"""Merge trace timelines and select deterministic manual replay boundaries."""
from .trace import load_trace

STEP_MODES = ('driver', 'timestamp', 'message')

class Schedule:
    def __init__(self, paths):
        loaded = [load_trace(path, i) for i, path in enumerate(paths)]
        if not loaded:
            raise ValueError('At least one trace is required')
        if len({item[2] for item in loaded}) != 1:
            raise ValueError('The traces must share the same timestamp origin')
        self.events = sorted((e for item in loaded for e in item[0]),
                             key=lambda e: (e.at, e.stream, e.order))
        self.duration = max(x[1] for x in loaded)
        self.totals = [len(x[0]) for x in loaded]
        self.machine_times = sorted({e.at for e in loaded[0][0]})

    def preview(self, index, driver=0, mode='driver'):
        if mode not in STEP_MODES:
            raise ValueError('Unknown step mode')
        if not 0 <= driver < len(self.totals):
            raise ValueError('Invalid driver stream')
        remaining = self.events[index:]
        if not remaining:
            return self.duration, []
        if mode == 'message':
            return remaining[0].at, remaining[:1]
        target = remaining[0].at if mode == 'timestamp' else next(
            (e.at for e in remaining if e.stream == driver), self.duration)
        return target, [e for e in remaining if e.at <= target]
