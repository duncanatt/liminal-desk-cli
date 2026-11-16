"""Merge the two trace timelines and select machine-driven slices."""
from .trace import load_trace

class Schedule:
    def __init__(self, paths):
        loaded = [load_trace(path, i) for i, path in enumerate(paths)]
        if loaded[0][2] != loaded[1][2]:
            raise ValueError('The two traces must share the same timestamp origin')
        self.events = sorted(loaded[0][0] + loaded[1][0],
                             key=lambda e: (e.at, e.stream, e.order))
        self.duration = max(x[1] for x in loaded)
        self.totals = [len(x[0]) for x in loaded]
        self.machine_times = sorted({e.at for e in loaded[0][0]})

    def preview(self, index):
        target = next((e.at for e in self.events[index:] if e.stream == 0), None)
        if target is None:
            target = self.duration
        batch = [e for e in self.events[index:] if e.at <= target]
        return target, batch
