import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from tests.helpers import ReplayCase
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.replay.engine import Replay
from liminal_desk_cli.replay.trace import load_trace
from liminal_desk_cli.ui.widgets import scroll_offset

class TestEngine(ReplayCase):
    def test_all_step_batches_timestamps_and_unchanged_sources(self):
        source = copy.deepcopy([e.payload for e in self.schedule.events])
        with patch('liminal_desk_cli.replay.engine.time.time_ns', return_value=1900000000000000000):
            self.replay.start('step')
        bounds = []
        while self.replay.state != 'Completed':
            target, batch = self.schedule.preview(self.replay.index)
            before = len(self.publisher.sent)
            self.replay.next()
            self.drain()
            bounds.append(target)
            self.assertEqual(len(self.publisher.sent)-before, len(batch))
            self.assertEqual(self.replay.position, target)
        self.assertEqual(bounds, self.schedule.machine_times)
        self.assertEqual(self.replay.counts, [36, 2644])
        for (_, payload), event in zip(self.publisher.sent, self.schedule.events):
            self.assertEqual(payload['timestamp_ms'], 1900000000000+event.at)
            self.assertEqual({k:v for k,v in payload.items() if k!='timestamp_ms'},
                             {k:v for k,v in event.payload.items() if k!='timestamp_ms'})
        self.assertEqual(source, [e.payload for e in self.schedule.events])
    def test_pause_freezes_both_streams_and_remaining_delay(self):
        self.replay.start('auto')
        self.drain()
        self.assertEqual(self.replay.counts, [2, 4])
        self.clock.now = .05
        self.replay.pause()
        self.clock.now = 20
        self.drain()
        self.assertEqual(self.replay.elapsed(), 50)
        self.assertEqual(self.replay.counts, [2, 4])
        self.replay.pause()
        self.clock.now = 20.049
        self.drain()
        self.assertEqual(self.replay.counts, [2, 4])
        self.clock.now = 20.051
        self.drain()
        self.assertEqual(self.replay.counts, [2, 8])
    def test_auto_completes_at_66_and_no_accumulated_clock_drift(self):
        self.replay.start('auto')
        self.drain()
        for i in range(1, 661):
            self.clock.now = i/10 + .0001
            self.drain()
        self.assertEqual(self.replay.state, 'Completed')
        self.assertEqual(self.replay.counts, [36, 2644])
    def test_pause_inside_step_batch_and_fresh_retry_origin(self):
        with patch('liminal_desk_cli.replay.engine.time.time_ns', return_value=1900000000000000000):
            self.replay.start('step')
        self.replay.next()
        self.replay.tick()
        self.replay.pause()
        self.replay.tick()
        self.assertEqual(self.replay.counts, [1, 0])
        self.replay.tick()
        self.assertEqual(self.replay.counts, [1, 0])
        self.replay.pause()
        self.drain()
        self.assertEqual(self.replay.counts, [2, 4])
        first_origin = self.replay.epoch
        self.replay = Replay(self.schedule, self.publisher, ['machine', 'sensor'], self.clock)
        with patch('liminal_desk_cli.replay.engine.time.time_ns', return_value=1900000010000000000):
            self.replay.start('step')
        self.assertEqual(self.replay.counts, [0, 0])
        self.assertEqual(self.replay.index, 0)
        self.assertEqual(self.replay.epoch-first_origin, 10000)
    def test_inflight_ack_pause_and_connection_failure(self):
        ack = SimpleNamespace(is_published=lambda: False)
        self.publisher.send = lambda topic, payload: ack
        self.replay.start('auto')
        self.replay.tick()
        self.replay.pause()
        self.replay.tick()
        self.assertEqual(self.replay.counts, [0, 0])
        ack.is_published = lambda: True
        self.replay.tick()
        self.assertEqual(self.replay.counts, [1, 0])
        self.assertEqual(self.replay.state, 'Paused')
        self.publisher.connected = False
        with self.assertRaisesRegex(RuntimeError, 'Connection lost'):
            self.replay.tick()
