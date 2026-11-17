"""Command-line settings and repository example paths."""
import argparse
from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class StreamConnection:
    name: str
    transport: str
    host: str
    port: int
    topic: str

    @property
    def destination(self):
        if self.transport == 'mqtt':
            return self.topic
        return f'tcp://{self.host}:{self.port} [{self.name}]'


def configure_streams(args, streams):
    """Validate all edits before applying them; keep existing MQTT destination names."""
    for stream in streams:
        if stream.transport not in ('mqtt', 'tcp'):
            raise ValueError('Transport must be mqtt or tcp')
        if not stream.host or not 1 <= stream.port <= 65535:
            raise ValueError('A non-empty host and port 1..65535 are required')
        if stream.transport == 'mqtt' and (not stream.topic or any(c in stream.topic for c in ('+', '#', '\0'))):
            raise ValueError('Publish topics must be non-empty and have no wildcards or NUL')
    destinations = [s.destination for s in streams]
    if len(set(destinations)) != len(destinations):
        raise ValueError('Stream destinations must be distinct (TCP connections may share an endpoint)')
    args.streams = list(streams)
    args.topics = destinations
    args.subscribe = list(dict.fromkeys(args.subscribe or [s.topic for s in streams if s.transport == 'mqtt']))

def parse_args(argv=None):
    here = Path(__file__).resolve().parent.parent / "examples" / "shop_floor"
    parser = argparse.ArgumentParser(description="Coordinated MQTT/TCP trace player. Run --help or --check without dependencies.")
    parser.add_argument('machine', nargs='?', type=Path, default=here/'machine_events.json')
    parser.add_argument('sensor', nargs='?', type=Path, default=here/'sensor_events.json')
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int)
    parser.add_argument('--transport', choices=('mqtt','tcp'), default='mqtt', help='Default transport for both streams')
    for name in ('machine', 'sensor'):
        parser.add_argument(f'--{name}-transport', choices=('mqtt','tcp'), help='Override transport for this stream')
        parser.add_argument(f'--{name}-host', help='Override host for this stream')
        parser.add_argument(f'--{name}-port', type=int, help='Override port for this stream')
    parser.add_argument('--max-frame-bytes', type=int, default=1048576, help='TCP inbound/outbound JSON frame limit (default 1 MiB)')
    parser.add_argument('--machine-topic', default='liminal/machine_data')
    parser.add_argument('--sensor-topic', default='liminal/sensor_data')
    parser.add_argument('--subscribe', action='append', help='Repeat for MQTT subscription filters; defaults to MQTT stream topics')
    parser.add_argument('--username', help='Password is read from MQTT_PASSWORD, never a command-line argument')
    parser.add_argument('--tls', action='store_true', help='Enable TLS for MQTT connections only')
    parser.add_argument('--ca-file')
    parser.add_argument('--qos', type=int, choices=(0, 1), default=1)
    parser.add_argument('--dry-run', action='store_true', help='Simulate publishing; no network and no MQTT dependency')
    parser.add_argument('--check', action='store_true', help='Validate and summarize files; no UI or network')
    args = parser.parse_args(argv)
    shared_port = args.port
    if args.port is None:
        args.port = (8080 if args.transport == 'tcp' else 8883 if args.tls else 1883)
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    if not 1 <= args.max_frame_bytes <= 4294967295:
        parser.error('max-frame-bytes must be 1..4294967295')
    streams = []
    for i, name in enumerate(('machine', 'sensor')):
        kind = getattr(args, name+'_transport') or args.transport
        port = getattr(args, name+'_port')
        if port is None:
            port = shared_port if shared_port is not None else (8080+i if kind == 'tcp' else 8883 if args.tls else 1883)
        streams.append(StreamConnection(name, kind, getattr(args,name+'_host') or args.host,
                                         port, getattr(args,name+'_topic')))
    if all(s.transport == 'tcp' for s in streams) and (args.tls or args.ca_file or args.username or args.subscribe):
        parser.error('TLS/authentication/subscriptions are MQTT-only options; TCP uses plain framed sockets')
    try:
        configure_streams(args, streams)
    except ValueError as exc:
        parser.error(str(exc))
    return parser, args
