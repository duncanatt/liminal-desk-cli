"""Textual workspace for the shared replay engine and MQTT/TCP transports."""
import json
import time
from collections import Counter
from pathlib import Path
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Footer, Label, Select, Static, TabbedContent, TabPane
from ..replay.engine import Replay
from ..transports.manager import TransportManager
from .screens import Connections, TracePicker
from .theme import ONE_DARK, event_color, BLUE, PURPLE, MUTED, GREEN


class DeskApp(App):
    TITLE = 'Liminal Desk'
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = 'desk.tcss'
    BINDINGS = [
        Binding('c', 'connect', 'Connect'), Binding('b', 'connections', 'Connections'),
        Binding('o', 'open_trace', 'Open'), Binding('l', 'open_trace', show=False),
        Binding('a', 'run', 'Run'), Binding('d', 'step', 'Step mode'),
        Binding('n', 'next', 'Next'), Binding('p,space', 'pause', 'Pause'),
        Binding('r', 'reset', 'Reset'), Binding('q', 'quit', 'Quit'),
        Binding('escape', 'close_inspector', show=False),
        Binding('v', 'previous_batch', show=False),
        Binding('V', 'next_batch', show=False),
        Binding('f', 'latest_batch', 'Latest'),
        Binding('e', 'focus_events', show=False),
    ]

    def __init__(self, args, schedule, manager=None, preferences_path=None):
        super().__init__()
        self.args, self.schedule = args, schedule
        self.broker = manager or TransportManager(args)
        self.replay = Replay(schedule, self.broker, args.topics)
        self.paths = [Path(args.machine), Path(args.sensor)]
        self.names = [s.name for s in args.streams]
        self.selected_batch = None
        self._history_signature = None
        self._table_signature = None
        self._received_serial = 0
        self._received_rows = {}
        self._event_rows = {}
        self._inspected = None
        self._desk_closing = False
        self._reset_pending = False
        self._wall_start = None
        self._wall_end = None
        self._last_refresh = 0
        self._notice = 'C connects the streams. A runs automatically; D then N steps through events.'
        self._view_states = {}
        self.preferences_path = preferences_path or Path.home()/'.config/liminal-desk-cli/ui.json'
        self.preferences = self._read_preferences()
        self.register_theme(ONE_DARK)
        self.theme = ONE_DARK.name

    def _read_preferences(self):
        try:
            doc = json.loads(self.preferences_path.read_text())
            return doc if isinstance(doc, dict) else {}
        except (OSError, ValueError):
            return {}

    def compose(self) -> ComposeResult:
        yield Static('LIMINAL DESK', id='title')
        yield Static('', id='connection-status', markup=False)
        yield Static('', id='streams', markup=False)
        with Horizontal(id='selectors'):
            yield Label('Driver')
            yield Select([(name, i) for i, name in enumerate(self.names)], value=0,
                         allow_blank=False, id='driver', compact=True)
            yield Label('Step')
            yield Select([('Next driver event time', 'driver'), ('Next timestamp', 'timestamp'),
                          ('Next message', 'message')], value='driver', allow_blank=False,
                         id='step-mode', compact=True)
        with Horizontal(id='controls'):
            for label, identity in [('Connect', 'connect'), ('Run', 'run'), ('Step mode', 'step'),
                                    ('Next', 'next'), ('Pause', 'pause'), ('Reset', 'reset'),
                                    ('Open', 'open-trace'), ('Connections', 'connections')]:
                yield Button(label, id=f'control-{identity}', compact=True)
        yield Static('', id='progress')
        with Horizontal(id='workspace'):
            with TabbedContent(id='tabs'):
                with TabPane('Sent batches', id='sent'):
                    with Horizontal(id='sent-content'):
                        yield DataTable(id='history', cursor_type='row', show_header=False,
                                        show_row_labels=False)
                        with Vertical(id='events-area'):
                            yield Static('No batch yet. D then N sends the first batch.', id='batch-heading', markup=False)
                            with Horizontal(id='filters'):
                                yield Select([('All streams', -1)]+[(n, i) for i,n in enumerate(self.names)],
                                             value=-1, allow_blank=False, id='stream-filter', compact=True)
                                yield Select([('All kinds', '*')]+[(k,k) for k in sorted({
                                    e.payload.get('event', e.payload.get('type', 'event')) for e in self.schedule.events})],
                                    value='*', allow_blank=False, id='kind-filter', compact=True)
                                yield Static('Filters: none', id='filter-status', markup=False)
                            yield DataTable(id='events', cursor_type='row', show_row_labels=False,
                                            fixed_columns=1, cursor_foreground_priority='renderable')
                            yield Static('', id='row-status', markup=False)
                with TabPane('Received', id='received'):
                    yield Static('MQTT subscriptions / TCP replies · separate from sent batches', markup=False)
                    yield DataTable(id='received-events', cursor_type='row', show_row_labels=False,
                                    fixed_columns=1, cursor_foreground_priority='renderable')
                    yield Static('', id='receive-status', markup=False)
            with VerticalScroll(id='inspector'):
                yield Button('Close · Esc', id='inspector-close', compact=True)
                yield Static('', id='inspection', markup=False)
        yield Static('', id='next-preview', markup=False)
        yield Static(self._notice, id='notice', markup=False)
        yield Footer()

    def on_mount(self):
        self.query_one('#history', DataTable).add_column('Batch', width=24)
        self.query_one('#events', DataTable).add_columns('#', 'Sent at', 'Trace s', 'Stream', 'Kind', 'Device', 'Summary')
        self.query_one('#received-events', DataTable).add_columns('#', 'Received at', 'Source', 'Kind', 'Device', 'Summary')
        self.query_one('#inspector').display = False
        self._pump_timer = self.set_interval(.005, self._tick)
        self._refresh()
        self.query_one('#events', DataTable).focus()

    def on_resize(self, event):
        if self.is_mounted and self.query('#history'):
            self.query_one('#history').display = event.size.width >= 105
            self.query_one('#controls').display = event.size.width >= 100

    def on_unmount(self):
        self._desk_closing = True
        self._pump_timer.stop()
        self.broker.close()

    def action_quit(self):
        self._desk_closing = True
        self._pump_timer.stop()
        self.exit()

    def _tick(self):
        if self._desk_closing or not self.is_running or not self.query('#connection-status'):
            return
        try:
            self.broker.pump()
            self.replay.tick()
        except Exception as exc:
            self.replay.position = self.replay.elapsed()
            self.replay.state, self.replay.error = 'Error', str(exc)
            self._notice = str(exc)
        if self._reset_pending and self.replay.pending is None:
            self._reset_pending = False
            self.action_reset()
        now = time.monotonic()
        if now-self._last_refresh >= .08:
            self._last_refresh = now
            self._refresh()

    def _refresh(self):
        r = self.replay
        self.query_one('#connection-status', Static).update(Text(
            ('DRY RUN · ' if self.args.dry_run else '') + self.broker.state,
            style=GREEN if self.broker.ready else MUTED))
        self.query_one('#streams', Static).update('\n'.join(
            f'{s.name}'+(' · DRIVER' if i == r.driver else '')+f' · {s.transport.upper()} {s.host}:{s.port} · {self.paths[i].name}'
            for i,s in enumerate(self.args.streams)))
        self.query_one('#driver', Select).disabled = r.state in ('Running', 'Stepping', 'Paused')
        self.query_one('#step-mode', Select).disabled = r.state in ('Running', 'Stepping', 'Paused')
        self.query_one('#control-next', Button).disabled = r.state != 'Step ready'
        self.query_one('#control-pause', Button).disabled = r.state not in ('Running','Stepping','Paused')
        for identity in ('run','step'):
            self.query_one('#control-'+identity, Button).disabled = r.epoch is not None or not self.broker.ready
        if r.state in ('Completed','Error') and self._wall_end is None:
            self._wall_end = time.monotonic()
        wall = (self._wall_end or time.monotonic())-self._wall_start if self._wall_start is not None else 0
        progress = Text(f'{r.state} · trace {r.elapsed()/1000:6.3f} / {self.schedule.duration/1000:.3f} s · elapsed {wall:.1f} s · lag {r.max_late:.0f} ms\n')
        for i, total in enumerate(self.schedule.totals):
            fraction = r.counts[i]/total
            filled = int(16*fraction)
            progress.append(f'{self.names[i]:10} {"━"*filled}{"─"*(16-filled)} {fraction:6.1%}  {r.counts[i]}/{total}  ', BLUE if i == 0 else PURPLE)
            progress.append(r.status(i)+'\n')
        self.query_one('#progress', Static).update(progress)
        target, events = self.schedule.preview(r.index, r.driver, r.step_mode)
        counts = Counter(e.stream for e in events)
        self.query_one('#next-preview', Static).update(
            'All events sent.' if r.index == len(self.schedule.events) else
            f'Next: through {target/1000:.3f} s · '+ ' + '.join(f'{counts[i]} {n}' for i,n in enumerate(self.names)))
        self.query_one('#notice', Static).update(self._notice)
        if self.selected_batch is None and r.history:
            self.selected_batch = r.history[0].number
        self._refresh_history()
        self._refresh_events()
        self._refresh_received()
        table = self.query_one('#events', DataTable)
        self.query_one('#row-status', Static).update(
            f'Event {table.cursor_row+1 if table.row_count else 0} / {table.row_count} visible · Enter inspects payload · ↑↓ / PgUp / PgDn scroll')

    def _refresh_history(self):
        signature = tuple((b.number, len(b.sent), b.complete) for b in self.replay.history)
        if signature == self._history_signature:
            return
        table = self.query_one('#history', DataTable)
        for batch in self.replay.history:
            key = str(batch.number)
            label = Text(f'{batch.number:02} · {batch.end/1000:7.3f}s · {len(batch.sent)}/{len(batch.events)}',
                         style=BLUE if batch is self.replay.batch else MUTED)
            if key in table.rows:
                table.update_cell(key, next(iter(table.columns)), label)
            else:
                table.add_row(label, key=key)
        self._history_signature = signature

    @staticmethod
    def _summary(payload):
        if 'event' in payload:
            return ' · '.join(f'{k}={payload[k]}' for k in ('object', 'source', 'destination', 'target') if k in payload) or payload['event']
        if 'value' in payload:
            return f'{payload["value"]} {payload.get("unit", "")}' + (f' → {payload["target"]}' if 'target' in payload else '')
        return json.dumps(payload, ensure_ascii=True, separators=(',', ':'))

    def _batch(self):
        return next((b for b in self.replay.history if b.number == self.selected_batch), None)

    def _save_view(self):
        table = self.query_one('#events', DataTable)
        self._view_states[self.selected_batch] = (table.cursor_row, table.scroll_x, table.scroll_y)

    def _select_batch(self, number):
        if self.selected_batch == number:
            return
        self._save_view()
        self.selected_batch = number
        self._refresh_history()
        history = self.query_one('#history', DataTable)
        if history.row_count >= number:
            history.move_cursor(row=number-1)
        self._table_signature = None
        self._refresh_events()

    def _refresh_events(self):
        batch = self._batch()
        stream = self.query_one('#stream-filter', Select).value
        kind = self.query_one('#kind-filter', Select).value
        signature = (self.selected_batch, len(batch.sent) if batch else 0, stream, kind, batch.complete if batch else False)
        if signature == self._table_signature:
            return
        table = self.query_one('#events', DataTable)
        old = (table.cursor_row, table.scroll_x, table.scroll_y)
        same_batch = self._table_signature is not None and self._table_signature[0] == self.selected_batch
        table.clear()
        self._event_rows = {}
        if batch:
            for number, (event, payload) in enumerate(batch.sent, 1):
                event_kind = payload.get('event', payload.get('type', 'event'))
                if (stream != -1 and stream != event.stream) or (kind != '*' and kind != event_kind):
                    continue
                key = str(number)
                stamp = batch.sent_times[number-1]
                cells = [f'{number:02}', stamp, f'{event.at/1000:.3f}', self.names[event.stream],
                         event_kind, str(payload.get('device_id', '')), self._summary(payload)]
                table.add_row(*(Text(c, style=event_color(payload)+(' dim' if batch is not self.replay.batch else '')) for c in cells), key=key)
                self._event_rows[key] = (event, payload, stamp, batch.number)
        self.query_one('#batch-heading', Static).update(
            f'Batch {batch.number:02} · through {batch.end/1000:.3f} s · {len(batch.sent)}/{len(batch.events)} sent'+
            (' · complete' if batch.complete else ' · sending') if batch else 'No batch selected. D then N sends a batch.')
        self.query_one('#filter-status', Static).update(
            'Filters: active' if stream != -1 or kind != '*' else 'Filters: none')
        row, x, y = old if same_batch else self._view_states.get(self.selected_batch, (0,0,0))
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count-1), scroll=False)
        table.scroll_to(x=x, y=y, animate=False, force=True)
        self._table_signature = signature

    def _refresh_received(self):
        table = self.query_one('#received-events', DataTable)
        for serial, stamp, source, body, retained in self.broker.record_log:
            if serial <= self._received_serial:
                continue
            try:
                payload = json.loads(body)
            except (ValueError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            key = str(serial)
            table.add_row(Text(f'{serial:02}'), Text(stamp), Text(source),
                          Text(str(payload.get('type', payload.get('event', 'message'))), style=event_color(payload)),
                          Text(str(payload.get('device_id',''))), Text(self._summary(payload) if payload else str(body)), key=key)
            self._received_rows[key] = (stamp, source, body, retained)
            self._received_serial = serial
        while table.row_count > 3000:
            key = next(iter(table.rows))
            table.remove_row(key)
            self._received_rows.pop(key.value, None)
        self.query_one('#receive-status', Static).update(
            f'{sum(self.broker.received.values())} received · {table.row_count} retained in display (limit 3000) · '
            f'{self.broker.dropped} omitted before display')

    @on(DataTable.RowSelected, '#history')
    def history_selected(self, event):
        self._select_batch(int(event.row_key.value))
        self.query_one('#events', DataTable).focus()

    @on(Select.Changed, '#driver')
    def driver_changed(self, event):
        self.replay.driver = event.value

    @on(Select.Changed, '#step-mode')
    def step_mode_changed(self, event):
        self.replay.step_mode = event.value

    @on(Select.Changed, '#stream-filter')
    @on(Select.Changed, '#kind-filter')
    def filter_changed(self):
        if self.is_mounted:
            self._refresh_events()

    @on(DataTable.RowSelected, '#events')
    def inspect_sent(self, event):
        record = self._event_rows.get(event.row_key.value)
        if not record:
            return
        source, payload, stamp, batch = record
        connection = self.args.streams[source.stream]
        status = 'Simulated · no network' if self.args.dry_run else 'TCP written locally · no application ACK' if connection.transport == 'tcp' else 'Broker acknowledged' if self.args.qos else 'MQTT written locally · QoS 0'
        self._inspected = ('sent', event.row_key.value)
        detail = (f'Event {event.row_key.value} · batch {batch}\n\nStream: {connection.name}\n'
                  f'Transport: {connection.transport.upper()}\nDestination: {connection.destination}\n'
                  f'Sent at: {stamp}\nTrace time: {source.at/1000:.3f} s\nStatus: {status}\n\nPayload\n\n'
                  +json.dumps(payload, ensure_ascii=True, indent=2))
        self.query_one('#inspection', Static).update(self._payload_text(detail))
        self.query_one('#inspector').display = True

    @staticmethod
    def _payload_text(detail):
        import re
        text = Text(detail)
        start = detail.find('Payload\n\n') + len('Payload\n\n')
        for match in re.finditer(r'"(?:[^"\\]|\\.)*"|\b(?:-?\d+(?:\.\d+)?|true|false|null)\b', detail[start:]):
            token = match.group()
            end = start+match.end()
            color = PURPLE if token.startswith('"') and detail[end:].lstrip().startswith(':') else GREEN if token.startswith('"') else '#D19A66'
            text.stylize(color, start+match.start(), end)
        return text

    @on(DataTable.RowHighlighted, '#events')
    def inspect_highlighted(self, event):
        if self.query_one('#inspector').display and self._inspected and self._inspected[0] == 'sent':
            self.inspect_sent(event)

    @on(DataTable.RowSelected, '#received-events')
    def inspect_received(self, event):
        record = self._received_rows.get(event.row_key.value)
        if record:
            stamp, source, body, retained = record
            try:
                body = json.dumps(json.loads(body), ensure_ascii=True, indent=2)
            except ValueError:
                body = str(body)
            self._inspected = ('received', event.row_key.value)
            self.query_one('#inspection', Static).update(
                f'Received event {event.row_key.value}\n\nTime: {stamp}\nSource: {source}\nRetained: {retained}\n\nPayload\n\n{body}')
            self.query_one('#inspector').display = True

    @on(Button.Pressed, '#inspector-close')
    def action_close_inspector(self):
        self.query_one('#inspector').display = False

    @on(Button.Pressed)
    def control_pressed(self, event):
        identity = event.button.id or ''
        if identity.startswith('control-'):
            getattr(self, 'action_'+identity[8:].replace('-', '_'))()

    def _guard(self, operation):
        try:
            operation()
        except Exception as exc:
            self._notice = str(exc)

    def _require_idle(self):
        if self.replay.epoch is not None and self.replay.state != 'Completed':
            raise ValueError('Reset the experiment before changing files or connections.')

    def action_connect(self):
        def connect():
            self._require_idle()
            self.broker.close() if self.broker.is_open else self.broker.connect()
        self._guard(connect)

    def _start(self, mode):
        def start():
            self.replay.start(mode)
            self._wall_start = time.monotonic()
            self._notice = 'Running.' if mode == 'auto' else 'Step mode ready. N sends the next batch without real-time delays.'
        self._guard(start)

    def action_run(self):
        self._start('auto')

    def action_step(self):
        self._start('step')

    def action_next(self):
        def advance():
            before = self.replay.batch
            self.replay.next()
            if self.replay.batch is not before:
                self._select_batch(self.replay.batch.number)
                self.query_one('#tabs', TabbedContent).active = 'sent'
                self.query_one('#events', DataTable).focus()
        self._guard(advance)

    def action_pause(self):
        self.replay.pause()

    def _new_replay(self):
        driver, mode = self.replay.driver, self.replay.step_mode
        self.replay = Replay(self.schedule, self.broker, self.args.topics)
        self.replay.driver, self.replay.step_mode = driver, mode
        self.selected_batch = None
        self._history_signature = self._table_signature = None
        self._view_states.clear()
        self.query_one('#history', DataTable).clear()
        self.query_one('#events', DataTable).clear()
        self.query_one('#inspector').display = False
        self._wall_start = None
        self._wall_end = None

    def action_reset(self):
        # An in-flight receipt may still complete; resetting while it is pending
        # would permit overlap with a fresh run on the same transport.
        if self.replay.pending is not None:
            if self.replay.state == 'Error':
                self.broker.close()
                self.replay.pending = self.replay.inflight = None
            else:
                if self.replay.state in ('Running','Stepping'):
                    self.replay.pause()
                self._reset_pending = True
                self._notice = 'Finishing the current send before resetting.'
                return
        self._new_replay()
        self._notice = 'Reset. A or D starts a fresh experiment; received history is retained.'

    def action_open_trace(self):
        def open_file():
            self._require_idle()
            self.push_screen(TracePicker(self.paths, self.names, self.preferences.get('recent', []),
                                         self.preferences.get('folder')), self._files_loaded)
        self._guard(open_file)

    def _files_loaded(self, result):
        if result is None:
            return
        paths, schedule = result
        changed = next((p for p,old in zip(paths,self.paths) if p != old), paths[0])
        self.paths, self.schedule = paths, schedule
        self.args.machine, self.args.sensor = paths
        self.preferences = {'folder':str(changed.parent),
                            'recent':list(dict.fromkeys([str(changed)]+self.preferences.get('recent',[])))[:5]}
        try:
            self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
            self.preferences_path.write_text(json.dumps(self.preferences, indent=2))
        except OSError:
            pass
        self._new_replay()
        kinds = sorted({e.payload.get('event', e.payload.get('type','event')) for e in schedule.events})
        self.query_one('#kind-filter', Select).set_options([('All kinds','*')]+[(k,k) for k in kinds])
        self.query_one('#kind-filter', Select).value = '*'
        self._notice = 'Trace loaded and validated. Source files remain unchanged.'

    def action_connections(self):
        def settings():
            self._require_idle()
            self.push_screen(Connections(self.args), self._connections_saved)
        self._guard(settings)

    def _connections_saved(self, args):
        if args is None:
            return
        self.broker.close()
        self.args = args
        # Preserve existing receive history even when transport adapters change.
        serial = self._received_serial
        self.broker = TransportManager(args)
        self.broker.record_serial = serial
        self._new_replay()
        self._notice = 'Settings saved. C connects the streams.'

    def action_previous_batch(self):
        if self.selected_batch and self.selected_batch > 1:
            self._select_batch(self.selected_batch-1)

    def action_next_batch(self):
        if self.selected_batch and self.selected_batch < len(self.replay.history):
            self._select_batch(self.selected_batch+1)

    def action_latest_batch(self):
        if self.replay.history:
            self._select_batch(self.replay.history[-1].number)

    def action_focus_events(self):
        self.query_one('#events', DataTable).focus()
