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

class TestBatchView(ReplayCase):
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
