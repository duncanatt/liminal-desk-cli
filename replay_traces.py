#!/usr/bin/env python3
"""Coordinated MQTT trace player. Run --help or --check without dependencies."""
import argparse
import copy
import curses
import json
import os
from pathlib import Path
import queue
import sys
import time
import textwrap
from collections import Counter, deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Event:
    at: int
    stream: int
    order: int
    payload: dict


@dataclass
class StepBatch:
    number: int
    start: int
    end: int
    events: list
    sent: list = field(default_factory=list)
    complete: bool = False
    sent_times: list = field(default_factory=list)

    def heading(self):
        counts = Counter(e.stream for e in self.events)
        status = 'Last step sent' if self.complete else 'Sending step'
        return (f'{status} {self.number} | t={self.start/1000:.3f} -> {self.end/1000:.3f}'
                f' | {counts[0]} machine + {counts[1]} sensor | {len(self.sent)}/{len(self.events)} sent')

    def summary(self):
        machines = [f'{e.payload.get("device_id", "?")} {e.payload.get("event", "?")}'
                    for e in self.events if e.stream == 0]
        lines = ['Machine: ' + (', '.join(machines) or 'none (sensor tail)')]
        groups = {}
        for e in self.events:
            if e.stream == 1:
                groups.setdefault(e.payload.get('device_id', '?'), {}).setdefault(
                    e.payload.get('type', '?'), []).append(e.at)
        for device, modalities in sorted(groups.items()):
            parts = [f'{kind}: {len(times)} [{min(times)/1000:.3f}-{max(times)/1000:.3f}]'
                     for kind, times in sorted(modalities.items())]
            lines.append(device + ' | ' + ' | '.join(parts))
        return lines

    def details(self, topics, width):
        return [line for line, color, number in self.detail_rows(topics, width)]

    def detail_rows(self, topics, width):
        rows = []
        digits = max(2, len(str(len(self.events))))
        for number, (event, payload) in enumerate(self.sent, 1):
            stamp = self.sent_times[number-1] if number <= len(self.sent_times) else '--:--:--'
            prefix = f'{number:0{digits}d}: '
            body = f'{stamp} {topics[event.stream]} ' + json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
            color = 4 if event.stream == 0 else 5 if payload.get('type') == 'vibration' else 6
            wrapped = textwrap.wrap(body, max(8, width-len(prefix)), break_long_words=True,
                                    break_on_hyphens=False, replace_whitespace=False)
            for i, line in enumerate(wrapped):
                rows.append((prefix+line if i == 0 else ' '*len(prefix)+line, color, number))
        return rows or [('No confirmed sends in this step yet.', 0, 0)]


def scroll_offset(current, action, page_size, row_count):
    """Clamp scrolling independently of terminal dimensions or payload wrapping."""
    end = max(0, row_count-page_size)
    if action == 'home':
        return 0
    if action == 'end':
        return end
    delta = {'down':1, 'up':-1, 'page_down':page_size, 'page_up':-page_size}.get(action, 0)
    return min(end, max(0, current+delta))


