"""Replay scheduling and state, independent of terminal and MQTT libraries."""
import copy
import time
from .models import StepBatch

class Replay:
    """One timeline; one in-flight send. MQTT work stays on its network thread."""
    def __init__(self, schedule, broker, topics, clock=time.monotonic):
        self.schedule, self.broker, self.topics, self.clock = schedule, broker, topics, clock
        self.index = 0
        self.counts = [0, 0]
        self.state = 'Ready'
        self.mode = 'auto'
        self.epoch = None
        self.position = 0.0
        self.anchor = clock()
        self.target = None
        self.inflight = None
        self.pending = None
        self.pending_since = 0
        self.pending_wall = None
        self.last = ['No messages sent', 'No messages sent']
        self.max_late = 0.0
        self.error = ''
        self.paused_from = None
        self.batch = None
        self.previous_batch = None

    def elapsed(self):
        if self.mode == 'auto' and self.state == 'Running':
            return min(self.schedule.duration, self.position + (self.clock()-self.anchor)*1000)
        return self.position

    def start(self, mode):
        if not self.broker.ready:
            raise RuntimeError('Connect and wait for subscription confirmation first (C)')
        if self.epoch is not None:
            raise RuntimeError('Use R to retry before starting a fresh run')
        self.epoch = time.time_ns() // 1_000_000
        self.mode = mode
        self.anchor = self.clock()
        self.state = 'Running' if mode == 'auto' else 'Step ready'

    def pause(self):
        if self.state in ('Running', 'Stepping'):
            self.position = self.elapsed()
            self.paused_from = self.state
            self.state = 'Paused'
        elif self.state == 'Paused':
            self.anchor = self.clock()
            self.state = self.paused_from or 'Running'

    def next(self):
        if self.mode != 'step' or self.state != 'Step ready':
            return
        self.target, events = self.schedule.preview(self.index)
        self.previous_batch = self.batch
        self.batch = StepBatch(1 if self.batch is None else self.batch.number+1,
                               int(self.position), self.target, events)
        self.state = 'Stepping'

    def tick(self):
        if self.epoch is None or self.state in ('Completed', 'Error'):
            return
        if not self.broker.connected:
            raise RuntimeError('Connection lost. Partial replay stopped; R starts a new experiment.')
        # Complete the pending send even when paused, but never start another.
        if self.pending is not None:
            if self.inflight is not None and not self.inflight.is_published():
                if self.clock()-self.pending_since > 10:
                    raise RuntimeError('Publish confirmation timed out; delivery is uncertain. Retry as a new run.')
                return
            event = self.pending
            self.counts[event.stream] += 1
            if self.mode == 'step' and self.batch is not None:
                payload = copy.deepcopy(event.payload)
                payload['timestamp_ms'] = self.epoch + event.at
                self.batch.sent.append((event, payload))
                self.batch.sent_times.append(self.pending_wall)
            name = event.payload.get('event', event.payload.get('type', 'event'))
            self.last[event.stream] = f'{event.payload.get("device_id", "?")} {name} at t={event.at/1000:.3f}'
            self.index += 1
            self.pending = self.inflight = None
        if self.state not in ('Running', 'Stepping'):
            return
        limit = self.elapsed() if self.mode == 'auto' else self.target
        if self.index < len(self.schedule.events):
            event = self.schedule.events[self.index]
            if event.at <= limit:
                payload = copy.deepcopy(event.payload)
                payload['timestamp_ms'] = self.epoch + event.at
                if self.mode == 'step':
                    self.position = event.at
                else:
                    self.max_late = max(self.max_late, limit-event.at)
                self.pending_since = self.clock()
                self.pending_wall = time.strftime('%H:%M:%S')
                self.inflight = self.broker.send(self.topics[event.stream], payload)
                self.pending = event
                return
        if self.mode == 'step':
            self.position = self.target
            self.state = 'Step ready'
            self.batch.complete = True
        # Honor trailing delays even after the last send.
        if self.index == len(self.schedule.events) and (self.mode == 'step' or limit >= self.schedule.duration):
            self.position = self.schedule.duration
            self.state = 'Completed'

    def status(self, stream):
        if self.pending is not None and self.pending.stream == stream:
            return 'Sending: awaiting broker ACK' if not self.broker.args.dry_run else 'Sending (simulated)'
        upcoming = next((e for e in self.schedule.events[self.index:] if e.stream == stream), None)
        if upcoming is None:
            return 'All messages sent'
        if self.state == 'Error':
            return 'Stopped after error'
        if self.state == 'Step ready':
            return f'Waiting for N; next t={upcoming.at/1000:.3f}'
        delay = max(0, upcoming.at-self.elapsed())/1000
        label = 'Paused' if self.state == 'Paused' else 'Waiting'
        return f'{label}: delay remaining {delay:.3f}s (next t={upcoming.at/1000:.3f})'
