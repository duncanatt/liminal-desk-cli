"""TCP client: four-byte big-endian UTF-8 JSON frames, matching Liminal."""
from collections import Counter, deque
import json
import queue
import select
import socket
import struct
import threading
import time


DEFAULT_MAX_FRAME_BYTES = 1024 * 1024


def encode_frame(payload, limit=DEFAULT_MAX_FRAME_BYTES):
    data = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(data) > limit:
        raise ValueError(f'TCP frame is {len(data)} bytes; limit is {limit}')
    return struct.pack('!I', len(data)) + data


class TcpReceipt:
    def __init__(self):
        self.finished = threading.Event()
        self.error = None

    def finish(self, error=None):
        self.error = error
        self.finished.set()

    def is_complete(self):
        if not self.finished.is_set():
            return False
        if self.error:
            raise RuntimeError(self.error)
        return True


class TcpClient:
    def __init__(self, host, port, dry_run=False, max_frame_bytes=DEFAULT_MAX_FRAME_BYTES):
        self.host, self.port, self.dry_run = host, port, dry_run
        self.limit = max_frame_bytes
        self.label = f'tcp://{host}:{port}'
        self.client = None
        self.connected = False
        self.state = 'Disconnected'
        self.received = Counter()
        self.log = deque(maxlen=300)
        self.dropped = 0
        self._messages = queue.Queue(maxsize=2000)
        self._outgoing = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = None
        self._wake_read = self._wake_write = None

    def _wake(self):
        if self._wake_write is not None:
            try:
                self._wake_write.send(b'\0')
            except (BlockingIOError, OSError):
                pass

    @property
    def ready(self):
        return self.connected

    def connect(self):
        self.close()
        self.received.clear()
        self.log.clear()
        self.dropped = 0
        self._messages = queue.Queue(maxsize=2000)
        self._outgoing = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        if self.dry_run:
            self.connected = True
            self.state = 'Dry run: no TCP connection'
            return
        self.state = 'Connecting'
        sock = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setblocking(False)
        except OSError as exc:
            if sock is not None:
                sock.close()
            self.state = f'Connection failed: {exc}'
            raise RuntimeError(f'{self.label}: {self.state}') from exc
        self.client = sock
        self._wake_read, self._wake_write = socket.socketpair()
        self._wake_read.setblocking(False)
        self._wake_write.setblocking(False)
        self.connected = True
        self.state = 'Connected (local write completion; no application ACK)'
        self._thread = threading.Thread(target=self._io, args=(sock,), daemon=True,
                                        name=f'liminal-{self.label}')
        self._thread.start()

    def send(self, destination, payload):
        if not self.connected:
            raise RuntimeError(f'{self.label}: TCP connection lost; reset before retry')
        frame = encode_frame(payload, self.limit)
        if self.dry_run:
            return None
        receipt = TcpReceipt()
        try:
            self._outgoing.put_nowait((frame, receipt))
        except queue.Full as exc:
            raise RuntimeError('TCP send already queued') from exc
        self._wake()
        return receipt

    def _io(self, sock):
        buffer = bytearray()
        current = None
        receipt = None
        offset = 0
        error = None
        try:
            while not self._stop.is_set():
                if current is None:
                    try:
                        current, receipt = self._outgoing.get_nowait()
                        offset = 0
                    except queue.Empty:
                        pass
                readable, writable, exceptional = select.select([sock, self._wake_read], [sock] if current is not None else [], [sock], .1)
                if self._wake_read in readable:
                    try:
                        self._wake_read.recv(4096)
                    except BlockingIOError:
                        pass
                    readable.remove(self._wake_read)
                if exceptional:
                    raise ConnectionError('TCP socket error')
                if readable:
                    try:
                        data = sock.recv(65536)
                    except BlockingIOError:
                        data = None
                    if data == b'':
                        raise ConnectionError('TCP peer closed the connection')
                    if data:
                        buffer.extend(data)
                        while len(buffer) >= 4:
                            length = struct.unpack('!I', buffer[:4])[0]
                            if length > self.limit:
                                raise ValueError(f'Incoming TCP frame {length} exceeds limit {self.limit}')
                            if len(buffer) < 4 + length:
                                break
                            body = bytes(buffer[4:4+length])
                            del buffer[:4+length]
                            try:
                                self._messages.put_nowait((time.strftime('%H:%M:%S'), body[:2048].decode('utf-8', 'replace')))
                            except queue.Full:
                                self.dropped += 1
                if writable and current is not None:
                    try:
                        sent = sock.send(memoryview(current)[offset:])
                    except BlockingIOError:
                        continue
                    if sent == 0:
                        raise ConnectionError('TCP write returned zero')
                    offset += sent
                    if offset == len(current):
                        receipt.finish()
                        current = receipt = None
        except Exception as exc:
            if not self._stop.is_set():
                error = f'{self.label}: {exc}; partial delivery is possible; reset before retry'
                self.state = error
        finally:
            self.connected = False
            failure = error or 'TCP connection closed before send completion; delivery may be partial'
            if receipt is not None:
                receipt.finish(failure)
            while True:
                try:
                    _, queued = self._outgoing.get_nowait()
                    queued.finish(failure)
                except queue.Empty:
                    break

    def pump(self):
        while True:
            try:
                stamp, body = self._messages.get_nowait()
            except queue.Empty:
                break
            self.received[self.label] += 1
            self.log.append((stamp, self.label, body, False))

    def close(self):
        self._stop.set()
        self._wake()
        if self.client is not None:
            try:
                self.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(2)
            if self._thread.is_alive():
                raise RuntimeError('TCP worker did not stop; do not reconnect yet')
            self._thread = None
        if self.client is not None:
            self.client.close()
            self.client = None
        for wake in (self._wake_read, self._wake_write):
            if wake is not None:
                wake.close()
        self._wake_read = self._wake_write = None
        self.connected = False
        self.state = 'Disconnected'
