"""Terminal path-entry prompts."""
import curses
from copy import copy
from ..config import StreamConnection, configure_streams

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


def connection_settings(screen, args):
    """Gather edits on a copy; callers disconnect only after all validation succeeds."""
    updated = copy(args)
    streams = []
    for index, stream in enumerate(args.streams):
        name = stream.name.title()
        kind = prompt(screen, f'{name} transport (mqtt/tcp):', stream.transport).lower()
        host = prompt(screen, f'{name} host:', stream.host)
        default_port = stream.port if kind == stream.transport else (8080+index if kind == 'tcp' else 8883 if args.tls else 1883)
        port = int(prompt(screen, f'{name} port:', str(default_port)))
        topic = prompt(screen, f'{name} MQTT publish topic:', stream.topic) if kind == 'mqtt' else stream.topic
        streams.append(StreamConnection(stream.name, kind, host, port, topic))
    if any(s.transport == 'mqtt' for s in streams):
        defaults = ','.join(args.subscribe or [s.topic for s in streams if s.transport == 'mqtt'])
        value = prompt(screen, 'MQTT subscription filters (comma-separated):', defaults)
        updated.subscribe = [t.strip() for t in value.split(',') if t.strip()]
        if not updated.subscribe:
            raise ValueError('At least one MQTT subscription filter is required')
    else:
        updated.subscribe = []
    configure_streams(updated, streams)
    return updated
