"""Offline configuration, routing, and transport-neutral completion checks."""
import contextlib
import io
from unittest.mock import patch, Mock
import unittest
from liminal_desk_cli.config import parse_args, StreamConnection
from liminal_desk_cli.transports.base import send_complete, MqttReceipt
from liminal_desk_cli.transports.manager import TransportManager
from liminal_desk_cli.ui.screens import connection_settings


class ConnectionTests(unittest.TestCase):
    def test_mqtt_defaults_remain_one_connection(self):
        _, args = parse_args([])
        manager = TransportManager(args)
        self.assertEqual(len(manager.adapters), 1)
        self.assertEqual(args.topics, ['liminal/machine_data', 'liminal/sensor_data'])
        self.assertEqual(args.subscribe, args.topics)
        self.assertEqual([s.port for s in args.streams], [1883,1883])

    def test_tcp_defaults_separate_and_explicit_port_shared(self):
        _, args = parse_args(['--transport','tcp','--dry-run'])
        self.assertEqual([s.port for s in args.streams], [8080,8081])
        manager = TransportManager(args)
        self.assertEqual(len(manager.adapters), 2)
        manager.connect()
        self.assertTrue(manager.ready)
        self.assertIn('local TCP write', TransportManager(parse_args(['--transport','tcp'])[1]).send_status(args.topics[0]))
        self.assertIsNone(manager.send(args.topics[0], {'x':1}))
        manager.close()
        self.assertFalse(manager.ready)
        _, args = parse_args(['--transport','tcp','--port','9000'])
        self.assertEqual(len(TransportManager(args).adapters), 1)
        self.assertNotEqual(*args.topics)

    def test_mixed_transport_and_per_stream_endpoints(self):
        _, args = parse_args(['--sensor-transport','tcp','--sensor-host','sensor.local','--sensor-port','9002'])
        self.assertEqual([(s.transport,s.host,s.port) for s in args.streams],
                         [('mqtt','localhost',1883),('tcp','sensor.local',9002)])
        self.assertEqual(args.subscribe, ['liminal/machine_data'])
        self.assertEqual(len(TransportManager(args).adapters), 2)

    def test_invalid_tcp_options_and_mqtt_compatibility(self):
        for argv in (['--transport','tcp','--tls'], ['--transport','tcp','--subscribe','x'],
                     ['--sensor-port','0'], ['--max-frame-bytes','0'],
                     ['--max-frame-bytes','4294967296'],
                     ['--machine-topic','same','--sensor-topic','same']):
            with self.subTest(argv=argv),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                parse_args(argv)
        _, args = parse_args(['--tls'])
        self.assertEqual([s.port for s in args.streams],[8883,8883])

    def test_mqtt_receipt_wrapper_and_legacy_receipts(self):
        info=Mock(spec=['is_published'])
        info.is_published.return_value=False
        self.assertFalse(send_complete(MqttReceipt(info)))
        self.assertFalse(send_complete(info))
        info.is_published.return_value=True
        self.assertTrue(send_complete(MqttReceipt(info)))
        self.assertTrue(send_complete(None))

    def test_connection_menu_edits_transactionally(self):
        _, args = parse_args([])
        replies=['tcp','localhost','9001','tcp','localhost','9002']
        with patch('liminal_desk_cli.ui.screens.prompt', side_effect=replies):
            updated=connection_settings(None,args)
        self.assertEqual([s.port for s in updated.streams],[9001,9002])
        self.assertEqual([s.port for s in args.streams],[1883,1883])
        self.assertEqual(updated.subscribe,[])
        with patch('liminal_desk_cli.ui.screens.prompt',side_effect=['tcp','localhost','0','tcp','localhost','9002']),self.assertRaises(ValueError):
            connection_settings(None,args)
        self.assertEqual([s.transport for s in args.streams],['mqtt','mqtt'])

    def test_partial_connect_failure_closes_all_adapters(self):
        _, args=parse_args(['--sensor-transport','tcp'])
        manager=TransportManager(args)
        adapters=[Mock(),Mock()]
        manager.adapters=[(('mqtt','a',1),adapters[0]),(('tcp','b',2),adapters[1])]
        adapters[1].connect.side_effect=RuntimeError('refused')
        with self.assertRaisesRegex(RuntimeError,'refused'):
            manager.connect()
        self.assertEqual(adapters[0].close.call_count,2)
        self.assertEqual(adapters[1].close.call_count,2)