def load_trace(path, stream):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key: {key}')
            result[key] = value
        return result
    doc = json.loads(Path(path).read_text(), object_pairs_hook=unique,
                     parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    if (not isinstance(doc, dict) or set(doc) != {'version', 'steps'}
            or type(doc['version']) is not int or doc['version'] != 1
            or not isinstance(doc['steps'], list)):
        raise ValueError(f'{path}: expected version 1 and steps array')
    elapsed = 0
    events = []
    for i, step in enumerate(doc['steps']):
        if not isinstance(step, dict):
            raise ValueError(f'{path}: step {i+1} must be an object')
        if step.get('type') == 'delay' and set(step) == {'type', 'duration_ms'}:
            duration = step['duration_ms']
            if type(duration) is not int or duration < 0:
                raise ValueError(f'{path}: step {i+1}: invalid delay')
            elapsed += duration
        elif step.get('type') == 'send' and set(step) == {'type', 'payload'}:
            if not isinstance(step['payload'], dict):
                raise ValueError(f'{path}: step {i+1}: payload must be an object')
            payload = step['payload']
            if type(payload.get('timestamp_ms')) is not int:
                raise ValueError(f'{path}: step {i+1}: integer timestamp_ms required')
            events.append(Event(elapsed, stream, i, payload))
        else:
            raise ValueError(f'{path}: unsupported step {i+1}')
    if not events:
        raise ValueError(f'{path}: no send events')
    origins = {e.payload['timestamp_ms'] - e.at for e in events}
    if len(origins) != 1:
        raise ValueError(f'{path}: timestamps disagree with delay offsets')
    return events, elapsed, origins.pop()


class Schedule:
    def __init__(self, paths):
        loaded = [load_trace(path, i) for i, path in enumerate(paths)]
        if loaded[0][2] != loaded[1][2]:
            raise ValueError('The two traces must share the same timestamp origin')
        self.events = sorted(loaded[0][0] + loaded[1][0],
                             key=lambda e: (e.at, e.stream, e.order))
        self.duration = max(x[1] for x in loaded)
        self.totals = [len(x[0]) for x in loaded]
        self.machine_times = sorted({e.at for e in loaded[0][0]})

    def preview(self, index):
        target = next((e.at for e in self.events[index:] if e.stream == 0), None)
        if target is None:
            target = self.duration
        batch = [e for e in self.events[index:] if e.at <= target]
        return target, batch


class Broker:
    def __init__(self, args):
        self.args = args
        self.client = None
        self.connected = False
        self.state = 'Disconnected'
        self.subscribed = set()
        self.received = Counter()
        self.log = deque(maxlen=300)
        self.notifications = queue.Queue(maxsize=2000)
        self.dropped = 0

    def notify(self, kind, value):
        try:
            self.notifications.put_nowait((kind, value))
        except queue.Full:
            self.dropped += 1

    def connect(self):
        self.close()
        self.subscribed.clear()
        self.received.clear()
        if self.args.dry_run:
            self.connected = True
            self.state = 'Dry run: no network connection'
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError('Install paho-mqtt: python3 -m pip install "paho-mqtt>=2,<3"') from exc
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  reconnect_on_failure=False)
        self.client.connect_timeout = 5
        if self.args.username:
            self.client.username_pw_set(self.args.username, os.environ.get('MQTT_PASSWORD'))
        if self.args.tls:
            self.client.tls_set(ca_certs=self.args.ca_file)
        def on_connect(client, userdata, flags, reason, properties):
            self.connected = not reason.is_failure
            self.notify('state', 'Connected' if self.connected else f'Connection rejected: {reason}')
            if self.connected:
                result, mid = client.subscribe([(topic, self.args.qos) for topic in self.args.subscribe])
                if result != mqtt.MQTT_ERR_SUCCESS:
                    self.notify('state', f'Subscription request failed: {result}')
        def on_subscribe(client, userdata, mid, reasons, properties):
            if any(reason.is_failure for reason in reasons):
                self.notify('state', 'Broker rejected a subscription')
            else:
                self.notify('subscribed', self.args.subscribe)
        def on_disconnect(client, userdata, flags, reason, properties):
            self.connected = False
            self.notify('state', f'Disconnected: {reason}')
        def on_message(client, userdata, msg):
            self.notify('message', (msg.topic, msg.payload[:2048].decode('utf-8', 'replace'), msg.retain))
        self.client.on_connect = on_connect
        self.client.on_subscribe = on_subscribe
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message
        self.state = 'Connecting / awaiting subscriptions...'
        self.client.connect(self.args.host, self.args.port, keepalive=30)
        self.client.loop_start()

    def pump(self):
        while True:
            try:
                kind, value = self.notifications.get_nowait()
            except queue.Empty:
                break
            if kind == 'message':
                topic, body, retained = value
                self.received[topic] += 1
                self.log.append((time.strftime('%H:%M:%S'), topic, body, retained))
            elif kind == 'subscribed':
                self.subscribed.update(value)
                self.state = 'Connected; subscriptions active'
            else:
                self.state = value

    @property
    def ready(self):
        return self.connected and (self.args.dry_run or set(self.args.subscribe) <= self.subscribed)

    def send(self, topic, payload):
        if not self.connected:
            raise RuntimeError('Broker connection lost; retry as a new experiment')
        if self.args.dry_run:
            return None
        info = self.client.publish(topic, json.dumps(payload, separators=(',', ':'), allow_nan=False),
                                   qos=self.args.qos, retain=False)
        if info.rc != 0:
            raise RuntimeError(f'MQTT publish failed: {info.rc}')
        return info

    def close(self):
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
        self.connected = False
        self.state = 'Disconnected'


