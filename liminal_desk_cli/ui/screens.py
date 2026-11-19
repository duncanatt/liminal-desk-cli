"""Keyboard and mouse dialogs for validated files and connection settings."""
from copy import copy
from pathlib import Path
from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DirectoryTree, Input, Label, Select, Static
from ..config import StreamConnection, configure_streams
from ..replay.schedule import Schedule


class TracePicker(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, paths, names, recent=(), folder=None):
        super().__init__()
        self.paths, self.names, self.recent = list(paths), names, list(recent)
        self.folder = Path(folder or self.paths[0].parent)
        if not self.folder.is_dir():
            self.folder = Path.cwd()
        self.candidate = None
        self.validated = None

    def compose(self):
        with Vertical(id='file-dialog', classes='dialog'):
            yield Label('Open trace', classes='dialog-title')
            yield Select([(name, i) for i, name in enumerate(self.names)], value=0,
                         allow_blank=False, id='file-stream')
            yield Input(str(self.folder), id='file-path', placeholder='Directory or JSON file path')
            with Horizontal(id='file-browser'):
                yield DirectoryTree(self.folder, id='file-tree')
                with VerticalScroll(id='file-info'):
                    yield Static('Choose a file to preview and validate it.', id='file-preview', markup=False)
                    yield Label('Recent files')
                    for i, path in enumerate(self.recent[:5]):
                        yield Button(str(path), id=f'recent-{i}', classes='recent')
            yield Static('', id='file-error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Load trace', id='file-load', disabled=True)
                yield Button('Cancel', id='file-cancel')

    @on(Input.Submitted, '#file-path')
    def path_submitted(self, event):
        path = Path(event.value).expanduser()
        if path.is_dir():
            self.folder = path.resolve()
            self.query_one('#file-tree', DirectoryTree).path = self.folder
        else:
            self.validate_path(path)

    @on(DirectoryTree.FileSelected)
    def file_selected(self, event):
        self.validate_path(event.path)

    @on(Select.Changed, '#file-stream')
    def stream_changed(self):
        if self.candidate is not None:
            self.validate_path(self.candidate)

    @on(Input.Changed, '#file-path')
    def path_edited(self):
        # Editing invalidates the preview; Enter validates the new path.
        self.validated = None
        self.query_one('#file-load', Button).disabled = True

    def validate_path(self, path):
        self.candidate = Path(path).expanduser().resolve()
        self.query_one('#file-path', Input).value = str(self.candidate)
        # Input.Changed is queued, so defer validation until it has been handled.
        self.call_after_refresh(self._validate_candidate)

    def _validate_candidate(self):
        paths = self.paths.copy()
        index = self.query_one('#file-stream', Select).value
        paths[index] = self.candidate
        try:
            schedule = Schedule(paths)
        except Exception as exc:
            self.validated = None
            self.query_one('#file-error', Static).update(str(exc))
            self.query_one('#file-preview', Static).update('Invalid trace; existing files remain loaded.')
        else:
            self.validated = (paths, schedule)
            self.query_one('#file-error', Static).update('')
            self.query_one('#file-preview', Static).update(
                f'{self.candidate.name}\n\nVersion 1\n{schedule.totals[index]:,} messages\n'
                f'Duration {schedule.duration/1000:.3f} s\n\nValid trace · shared timestamp origin')
        self.query_one('#file-load', Button).disabled = self.validated is None

    @on(Button.Pressed)
    def pressed(self, event):
        identity = event.button.id or ''
        if identity == 'file-cancel':
            self.action_cancel()
        elif identity == 'file-load' and self.validated:
            self.dismiss(self.validated)
        elif identity.startswith('recent-'):
            self.validate_path(self.recent[int(identity.split('-')[1])])

    def action_cancel(self):
        self.dismiss(None)


class Connections(ModalScreen):
    BINDINGS = [('escape', 'cancel', 'Cancel')]

    def __init__(self, args):
        super().__init__()
        self.args = args

    def compose(self):
        with Vertical(id='connection-dialog', classes='dialog'):
            yield Label('Stream connections', classes='dialog-title')
            with VerticalScroll(id='connection-fields'):
                for i, stream in enumerate(self.args.streams):
                    yield Label(stream.name, classes='stream-label')
                    with Horizontal(classes='connection-row'):
                        yield Select([('MQTT', 'mqtt'), ('TCP', 'tcp')], value=stream.transport,
                                     allow_blank=False, id=f'transport-{i}')
                        yield Input(stream.host, id=f'host-{i}', placeholder='Host')
                        yield Input(str(stream.port), id=f'port-{i}', placeholder='Port')
                    yield Input(stream.topic, id=f'topic-{i}', placeholder='MQTT publish topic (unused for TCP)')
                yield Label('MQTT options · unused for TCP')
                yield Input(','.join(self.args.subscribe), id='subscriptions', placeholder='Subscription filters, comma-separated')
                with Horizontal(classes='connection-row'):
                    yield Select([('QoS 0 · local write', 0), ('QoS 1 · broker ACK', 1)],
                                 value=self.args.qos, allow_blank=False, id='qos')
                    yield Checkbox('TLS', value=self.args.tls, id='tls')
                yield Input(self.args.username or '', id='username', placeholder='MQTT username · password from MQTT_PASSWORD')
                yield Input(self.args.ca_file or '', id='ca-file', placeholder='Optional CA certificate path')
                yield Static('TCP: 4-byte big-endian length + UTF-8 JSON. Plain sockets; no application ACK.', markup=False)
            yield Static('', id='connection-error', markup=False)
            with Horizontal(classes='dialog-actions'):
                yield Button('Save settings', id='connection-save')
                yield Button('Cancel', id='connection-cancel')

    @on(Button.Pressed, '#connection-save')
    def save(self):
        try:
            updated = copy(self.args)
            streams = []
            for i, old in enumerate(self.args.streams):
                streams.append(StreamConnection(old.name,
                    self.query_one(f'#transport-{i}', Select).value,
                    self.query_one(f'#host-{i}', Input).value.strip(),
                    int(self.query_one(f'#port-{i}', Input).value),
                    self.query_one(f'#topic-{i}', Input).value.strip()))
            updated.subscribe = [x.strip() for x in self.query_one('#subscriptions', Input).value.split(',') if x.strip()]
            updated.qos = self.query_one('#qos', Select).value
            updated.tls = self.query_one('#tls', Checkbox).value
            updated.username = self.query_one('#username', Input).value or None
            updated.ca_file = self.query_one('#ca-file', Input).value or None
            if updated.ca_file and not Path(updated.ca_file).expanduser().is_file():
                raise ValueError('CA certificate does not exist')
            configure_streams(updated, streams)
        except Exception as exc:
            self.query_one('#connection-error', Static).update(str(exc))
        else:
            self.dismiss(updated)

    @on(Button.Pressed, '#connection-cancel')
    def action_cancel(self):
        self.dismiss(None)
