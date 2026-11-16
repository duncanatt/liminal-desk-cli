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

class TestSchedule(ReplayCase):
    def test_real_files_and_machine_first_ties(self):
        self.assertEqual(self.schedule.totals, [36, 2644])
        self.assertEqual(self.schedule.duration, 66000)
        grouped = {}
        for e in self.schedule.events:
            grouped.setdefault(e.at, []).append(e.stream)
        for streams in grouped.values():
            self.assertEqual(streams, sorted(streams))
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
