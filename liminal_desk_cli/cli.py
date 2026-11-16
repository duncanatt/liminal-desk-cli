"""Command-line entry point; terminal imports are deferred for offline commands."""
import sys
from .config import parse_args
from .replay.schedule import Schedule

def main(argv=None):
    parser, args = parse_args(argv)
    try:
        schedule = Schedule([args.machine, args.sensor])
        if args.check:
            print(f'Valid: {schedule.totals[0]} machine + {schedule.totals[1]} sensor messages; duration {schedule.duration/1000:.3f}s')
            print('Shared timeline; machine first on timestamp ties; timestamps refreshed in memory on each run.')
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error('Interactive mode needs a terminal; use --check for validation')
        import curses
        from .ui.app import terminal
        curses.wrapper(terminal, args, schedule)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0
