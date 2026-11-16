"""Command-line settings and repository example paths."""
import argparse
from pathlib import Path

def parse_args(argv=None):
    here = Path(__file__).resolve().parent.parent / "examples" / "shop_floor"
    parser = argparse.ArgumentParser(description="Coordinated MQTT trace player. Run --help or --check without dependencies.")
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
    args = parser.parse_args(argv)
    if args.port is None:
        args.port = 8883 if args.tls else 1883
    if not 1 <= args.port <= 65535:
        parser.error('Port must be 1..65535')
    args.topics = [args.machine_topic, args.sensor_topic]
    if any(not t or '+' in t or '#' in t for t in args.topics) or len(set(args.topics)) != 2:
        parser.error('Publish topics must be distinct non-empty topics without wildcards')
    args.subscribe = list(dict.fromkeys(args.subscribe or args.topics))
    return parser, args