class Replay:
    """One timeline; one in-flight send. MQTT work stays on its network thread."""
    def __init__(self, schedule, broker, topics, clock=time.monotonic):
        self.schedule, self.broker, self.topics, self.clock = schedule, broker, topics, clock
        self.index = 0
        self.counts = [0, 0]
        self.state = 'Ready'
        self.mode = 'auto'
        self.epoch = None
        self.position = 0.0
        self.anchor = clock()
        self.target = None
        self.inflight = None
        self.pending = None
        self.pending_since = 0
        self.pending_wall = None
        self.last = ['No messages sent', 'No messages sent']
        self.max_late = 0.0
        self.error = ''
        self.paused_from = None
        self.batch = None
        self.previous_batch = None

    def elapsed(self):
        if self.mode == 'auto' and self.state == 'Running':
            return min(self.schedule.duration, self.position + (self.clock()-self.anchor)*1000)
        return self.position

    def start(self, mode):
        if not self.broker.ready:
            raise RuntimeError('Connect and wait for subscription confirmation first (C)')
        if self.epoch is not None:
            raise RuntimeError('Use R to retry before starting a fresh run')
        self.epoch = time.time_ns() // 1_000_000
        self.mode = mode
        self.anchor = self.clock()
        self.state = 'Running' if mode == 'auto' else 'Step ready'

    def pause(self):
        if self.state in ('Running', 'Stepping'):
            self.position = self.elapsed()
            self.paused_from = self.state
            self.state = 'Paused'
        elif self.state == 'Paused':
            self.anchor = self.clock()
            self.state = self.paused_from or 'Running'

    def next(self):
        if self.mode != 'step' or self.state != 'Step ready':
            return
        self.target, events = self.schedule.preview(self.index)
        self.previous_batch = self.batch
        self.batch = StepBatch(1 if self.batch is None else self.batch.number+1,
                               int(self.position), self.target, events)
        self.state = 'Stepping'

    def tick(self):
        if self.epoch is None or self.state in ('Completed', 'Error'):
            return
        if not self.broker.connected:
            raise RuntimeError('Connection lost. Partial replay stopped; R starts a new experiment.')
        # Complete the pending send even when paused, but never start another.
        if self.pending is not None:
            if self.inflight is not None and not self.inflight.is_published():
                if self.clock()-self.pending_since > 10:
                    raise RuntimeError('Publish confirmation timed out; delivery is uncertain. Retry as a new run.')
                return
            event = self.pending
            self.counts[event.stream] += 1
            if self.mode == 'step' and self.batch is not None:
                payload = copy.deepcopy(event.payload)
                payload['timestamp_ms'] = self.epoch + event.at
                self.batch.sent.append((event, payload))
                self.batch.sent_times.append(self.pending_wall)
            name = event.payload.get('event', event.payload.get('type', 'event'))
            self.last[event.stream] = f'{event.payload.get("device_id", "?")} {name} at t={event.at/1000:.3f}'
            self.index += 1
            self.pending = self.inflight = None
        if self.state not in ('Running', 'Stepping'):
            return
        limit = self.elapsed() if self.mode == 'auto' else self.target
        if self.index < len(self.schedule.events):
            event = self.schedule.events[self.index]
            if event.at <= limit:
                payload = copy.deepcopy(event.payload)
                payload['timestamp_ms'] = self.epoch + event.at
                if self.mode == 'step':
                    self.position = event.at
                else:
                    self.max_late = max(self.max_late, limit-event.at)
                self.pending_since = self.clock()
                self.pending_wall = time.strftime('%H:%M:%S')
                self.inflight = self.broker.send(self.topics[event.stream], payload)
                self.pending = event
                return
        if self.mode == 'step':
            self.position = self.target
            self.state = 'Step ready'
            self.batch.complete = True
        # Honor trailing delays even after the last send.
        if self.index == len(self.schedule.events) and (self.mode == 'step' or limit >= self.schedule.duration):
            self.position = self.schedule.duration
            self.state = 'Completed'

    def status(self, stream):
        if self.pending is not None and self.pending.stream == stream:
            return 'Sending: awaiting broker ACK' if not self.broker.args.dry_run else 'Sending (simulated)'
        upcoming = next((e for e in self.schedule.events[self.index:] if e.stream == stream), None)
        if upcoming is None:
            return 'All messages sent'
        if self.state == 'Error':
            return 'Stopped after error'
        if self.state == 'Step ready':
            return f'Waiting for N; next t={upcoming.at/1000:.3f}'
        delay = max(0, upcoming.at-self.elapsed())/1000
        label = 'Paused' if self.state == 'Paused' else 'Waiting'
        return f'{label}: delay remaining {delay:.3f}s (next t={upcoming.at/1000:.3f})'


