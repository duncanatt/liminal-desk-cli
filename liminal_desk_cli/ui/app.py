"""Existing curses interface for the coordinated replay engine."""
import curses
import time
from pathlib import Path
from collections import Counter
from ..replay.engine import Replay
from ..replay.schedule import Schedule
from ..transports.manager import TransportManager
from .screens import prompt, connection_settings
from .widgets import scroll_offset

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
    broker = TransportManager(args)
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
            text(1, broker.state + (' | DRY RUN' if args.dry_run else ''))
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
            text(14, 'C connect/disconnect  B connections  L load files  A run  D step mode')
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
            text(row, 'RECEIVED (MQTT subscriptions / TCP replies; separate from sent batches)', 1)
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
                    if broker.is_open:
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
                        raise ValueError('R resets the current experiment before connection setup')
                    updated = connection_settings(screen, args)
                    broker.close()
                    args = updated
                    broker = TransportManager(args)
                    replay = Replay(schedule, broker, args.topics)
                    scroll = 0
                    inspect_previous = False
                    started_wall = None
                    notice = 'Connections updated; C connects both streams. TCP is plain framed JSON, without application ACKs.'
            except Exception as exc:
                notice = str(exc)
    finally:
        broker.close()
