"""Exact sRGB colours from nathanbuchar's One Dark Terminal profile."""
from textual.theme import Theme

BACKGROUND = '#1E2127'
FOREGROUND = '#ABB2BF'
MUTED = '#5C6370'
SELECTION = '#3A3F4B'
BLUE = '#61AFEF'
AMBER = '#D19A66'
PURPLE = '#C678DD'
GREEN = '#98C379'
RED = '#E06C75'
CYAN = '#56B6C2'

ONE_DARK = Theme(
    name='liminal-one-dark', primary=BLUE, secondary=PURPLE, accent=CYAN,
    warning=AMBER, error=RED, success=GREEN, foreground=FOREGROUND,
    background=BACKGROUND, surface=BACKGROUND, panel=BACKGROUND, boost=SELECTION,
    dark=True, text_alpha=1,
    variables={'border': MUTED, 'border-blurred': MUTED,
               'footer-background': BACKGROUND, 'footer-key-foreground': BLUE,
               'footer-description-foreground': FOREGROUND,
               'input-selection-background': SELECTION},
)


def event_color(payload):
    return BLUE if 'event' in payload else AMBER if payload.get('type') == 'vibration' else PURPLE if payload.get('type') == 'lidar' else CYAN
