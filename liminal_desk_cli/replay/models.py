"""Replay events and sent-batch records, including their text representations."""
import json
import textwrap
from collections import Counter
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Event:
    at: int
    stream: int
    order: int
    payload: dict


@dataclass
class StepBatch:
    number: int
    start: int
    end: int
    events: list
    sent: list = field(default_factory=list)
    complete: bool = False
    sent_times: list = field(default_factory=list)

    def heading(self):
        counts = Counter(e.stream for e in self.events)
        status = 'Last step sent' if self.complete else 'Sending step'
        return (f'{status} {self.number} | t={self.start/1000:.3f} -> {self.end/1000:.3f}'
                f' | {counts[0]} machine + {counts[1]} sensor | {len(self.sent)}/{len(self.events)} sent')

    def summary(self):
        machines = [f'{e.payload.get("device_id", "?")} {e.payload.get("event", "?")}'
                    for e in self.events if e.stream == 0]
        lines = ['Machine: ' + (', '.join(machines) or 'none (sensor tail)')]
        groups = {}
        for e in self.events:
            if e.stream == 1:
                groups.setdefault(e.payload.get('device_id', '?'), {}).setdefault(
                    e.payload.get('type', '?'), []).append(e.at)
        for device, modalities in sorted(groups.items()):
            parts = [f'{kind}: {len(times)} [{min(times)/1000:.3f}-{max(times)/1000:.3f}]'
                     for kind, times in sorted(modalities.items())]
            lines.append(device + ' | ' + ' | '.join(parts))
        return lines

    def details(self, topics, width):
        return [line for line, color, number in self.detail_rows(topics, width)]

    def detail_rows(self, topics, width):
        rows = []
        digits = max(2, len(str(len(self.events))))
        for number, (event, payload) in enumerate(self.sent, 1):
            stamp = self.sent_times[number-1] if number <= len(self.sent_times) else '--:--:--'
            prefix = f'{number:0{digits}d}: '
            body = f'{stamp} {topics[event.stream]} ' + json.dumps(payload, ensure_ascii=True, separators=(',', ':'))
            color = 4 if event.stream == 0 else 5 if payload.get('type') == 'vibration' else 6
            wrapped = textwrap.wrap(body, max(8, width-len(prefix)), break_long_words=True,
                                    break_on_hyphens=False, replace_whitespace=False)
            for i, line in enumerate(wrapped):
                rows.append((prefix+line if i == 0 else ' '*len(prefix)+line, color, number))
        return rows or [('No confirmed sends in this step yet.', 0, 0)]
