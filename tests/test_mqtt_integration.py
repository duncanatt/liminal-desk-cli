"""Opt-in loopback MQTT tests. Never contacts an external/configured broker.

LIMINAL_TEST_MQTT=1 python -m unittest tests.test_mqtt_integration -v
Requires the project's Paho dependency and permission to bind a loopback socket.
The test server implements just the MQTT 3.1.1 packets used by this application.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
from types import SimpleNamespace
import unittest

from liminal_desk_cli.replay.engine import Replay
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.transports.mqtt import Broker

ROOT = Path(__file__).resolve().parent.parent
TOPICS = ['liminal/machine_data', 'liminal/sensor_data']


def packet(header, body):
    length = len(body)
    encoded = bytearray()
    while True:
        digit, length = length % 128, length // 128
        encoded.append(digit | (128 if length else 0))
        if not length:
            return bytes([header])+encoded+body


class LoopbackMqtt:
    def __init__(self, reject_subscriptions=False):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.messages = []
        self.errors = []
        self.clients = []
        self.stop = threading.Event()
        self.reject_subscriptions = reject_subscriptions
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            while not self.stop.is_set():
                try:
                    conn, _ = self.listener.accept()
                except socket.timeout:
                    continue
                self.clients.append(conn)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.settimeout(.1)
                try:
                    self.session(conn)
                except (EOFError, ConnectionError, OSError):
                    pass
                finally:
                    conn.close()
        except Exception as exc:
            self.errors.append(repr(exc))

    def session(self, conn):
        def read(n):
            data = b''
            while len(data) < n:
                if self.stop.is_set():
                    raise EOFError
                try:
                    more = conn.recv(n-len(data))
                except socket.timeout:
                    continue
                if not more:
                    raise EOFError
                data += more
            return data
        while not self.stop.is_set():
            header = read(1)[0]
            size, multiplier = 0, 1
            for _ in range(4):
                digit = read(1)[0]
                size += (digit & 127)*multiplier
                multiplier *= 128
                if digit < 128:
                    break
            body = read(size)
            kind = header >> 4
            if kind == 1:  # CONNECT / successful CONNACK
                conn.sendall(b'\x20\x02\x00\x00')
            elif kind == 8:  # SUBSCRIBE / SUBACK, preserving request id
                pos, codes = 2, []
                while pos < len(body):
                    length = int.from_bytes(body[pos:pos+2], 'big')
                    pos += 2+length
                    codes.append(128 if self.reject_subscriptions else body[pos])
                    pos += 1
                conn.sendall(packet(0x90, body[:2]+bytes(codes)))
            elif kind == 3:  # PUBLISH: record payload, ACK and echo to subscriber
                length = int.from_bytes(body[:2], 'big')
                topic = body[2:2+length]
                pos, ack = 2+length, b''
                if (header >> 1) & 3:
                    ack = packet(0x40, body[pos:pos+2])
                    pos += 2
                payload = body[pos:]
                self.messages.append((topic.decode(), json.loads(payload), time.monotonic()))
                conn.sendall(ack+packet(0x30, len(topic).to_bytes(2, 'big')+topic+payload))
            elif kind == 12:
                conn.sendall(b'\xd0\x00')
            elif kind == 14:
                return
            else:
                raise AssertionError(f'Unexpected MQTT packet: {kind}')

    def drop_connection(self):
        for conn in self.clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self.stop.set()
        self.drop_connection()
        self.thread.join(2)
        self.listener.close()


@unittest.skipUnless(os.environ.get('LIMINAL_TEST_MQTT') == '1', 'opt-in isolated loopback MQTT tests')
class MqttIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = LoopbackMqtt()
        self.addCleanup(self.server.close)
        self.args = SimpleNamespace(host='127.0.0.1', port=self.server.port, username=None,
                                    tls=False, ca_file=None, qos=1, dry_run=False, subscribe=TOPICS)
        self.broker = Broker(self.args)
        self.addCleanup(self.broker.close)
        self.paths = [ROOT/'examples/shop_floor'/name for name in ('machine_events.json', 'sensor_events.json')]
        self.hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths]
        self.schedule = Schedule(self.paths)

    def wait(self, condition, seconds=10):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self.broker.pump()
            if condition():
                return
            time.sleep(.001)
        self.fail(f'Timed out; broker={self.broker.state}; server errors={self.server.errors}')

    def connect(self):
        self.broker.connect()
        self.wait(lambda: self.broker.ready)

    def verify(self, replay):
        self.wait(lambda: sum(self.broker.received.values()) == 2680)
        self.assertEqual(replay.counts, [36, 2644])
        self.assertEqual(len(self.server.messages), 2680)
        for event, (topic, payload, _) in zip(self.schedule.events, self.server.messages):
            expected = dict(event.payload, timestamp_ms=replay.epoch+event.at)
            self.assertEqual((topic, payload), (TOPICS[event.stream], expected))
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths], self.hashes)
        self.assertFalse(self.server.errors)

    def run_step_trace(self):
        self.connect()
        replay = Replay(self.schedule, self.broker, TOPICS)
        replay.start('step')
        deadline = time.monotonic()+30
        while replay.state != 'Completed' and time.monotonic() < deadline:
            if replay.state == 'Step ready':
                replay.next()
            self.broker.pump()
            replay.tick()
            time.sleep(.0002)
        self.assertEqual(replay.state, 'Completed')
        self.verify(replay)

    def test_full_step_replay_qos1(self):
        self.run_step_trace()

    def test_full_step_replay_qos0(self):
        self.args.qos = 0
        self.run_step_trace()

    def test_full_real_time_automatic_replay(self):
        self.connect()
        replay = Replay(self.schedule, self.broker, TOPICS)
        started = time.monotonic()
        replay.start('auto')
        while replay.state != 'Completed' and time.monotonic()-started < 80:
            self.broker.pump()
            replay.tick()
            time.sleep(.001)
        elapsed = time.monotonic()-started
        self.assertEqual(replay.state, 'Completed')
        self.assertGreaterEqual(elapsed, 66)
        self.assertLess(elapsed, 75)
        self.verify(replay)
        print(f'\nReal MQTT automatic replay: {elapsed:.3f}s; max scheduler lag {replay.max_late:.1f}ms', flush=True)

    def test_disconnect_stops_replay_and_reconnect_allows_fresh_run(self):
        self.connect()
        replay = Replay(self.schedule, self.broker, TOPICS)
        replay.start('step')
        self.server.drop_connection()
        self.wait(lambda: not self.broker.connected)
        with self.assertRaisesRegex(RuntimeError, 'Connection lost'):
            replay.tick()
        self.broker.close()
        self.connect()
        fresh = Replay(self.schedule, self.broker, TOPICS)
        fresh.start('step')
        fresh.next()
        def advance():
            fresh.tick()
            return fresh.state == 'Step ready'
        self.wait(advance)
        self.assertEqual(fresh.counts, [2, 4])

    def test_rejected_subscription_blocks_replay(self):
        self.server.reject_subscriptions = True
        self.broker.connect()
        self.wait(lambda: 'rejected' in self.broker.state)
        self.assertFalse(self.broker.ready)
        with self.assertRaisesRegex(RuntimeError, 'subscription confirmation'):
            Replay(self.schedule, self.broker, TOPICS).start('step')


if __name__ == '__main__':
    unittest.main()
