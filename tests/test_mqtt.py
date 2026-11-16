"""Offline regression checks for the real MQTT publish path."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from liminal_desk_cli.transports.mqtt import Broker

class MqttTests(unittest.TestCase):
    def test_publish_serializes_payload_and_returns_confirmation(self):
        broker = Broker(SimpleNamespace(dry_run=False, qos=1))
        broker.connected = True
        info = SimpleNamespace(rc=0)
        broker.client = Mock()
        broker.client.publish.return_value = info
        payload = {"device_id": "mm-1", "event": "pick", "timestamp_ms": 1000}
        self.assertIs(broker.send("liminal/machine_data", payload), info)
        args, kwargs = broker.client.publish.call_args
        self.assertEqual(args[0], "liminal/machine_data")
        self.assertEqual(json.loads(args[1]), payload)
        self.assertEqual(kwargs, {"qos": 1, "retain": False})
