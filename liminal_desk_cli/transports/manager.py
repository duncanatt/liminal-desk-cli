"""Route two streams through shared MQTT/TCP adapters, on one replay timeline."""
from collections import Counter, deque
from copy import copy
from .base import MqttReceipt
from .mqtt import Broker
from .tcp import TcpClient


class TransportManager:
    def __init__(self, args):
        self.args = args
        self.adapters = []
        self.routes = {}
        self.received = Counter()
        self.log = deque(maxlen=300)
        self.dropped = 0
        self.record_log = deque(maxlen=3000)
        self.record_serial = 0
        self._seen = {}
        self._omitted = 0
        groups = {}
        for stream in args.streams:
            key = (stream.transport, stream.host, stream.port)
            if key not in groups:
                if stream.transport == 'mqtt':
                    options = copy(args)
                    options.host, options.port = stream.host, stream.port
                    adapter = Broker(options)
                else:
                    adapter = TcpClient(stream.host, stream.port, args.dry_run, args.max_frame_bytes)
                groups[key] = adapter
                self.adapters.append((key, adapter))
            self.routes[stream.destination] = (stream.transport, groups[key])

    @property
    def connected(self):
        return bool(self.adapters) and all(a.connected for _,a in self.adapters)

    @property
    def ready(self):
        return bool(self.adapters) and all(a.ready for _,a in self.adapters)

    @property
    def is_open(self):
        return any(a.connected or a.client is not None for _,a in self.adapters)

    @property
    def not_ready_message(self):
        if all(kind == 'tcp' for (kind,_,_),_ in self.adapters):
            return 'Connect both TCP stream endpoints first (C)'
        return 'Connect both stream endpoints and wait for MQTT subscription confirmation (C)'

    @property
    def state(self):
        return ' | '.join(f'{kind.upper()} {host}:{port}'+(f' QoS {self.args.qos}' if kind=='mqtt' else ' plain')+f': {a.state}'
                          for (kind,host,port),a in self.adapters)

    def connect(self):
        self.close()
        self._seen.clear()
        self.received.clear()
        self._omitted = 0
        try:
            for _, adapter in self.adapters:
                adapter.connect()
        except Exception:
            self.close()
            raise

    def close(self):
        errors = []
        for _, adapter in self.adapters:
            try:
                adapter.close()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError('; '.join(errors))

    def send(self, destination, payload):
        if not self.connected:
            raise RuntimeError('Connection lost; reset the experiment before retry')
        kind, adapter = self.routes[destination]
        receipt = adapter.send(destination, payload)
        return MqttReceipt(receipt) if kind == 'mqtt' and receipt is not None else receipt

    def send_status(self, destination):
        if self.args.dry_run:
            return 'Sending (simulated)'
        kind, _ = self.routes[destination]
        if kind == 'tcp':
            return 'Sending: awaiting local TCP write (no application ACK)'
        return 'Sending: awaiting broker ACK' if self.args.qos else 'Sending: awaiting local MQTT write'

    def pump(self):
        total = Counter()
        for key, adapter in self.adapters:
            adapter.pump()
            count = sum(adapter.received.values())
            delta = max(0, count-self._seen.get(key, 0))
            if delta:
                records = list(adapter.log)[-delta:]
                self._omitted += max(0, delta-len(records))
                self.log.extend(records)
                for record in records:
                    self.record_serial += 1
                    self.record_log.append((self.record_serial, *record))
            self._seen[key] = count
            total.update(adapter.received)
        self.received = total
        self.dropped = self._omitted + sum(a.dropped for _,a in self.adapters)
