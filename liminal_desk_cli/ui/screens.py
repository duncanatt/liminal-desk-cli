"""Terminal path-entry prompts."""
import curses

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