def prompt(screen, label, default=''):
    screen.nodelay(False)
    curses.curs_set(1)
    curses.echo()
    try:
        screen.erase()
        screen.addstr(1, 1, label[:max(1, screen.getmaxyx()[1]-3)])
        screen.addstr(3, 1, f'Enter = {default}'[:max(1, screen.getmaxyx()[1]-3)])
        screen.move(5, 1)
        value = screen.getstr().decode('utf-8').strip()
        return value or default
    finally:
        curses.noecho()
        curses.curs_set(0)
        screen.nodelay(True)


def terminal(screen, args, schedule):
    curses.curs_set(0)
    screen.nodelay(True)
    screen.keypad(True)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
    except curses.error:
        pass
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_MAGENTA, -1)
        curses.init_pair(3, curses.COLOR_GREEN, -1)
        curses.init_pair(4, 33 if curses.COLORS >= 256 else curses.COLOR_BLUE, -1)
        curses.init_pair(5, 130 if curses.COLORS >= 256 else curses.COLOR_YELLOW, -1)
        curses.init_pair(6, 141 if curses.COLORS >= 256 else curses.COLOR_MAGENTA, -1)
    broker = Broker(args)
    replay = Replay(schedule, broker, args.topics)
    notice = 'C connect | A automatic replay | D step mode, then N next'
    paths = [args.machine, args.sensor]
    started_wall = None
    expanded = False
    inspect_previous = False
    scroll = 0
    def text(y, value, color=0, style=0):
        h, w = screen.getmaxyx()
        if 0 <= y < h-1:
            # MQTT payloads may contain terminal control characters.
            safe = ''.join(c if c.isprintable() else ' ' for c in str(value))
            try:
                screen.addnstr(y, 1, safe, max(0, w-2), curses.color_pair(color) | style)
            except curses.error:
                pass
    try:
        while True:
            broker.pump()
            try:
                replay.tick()
            except Exception as exc:
                replay.position = replay.elapsed()
                replay.state, replay.error = 'Error', str(exc)
                notice = str(exc)
            screen.erase()
            text(0, 'LIMINAL REPLAY  |  coordinated MQTT publisher + subscriber', 1)
            text(1, f'{args.host}:{args.port} | {broker.state} | QoS {args.qos}' + (' | DRY RUN' if args.dry_run else ''))
            wall = time.monotonic()-started_wall if started_wall else 0
            text(2, f'{replay.state} / {replay.mode} | Trace {replay.elapsed()/1000:.3f}/{schedule.duration/1000:.3f}s | Wall {wall:.1f}s | Max send lag {replay.max_late:.0f}ms')
            text(3, f'Replay Unix origin: {replay.epoch or "not started"}; source files are never modified')
            for stream in (0, 1):
                row = 5+stream*4
                total = schedule.totals[stream]
                sent = replay.counts[stream]
                width = max(10, min(36, screen.getmaxyx()[1]-48))
                fill = int(width*sent/total)
                text(row, f'{"MACHINE" if stream == 0 else "SENSOR "} [{"#"*fill}{"-"*(width-fill)}] {100*sent/total:6.2f}%  {sent}/{total}', stream+1)
                text(row+1, f'{args.topics[stream]} | {replay.status(stream)}', stream+1)
                text(row+2, f'Last sent: {replay.last[stream]}', stream+1)
            target, batch = schedule.preview(replay.index)
            counts = Counter(e.stream for e in batch)
            machine = [f'{e.payload.get("device_id")}:{e.payload.get("event", "?")}' for e in batch if e.stream == 0]
            text(13, f'Next step -> t={target/1000:.3f}: {counts[0]} machine, {counts[1]} sensor | '+(', '.join(machine) or 'finish sensor tail'))
            text(14, 'C connect/disconnect  B broker setup  L load files  A run  D step mode')
            text(15, 'N next slice  P pause/resume  E expand  R reset  Q close')
            text(16, notice)
            height = screen.getmaxyx()[0]
            row = 18
            if replay.batch is not None:
                text(row, replay.batch.heading(), 3, curses.A_BOLD)
                row += 1
                for line in replay.batch.summary():
                    text(row, line, 3)
                    row += 1
                if replay.previous_batch is not None:
                    text(row, '-'*max(0, screen.getmaxyx()[1]-2), style=curses.A_DIM)
                    row += 1
                    text(row, 'Previous: ' + replay.previous_batch.heading().replace('Last step sent ', ''),
                         style=curses.A_DIM)
                    row += 1
            else:
                text(row, 'LAST STEP SENT | D then N to send and inspect a batch', 3)
                row += 1
            row += 1
            text(row, 'RECEIVED (subscription log, separate from sent batches)', 1)
            row += 1
            text(row, ' | '.join(f'{topic}: {n}' for topic, n in broker.received.items()) or 'No messages received')
            row += 1
            log_space = max(0, height-row-2)
            visible_log = list(broker.log)[-log_space:] if log_space else []
            for row, (stamp, topic, body, retained) in enumerate(visible_log, row):
                text(row, f'{stamp} {topic}{" [retained]" if retained else ""} {body}')
            if broker.dropped:
                text(height-2, f'Receive display queue overflow: {broker.dropped} messages omitted')
            if expanded:
                screen.erase()
                inspected = replay.previous_batch if inspect_previous else replay.batch
                text(0, 'SENT BATCH | E overview | V previous/current | arrows/J/K scroll | PgUp/PgDn', 3, curses.A_BOLD)
                text(1, f'{replay.state} | P pause/resume | N next slice | Q close')
                text(2, notice)
                if inspected is None:
                    text(3, 'No batch available. Use D then N to send the first slice.')
                else:
                    color = 0 if inspect_previous else 3
                    style = curses.A_DIM if inspect_previous else curses.A_BOLD
                    text(3, inspected.heading(), color, style)
                    lines = inspected.detail_rows(args.topics, screen.getmaxyx()[1]-3)
                    page_size = max(1, height-7)
                    scroll = min(scroll, max(0, len(lines)-page_size))
                    text(4, f'{len(inspected.sent)} confirmed events | rows {scroll+1}-{min(scroll+page_size,len(lines))}/{len(lines)} | Home/End first/last')
                    text(5, 'Machine = blue | vibration = brown | LiDAR = purple | numbers restart per batch')
                    for y, (line, event_color, number) in enumerate(lines[scroll:scroll+page_size], 6):
                        text(y, line, event_color, curses.A_DIM if inspect_previous else 0)
            screen.refresh()
            key = screen.getch()
            if key == -1:
                time.sleep(.002)
                continue
            special = {curses.KEY_UP:'up', curses.KEY_DOWN:'down', curses.KEY_PPAGE:'page_up',
                       curses.KEY_NPAGE:'page_down', curses.KEY_HOME:'home', curses.KEY_END:'end'}
            if key == curses.KEY_MOUSE:
                try:
                    mouse_state = curses.getmouse()[4]
                    key = 'up' if mouse_state & getattr(curses, 'BUTTON4_PRESSED', 0) else 'down' if mouse_state & getattr(curses, 'BUTTON5_PRESSED', 0) else ''
                except curses.error:
                    key = ''
            else:
                key = special.get(key, chr(key).lower() if 0<=key<256 else '')
            try:
                active = replay.epoch is not None and replay.state != 'Completed'
                if key == 'q':
                    break
                if key == 'r':
                    replay = Replay(schedule, broker, args.topics)
                    scroll = 0
                    inspect_previous = False
                    started_wall = None
                    notice = 'Reset. A or D starts from the beginning with a new Unix origin; received history is retained.'
                elif key in ('p', ' '):
                    replay.pause()
                elif key == 'n':
                    old_batch = replay.batch
                    replay.next()
                    if replay.batch is not old_batch:
                        scroll = 0
                        inspect_previous = False
                        expanded = True
                elif key == 'e':
                    expanded = not expanded
                    scroll = 0
                elif key == 'v' and expanded:
                    inspect_previous = not inspect_previous
                    scroll = 0
                elif expanded and key in ('j','k','[',']','up','down','page_up','page_down','home','end','g'):
                    action = {'j':'down','k':'up','[':'page_up',']':'page_down','g':'home'}.get(key,key)
                    inspected = replay.previous_batch if inspect_previous else replay.batch
                    if inspected is not None:
                        row_count = len(inspected.detail_rows(args.topics, screen.getmaxyx()[1]-3))
                        scroll = scroll_offset(scroll, action, max(1, height-7), row_count)
                elif key in ('a', 'd'):
                    replay.start('auto' if key == 'a' else 'step')
                    started_wall = time.monotonic()
                    notice = 'Running' if key == 'a' else 'Step mode ready. N sends the next time slice without real-time delays.'
                elif key == 'c':
                    if active:
                        raise ValueError('R resets the current experiment before connecting/disconnecting')
                    if broker.client is not None or broker.connected:
                        broker.close()
                    else:
                        broker.connect()
                elif key == 'l':
                    if active:
                        raise ValueError('R resets the current experiment before loading files')
                    new_paths = [prompt(screen, 'Machine trace path:', str(paths[0])),
                                 prompt(screen, 'Sensor trace path:', str(paths[1]))]
                    new_schedule = Schedule([Path(x).expanduser() for x in new_paths])
                    paths, schedule = new_paths, new_schedule
                    replay = Replay(schedule, broker, args.topics)
                    scroll = 0
                    inspect_previous = False
                    notice = 'Both files loaded and validated.'
                elif key == 'b':
                    if active:
                        raise ValueError('R resets the current experiment before broker setup')
                    host = prompt(screen, 'Broker host:', args.host)
                    port = int(prompt(screen, 'Broker port:', str(args.port)))
                    if not 1 <= port <= 65535:
                        raise ValueError('Port must be 1..65535')
                    subscriptions = prompt(screen, 'Subscription topics (comma-separated):', ','.join(args.subscribe))
                    topics = [x.strip() for x in subscriptions.split(',') if x.strip()]
                    if not topics:
                        raise ValueError('At least one subscription topic is required')
                    broker.close()
                    args.host, args.port, args.subscribe = host, port, topics
                    notice = 'Broker settings updated; C connects. Publish topics are configured with command-line options.'
            except Exception as exc:
                notice = str(exc)
    finally:
        broker.close()


