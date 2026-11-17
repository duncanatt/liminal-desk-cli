"""MQTT publication and subscription adapter."""
import json
import os
import queue
import time
from collections import Counter, deque

class Broker:
    def __init__(self, args):
        self.args = args
        self.client = None
        self.connected = False
        self.state = 'Disconnected'
        self.subscribed = set()
        self.received = Counter()
        self.log = deque(maxlen=300)
        self.notifications = queue.Queue(maxsize=2000)
        self.dropped = 0

    def notify(self, kind, value):
        try:
            self.notifications.put_nowait((kind, value))
        except queue.Full:
            self.dropped += 1

    def connect(self):
        self.close()
        self.subscribed.clear()
        self.received.clear()
        # close() joins the old network loop: discard any queued callbacks from
        # that session before using subscription readiness for a new connection.
        self.notifications = queue.Queue(maxsize=2000)
        self.log.clear()
        self.dropped = 0
        if self.args.dry_run:
            self.connected = True
            self.state = 'Dry run: no network connection'
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError('Install paho-mqtt: python3 -m pip install "paho-mqtt>=2,<3"') from exc
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  reconnect_on_failure=False)
        self.client.connect_timeout = 5
        if self.args.username:
            self.client.username_pw_set(self.args.username, os.environ.get('MQTT_PASSWORD'))
        if self.args.tls:
            self.client.tls_set(ca_certs=self.args.ca_file)
        def on_connect(client, userdata, flags, reason, properties):
            self.connected = not reason.is_failure
            self.notify('state', 'Connected' if self.connected else f'Connection rejected: {reason}')
            if self.connected:
                result, mid = client.subscribe([(topic, self.args.qos) for topic in self.args.subscribe])
                if result != mqtt.MQTT_ERR_SUCCESS:
                    self.notify('state', f'Subscription request failed: {result}')
        def on_subscribe(client, userdata, mid, reasons, properties):
            if any(reason.is_failure for reason in reasons):
                self.notify('state', 'Broker rejected a subscription')
            else:
                self.notify('subscribed', self.args.subscribe)
        def on_disconnect(client, userdata, flags, reason, properties):
            self.connected = False
            self.notify('state', f'Disconnected: {reason}')
        def on_message(client, userdata, msg):
            self.notify('message', (msg.topic, msg.payload[:2048].decode('utf-8', 'replace'), msg.retain))
        self.client.on_connect = on_connect
        self.client.on_subscribe = on_subscribe
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message
        self.state = 'Connecting / awaiting subscriptions...'
        self.client.connect(self.args.host, self.args.port, keepalive=30)
        self.client.loop_start()

    def pump(self):
        while True:
            try:
                kind, value = self.notifications.get_nowait()
            except queue.Empty:
                break
            if kind == 'message':
                topic, body, retained = value
                self.received[topic] += 1
                self.log.append((time.strftime('%H:%M:%S'), topic, body, retained))
            elif kind == 'subscribed':
                self.subscribed.update(value)
                self.state = 'Connected; subscriptions active'
            else:
                self.state = value

    @property
    def ready(self):
        return self.connected and (self.args.dry_run or set(self.args.subscribe) <= self.subscribed)

    def send(self, topic, payload):
        if not self.connected:
            raise RuntimeError('Broker connection lost; retry as a new experiment')
        if self.args.dry_run:
            return None
        info = self.client.publish(topic, json.dumps(payload, separators=(',', ':'), allow_nan=False),
                                   qos=self.args.qos, retain=False)
        if info.rc != 0:
            raise RuntimeError(f'MQTT publish failed: {info.rc}')
        return info

    def close(self):
        if self.client is not None:
            self.client.disconnect()
            self.client.loop_stop()
            self.client = None
        self.connected = False
        self.state = 'Disconnected'
