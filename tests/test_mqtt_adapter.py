"""Exercise MQTT callbacks and error paths without a live broker."""
import os
import queue
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from liminal_desk_cli.transports.mqtt import Broker


class MqttAdapterTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(host='localhost',port=1883,username=None,
                                    tls=False,ca_file=None,qos=1,dry_run=False,
                                    subscribe=['liminal/#'])
        self.broker = Broker(self.args)

    def test_disconnected_dry_run_and_publish_error(self):
        with self.assertRaisesRegex(RuntimeError, 'connection lost'):
            self.broker.send('topic', {})
        self.args.dry_run = True
        self.broker.connect()
        self.assertTrue(self.broker.ready)
        self.assertIsNone(self.broker.send('topic', {}))
        self.broker.close()
        self.assertFalse(self.broker.ready)
        self.args.dry_run = False
        self.broker.connected = True
        self.broker.client = Mock()
        self.broker.client.publish.return_value = SimpleNamespace(rc=4)
        with self.assertRaisesRegex(RuntimeError, 'publish failed'):
            self.broker.send('topic', {})

    def test_nonfinite_payload_fails_before_publish(self):
        self.broker.connected = True
        self.broker.client = Mock()
        with self.assertRaises(ValueError):
            self.broker.send('topic', {'value':float('nan')})
        self.broker.client.publish.assert_not_called()

    def test_subscription_receipts_queue_and_readiness(self):
        self.broker.connected = True
        self.assertFalse(self.broker.ready)
        self.broker.notify('subscribed', ['liminal/#'])
        self.broker.notify('message', ('liminal/machine_data', '{"event":"pick"}', True))
        self.broker.pump()
        self.assertTrue(self.broker.ready)
        self.assertEqual(self.broker.received['liminal/machine_data'], 1)
        self.assertTrue(self.broker.log[-1][-1])
        self.broker.notifications = queue.Queue(maxsize=1)
        self.broker.notify('state', 'one')
        self.broker.notify('state', 'two')
        self.assertEqual(self.broker.dropped, 1)

    def test_connection_callbacks_auth_tls_and_cleanup(self):
        self.args.username='alice'
        self.args.tls=True
        self.args.ca_file='/example/ca.pem'
        client=Mock()
        client.subscribe.return_value=(0, 1)
        paho=ModuleType('paho');mqtt_pkg=ModuleType('paho.mqtt');mqtt=ModuleType('paho.mqtt.client')
        paho.mqtt=mqtt_pkg;mqtt_pkg.client=mqtt
        mqtt.Client=Mock(return_value=client)
        mqtt.CallbackAPIVersion=SimpleNamespace(VERSION2=2)
        mqtt.MQTT_ERR_SUCCESS=0
        with patch.dict(sys.modules,{'paho':paho,'paho.mqtt':mqtt_pkg,'paho.mqtt.client':mqtt}),patch.dict(os.environ,{'MQTT_PASSWORD':'secret'}):
            self.broker.connect()
        client.username_pw_set.assert_called_once_with('alice','secret')
        client.tls_set.assert_called_once_with(ca_certs='/example/ca.pem')
        client.connect.assert_called_once_with('localhost',1883,keepalive=30)
        client.loop_start.assert_called_once()
        ok=SimpleNamespace(is_failure=False)
        client.on_connect(client,None,None,ok,None)
        self.broker.pump()
        self.assertFalse(self.broker.ready)
        client.subscribe.assert_called_once_with([('liminal/#',1)])
        client.on_subscribe(client,None,1,[ok],None)
        client.on_message(client,None,SimpleNamespace(topic='liminal/test',payload=b'hello',retain=False))
        self.broker.pump()
        self.assertTrue(self.broker.ready)
        self.assertEqual(self.broker.log[-1][2],'hello')
        client.on_disconnect(client,None,None,'test loss',None)
        self.broker.pump()
        self.assertFalse(self.broker.connected)
        self.assertIn('Disconnected',self.broker.state)
        self.broker.close()
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_rejected_callback_does_not_enable_replay(self):
        client=Mock()
        paho=ModuleType('paho');mqtt_pkg=ModuleType('paho.mqtt');mqtt=ModuleType('paho.mqtt.client')
        paho.mqtt=mqtt_pkg;mqtt_pkg.client=mqtt
        mqtt.Client=Mock(return_value=client);mqtt.CallbackAPIVersion=SimpleNamespace(VERSION2=2)
        with patch.dict(sys.modules,{'paho':paho,'paho.mqtt':mqtt_pkg,'paho.mqtt.client':mqtt}):
            self.broker.connect()
        client.on_connect(client,None,None,SimpleNamespace(is_failure=True),None)
        self.broker.pump()
        self.assertFalse(self.broker.ready)
        self.assertIn('rejected',self.broker.state)