def main():
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('machine', nargs='?', type=Path, default=here/'machine_events.json')
    parser.add_argument('sensor', nargs='?', type=Path, default=here/'sensor_events.json')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int)
    parser.add_argument('--machine-topic', default='liminal/machine_data')
    parser.add_argument('--sensor-topic', default='liminal/sensor_data')
    parser.add_argument('--subscribe', action='append', help='Repeat for additional MQTT topic filters; defaults to both publish topics')
    parser.add_argument('--username', help='Password is read from MQTT_PASSWORD, never a command-line argument')
    parser.add_argument('--tls', action='store_true')
    parser.add_argument('--ca-file')
    parser.add_argument('--qos', type=int, choices=(0, 1), default=1)
    parser.add_argument('--dry-run', action='store_true', help='Simulate publishing; no network and no MQTT dependency')
    parser.add_argument('--check', action='store_true', help='Validate and summarize files; no UI or network')
    args = parser.parse_args()
    if args.port is None:
        args.port = 8883 if args.tls else 1883
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    args.topics = [args.machine_topic, args.sensor_topic]
    if any(not t or '+' in t or '#' in t for t in args.topics) or len(set(args.topics)) != 2:
        parser.error('Publish topics must be distinct non-empty topics without wildcards')
    args.subscribe = list(dict.fromkeys(args.subscribe or args.topics))
    try:
        schedule = Schedule([args.machine, args.sensor])
        if args.check:
            print(f'Valid: {schedule.totals[0]} machine + {schedule.totals[1]} sensor messages; duration {schedule.duration/1000:.3f}s')
            print('Shared timeline; machine first on timestamp ties; timestamps refreshed in memory on each run.')
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error('Interactive mode needs a terminal; use --check for validation')
        curses.wrapper(terminal, args, schedule)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
