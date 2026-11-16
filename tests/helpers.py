"""Offline clock and publisher shared by replay tests."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.replay.engine import Replay

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


class ReplayCase(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parent.parent / "examples" / "shop_floor"
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
