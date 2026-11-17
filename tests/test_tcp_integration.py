"""Opt in: LIMINAL_TEST_TCP=1 python -m unittest tests.test_tcp_integration -v.

Only ephemeral 127.0.0.1 endpoints are used. No existing broker/server is contacted.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time
import unittest

from liminal_desk_cli.config import parse_args
from liminal_desk_cli.replay.engine import Replay
from liminal_desk_cli.replay.schedule import Schedule
from liminal_desk_cli.transports.base import send_complete
from liminal_desk_cli.transports.manager import TransportManager
from liminal_desk_cli.transports.tcp import TcpClient, encode_frame
from tests.helpers import Clock
from tests.test_mqtt_integration import LoopbackMqtt

ROOT = Path(__file__).resolve().parent.parent


class FrameServer:
    def __init__(self, echo=True):
        self.listener=socket.socket()
        self.listener.bind(('127.0.0.1',0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.port=self.listener.getsockname()[1]
        self.echo=echo
        self.messages=[]
        self.errors=[]
        self.peer=None
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                peer,_=self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.peer=peer
            peer.settimeout(.1)
            peer.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            buffer=bytearray()
            try:
                while not self.stop.is_set():
                    try:
                        data=peer.recv(8192)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buffer.extend(data)
                    while len(buffer)>=4:
                        size=struct.unpack('!I',buffer[:4])[0]
                        if size>1048576:
                            raise ValueError('Test server frame limit exceeded')
                        if len(buffer)<size+4:
                            break
                        raw=bytes(buffer[:size+4]);del buffer[:size+4]
                        self.messages.append(json.loads(raw[4:]))
                        if self.echo:
                            peer.sendall(raw)
            except (OSError,ConnectionError):
                pass
            except Exception as exc:
                self.errors.append(str(exc))
            finally:
                peer.close()
                self.peer=None

    def send_raw(self, data):
        if self.peer is None:
            raise RuntimeError('Test peer is not connected')
        self.peer.sendall(data)

    def disconnect(self):
        if self.peer is not None:
            try:
                self.peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self):
        self.stop.set();self.disconnect();self.thread.join(2);self.listener.close()


@unittest.skipUnless(os.environ.get('LIMINAL_TEST_TCP')=='1','opt-in local TCP integration tests')
class TcpIntegrationTests(unittest.TestCase):
    def wait(self, condition, pump=lambda:None, seconds=10):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            pump()
            if condition():
                return
            time.sleep(.0005)
        self.fail('Timed out waiting for local TCP operation')

    def server(self, **kwargs):
        server=FrameServer(**kwargs);self.addCleanup(server.close);return server

    def client(self, server, **kwargs):
        client=TcpClient('127.0.0.1',server.port,**kwargs);self.addCleanup(client.close)
        client.connect();self.wait(lambda:server.peer is not None);return client

    def run_replay(self, args, servers, auto=False):
        manager=TransportManager(args);self.addCleanup(manager.close);manager.connect()
        self.wait(lambda:manager.ready,manager.pump)
        paths=[ROOT/'examples/shop_floor'/name for name in ('machine_events.json','sensor_events.json')]
        hashes=[hashlib.sha256(p.read_bytes()).digest() for p in paths]
        schedule=Schedule(paths);replay=Replay(schedule,manager,args.topics)
        replay.start('auto' if auto else 'step')
        start=time.monotonic();deadline=start+(80 if auto else 20)
        while replay.state!='Completed' and time.monotonic()<deadline:
            manager.pump()
            if not auto and replay.state=='Step ready':
                replay.next()
            replay.tick();time.sleep(.0005)
        self.assertEqual(replay.state,'Completed',manager.state)
        self.assertEqual(replay.counts,[36,2644])
        self.wait(lambda:sum(sum(a.received.values()) for _,a in manager.adapters)==2680,manager.pump)
        self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).digest() for p in paths])
        for i,server in enumerate(servers):
            expected=[dict(e.payload,timestamp_ms=replay.epoch+e.at) for e in schedule.events if len(servers)==1 or e.stream==i]
            actual=[m[1] for m in server.messages] if isinstance(server,LoopbackMqtt) else server.messages
            self.assertEqual(actual,expected)
            self.assertFalse(server.errors)
        return replay,manager,time.monotonic()-start

    def test_full_shared_tcp_replay(self):
        server=self.server()
        _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--port',str(server.port)])
        replay,manager,_=self.run_replay(args,[server])
        self.assertEqual(len(manager.adapters),1)
        self.assertEqual(len(replay.batch.sent),1+40)  # (65,66]: ten samples per sensor/MM

    def test_full_separate_tcp_endpoints(self):
        machine=self.server();sensor=self.server()
        _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--machine-port',str(machine.port),'--sensor-port',str(sensor.port)])
        self.run_replay(args,[machine,sensor])

    def test_mixed_mqtt_tcp_replay(self):
        mqtt=LoopbackMqtt();self.addCleanup(mqtt.close);tcp=self.server()
        _,args=parse_args(['--host','127.0.0.1','--machine-port',str(mqtt.port),'--sensor-transport','tcp','--sensor-port',str(tcp.port)])
        self.run_replay(args,[mqtt,tcp])

    def test_full_mqtt_manager_replay(self):
        mqtt=LoopbackMqtt();self.addCleanup(mqtt.close)
        _,args=parse_args(['--host','127.0.0.1','--port',str(mqtt.port)])
        self.run_replay(args,[mqtt])

    def test_any_tcp_endpoint_loss_stops_the_shared_replay(self):
        first=self.server();second=self.server()
        _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--machine-port',str(first.port),'--sensor-port',str(second.port)])
        manager=TransportManager(args);self.addCleanup(manager.close);manager.connect()
        self.wait(lambda:first.peer is not None and second.peer is not None)
        schedule=Schedule([ROOT/'examples/shop_floor'/n for n in ('machine_events.json','sensor_events.json')])
        replay=Replay(schedule,manager,args.topics);replay.start('step')
        second.disconnect();self.wait(lambda:not manager.connected,manager.pump)
        self.assertFalse(manager.ready)
        with self.assertRaisesRegex(RuntimeError,'Connection lost'):
            replay.tick()
        self.assertEqual(first.messages,[])

    def test_full_real_time_automatic_tcp_replay(self):
        server=self.server()
        _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--port',str(server.port)])
        replay,_,elapsed=self.run_replay(args,[server],auto=True)
        self.assertGreaterEqual(elapsed,66)
        self.assertLess(elapsed,75)
        print(f'\nTCP automatic replay {elapsed:.3f}s; max lag {replay.max_late:.1f}ms',flush=True)

    def test_fragmented_and_coalesced_inbound_frames(self):
        server=self.server(echo=False);client=self.client(server)
        combined=encode_frame({'first':'µ'})+encode_frame({'second':2})
        for chunk in (combined[:1],combined[1:3],combined[3:11],combined[11:]):
            server.send_raw(chunk);time.sleep(.005)
        self.wait(lambda:sum(client.received.values())==2,client.pump)
        self.assertEqual([json.loads(row[2]) for row in client.log],[{'first':'µ'},{'second':2}])

    def test_large_outbound_frame_and_local_write_receipt(self):
        server=self.server(echo=False);client=self.client(server)
        payload={'large':'x'*250000}
        receipt=client.send('',payload)
        self.wait(lambda:send_complete(receipt))
        self.wait(lambda:len(server.messages)==1)
        self.assertEqual(server.messages[0],payload)

    def test_oversized_inbound_frame_disconnects_without_waiting_for_body(self):
        server=self.server(echo=False);client=self.client(server,max_frame_bytes=64)
        server.send_raw(struct.pack('!I',65))
        self.wait(lambda:not client.connected)
        self.assertIn('exceeds limit',client.state)
        with self.assertRaisesRegex(RuntimeError,'connection lost'):
            client.send('',{})

    def test_disconnect_reconnect_and_incomplete_frame_reset(self):
        server=self.server(echo=False);client=self.client(server)
        server.send_raw(b'\x00\x00');server.disconnect()
        self.wait(lambda:not client.connected)
        self.wait(lambda:server.peer is None)
        client.connect();self.wait(lambda:server.peer is not None)
        server.send_raw(encode_frame({'fresh':True}))
        self.wait(lambda:sum(client.received.values())==1,client.pump)
        self.assertEqual(json.loads(client.log[0][2]),{'fresh':True})
        client.close();self.assertIsNone(client._thread)

    def test_refused_endpoint_and_no_automatic_reconnect(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0))
            client=TcpClient('127.0.0.1',reserved.getsockname()[1]);self.addCleanup(client.close)
            with self.assertRaisesRegex(RuntimeError,'Connection failed'):
                client.connect()
            self.assertFalse(client.ready)

    def test_pause_and_resume_keeps_step_clock_and_batches(self):
        server=self.server()
        _,args=parse_args(['--transport','tcp','--host','127.0.0.1','--port',str(server.port)])
        manager=TransportManager(args);self.addCleanup(manager.close);manager.connect()
        schedule=Schedule([ROOT/'examples/shop_floor'/n for n in ('machine_events.json','sensor_events.json')])
        clock=Clock();replay=Replay(schedule,manager,args.topics,clock)
        replay.start('auto')
        self.wait(lambda:replay.counts==[2,4],lambda:(manager.pump(),replay.tick()))
        clock.now=.05;replay.pause();before=len(server.messages)
        clock.now=10
        for _ in range(10):manager.pump();replay.tick();time.sleep(.002)
        self.assertEqual(len(server.messages),before)
        self.assertEqual(replay.elapsed(),50)
        replay.pause();clock.now=10.06
        self.wait(lambda:replay.counts==[2,8],lambda:(manager.pump(),replay.tick()))


if __name__=='__main__':
    unittest.main()
