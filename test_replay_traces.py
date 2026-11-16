"""Offline checks: python3 -m unittest -v test_replay_traces.py"""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from replay_traces import Schedule, Replay, load_trace, scroll_offset


class Clock:
    now = 0
    def __call__(self):
        return self.now


class Publisher:
    ready = connected = True
    args = SimpleNamespace(dry_run=True)
    def __init__(self):
        self.sent = []
    def send(self, topic, payload):
        self.sent.append((topic, payload))


class ReplayTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent
        self.schedule = Schedule([root/'machine_events.json', root/'sensor_events.json'])
        self.publisher = Publisher()
        self.clock = Clock()
        self.replay = Replay(self.schedule, self.publisher, ['machine', 'sensor'], self.clock)

    def drain(self, count=10000):
        for _ in range(count):
            old = self.replay.index
            self.replay.tick()
            if self.replay.state in ('Step ready', 'Completed'):
                break
            if old == self.replay.index and self.replay.pending is None:
                break

    def test_real_files_and_machine_first_ties(self):
        self.assertEqual(self.schedule.totals, [36, 2644])
        self.assertEqual(self.schedule.duration, 66000)
        grouped = {}
        for e in self.schedule.events:
            grouped.setdefault(e.at, []).append(e.stream)
        for streams in grouped.values():
            self.assertEqual(streams, sorted(streams))

    def test_all_step_batches_timestamps_and_unchanged_sources(self):
        source = copy.deepcopy([e.payload for e in self.schedule.events])
        with patch('replay_traces.time.time_ns', return_value=1900000000000000000):
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

    def test_step_display_tracks_confirmed_payloads_and_previous_batch(self):
        self.replay.start('step')
        self.replay.next()
        first = self.replay.batch
        self.assertIn('Sending step 1', first.heading())
        self.assertEqual(first.sent, [])
        self.drain()
        self.assertTrue(first.complete)
        self.assertEqual(len(first.sent), 6)
        self.assertIn('2 machine + 4 sensor', first.heading())
        self.assertIn('Last step sent 1', first.heading())
        self.replay.next()
        self.assertIs(self.replay.previous_batch, first)
        second = self.replay.batch
        self.assertEqual((second.start, second.end), (0, 1000))
        self.drain()
        self.assertEqual(len(second.sent), 42)
        self.assertEqual(len(first.sent), 6)
        self.assertIn('lidar: 10 [0.100-1.000]', '\n'.join(second.summary()))
        for event, payload in second.sent:
            self.assertEqual(payload['timestamp_ms'], self.replay.epoch+event.at)
        details = '\n'.join(second.details(['machine', 'sensor'], 100))
        self.assertIn('timestamp_ms', details)
        self.assertIn('machine', details)
        self.assertEqual(len(second.sent_times), 42)

    def test_numbered_colored_payload_rows_and_full_scroll_range(self):
        self.replay.start('step')
        for _ in range(2):
            self.replay.next()
            self.drain()
        batch = self.replay.batch
        rows = batch.detail_rows(['machine', 'sensor'], 70)
        starts = [(line, color, n) for line, color, n in rows if line[:1].isdigit()]
        self.assertEqual([n for _,_,n in starts], list(range(1,43)))
        self.assertTrue(starts[0][0].startswith('01: '))
        self.assertTrue(starts[-1][0].startswith('42: '))
        for (event,payload),(_,color,n) in zip(batch.sent,starts):
            self.assertEqual(color,4 if event.stream==0 else 5 if payload['type']=='vibration' else 6)
        end = scroll_offset(0, 'end', 17, len(rows))
        self.assertEqual(rows[end:][-1][2], 42)
        self.assertEqual(scroll_offset(end, 'home', 17, len(rows)), 0)
        self.assertEqual(scroll_offset(end, 'down', 17, len(rows)), end)
        self.assertEqual(scroll_offset(0, 'up', 17, len(rows)), 0)
        self.assertLessEqual(max(len(line) for line,_,_ in rows),70)
        # Wrapping changes row count, not event identity or numbering.
        self.assertEqual({n for _,_,n in batch.detail_rows(['machine','sensor'],35)},set(range(1,43)))

    def test_step_display_waits_for_ack(self):
        ack = SimpleNamespace(is_published=lambda: False)
        self.publisher.send = lambda topic, payload: ack
        self.replay.start('step')
        self.replay.next()
        self.replay.tick()
        self.assertEqual(self.replay.batch.sent, [])
        self.assertFalse(self.replay.batch.complete)
        ack.is_published = lambda: True
        self.replay.tick()
        self.assertEqual(len(self.replay.batch.sent), 1)

    def test_auto_completes_at_66_and_no_accumulated_clock_drift(self):
        self.replay.start('auto')
        self.drain()
        for i in range(1, 661):
            self.clock.now = i/10 + .0001
            self.drain()
        self.assertEqual(self.replay.state, 'Completed')
        self.assertEqual(self.replay.counts, [36, 2644])

    def test_pause_inside_step_batch_and_fresh_retry_origin(self):
        with patch('replay_traces.time.time_ns', return_value=1900000000000000000):
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
        with patch('replay_traces.time.time_ns', return_value=1900000010000000000):
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

    def test_validation_and_sensor_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory)/'machine.json', Path(directory)/'sensor.json']
            for i, path in enumerate(paths):
                path.write_text(json.dumps({'version':1, 'steps':[
                    {'type':'send','payload':{'timestamp_ms':1000}},
                    {'type':'delay','duration_ms':100*(i+1)},
                    {'type':'send','payload':{'timestamp_ms':1000+100*(i+1)}},
                    {'type':'delay','duration_ms':100}]}))
            self.schedule = Schedule(paths)
            self.replay = Replay(self.schedule, self.publisher, ['m', 's'], self.clock)
            self.replay.start('step')
            for target in (0,100,300):
                self.replay.next()
                self.drain()
                self.assertEqual(self.replay.position, target)
            self.assertEqual(self.replay.state, 'Completed')
            paths[0].write_text('{"version":1,"steps":[{"type":"delay","duration_ms":true}]}')
            with self.assertRaisesRegex(ValueError, 'invalid delay'):
                load_trace(paths[0], 0)
            paths[0].write_text('{"version":1,"version":1,"steps":[]}')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                load_trace(paths[0], 0)


if __name__ == '__main__':
    unittest.main()
