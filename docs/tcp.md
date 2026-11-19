# TCP and mixed-transport replay

The existing replay engine and Textual interface support MQTT and TCP. MQTT
remains the default. Timing, Unix timestamp rebasing, N-step boundaries, colored
numbered batches, pause/resume and retry all use the same engine.

## Launch

From the repository root, with your environment active:

```sh
# Machine TCP input on 8080, sensor TCP input on 8081.
python -m liminal_desk_cli --transport tcp --host 127.0.0.1

# Separate custom TCP endpoints.
python -m liminal_desk_cli --transport tcp --host 127.0.0.1 \
  --machine-port 9001 --sensor-port 9002

# Both streams share one socket.
python -m liminal_desk_cli --transport tcp --host 127.0.0.1 --port 9000

# Machine MQTT plus sensor TCP.
python -m liminal_desk_cli --machine-transport mqtt --machine-port 1883 \
  --sensor-transport tcp --sensor-host 127.0.0.1 --sensor-port 9002

# Try the controls without network access or Paho (Textual is still required).
python -m liminal_desk_cli --transport tcp --dry-run
```

Positional trace paths work as before. `--transport` defaults both streams;
per-stream transport/host/port options override common settings. An explicit
`--port` applies to both unless overridden. Otherwise MQTT defaults to 1883
(8883 with TLS); TCP uses 8080 for machine and 8081 for sensor.

Press C to connect both streams, A for automatic replay, or D then N to step.
B edits each stream's transport, host, port, and MQTT topic where applicable.
Settings are validated before replacing the old configuration. Use R first
during a run. Changing connections resets the replay; it does not send messages.

The CLI is a TCP **client**; Liminal's input must be in **server** mode. The
[example receiver](../examples/shop_floor/liminal_tcp_inputs.toml) listens on the
default two ports and prints raw inputs. It does not perform shop-floor fusion.
To retain fusion, replace only the existing MQTT inputs with TCP inputs while
preserving their `machine_data` and `sensor_data` output channel names. No running
Liminal configuration is modified and no broker/server is started by the CLI.

## Wire format

Liminal expects a four-byte unsigned **big-endian payload byte length** followed
by that many UTF-8 JSON bytes. The CLI sends the payload alone, without a Desk
send envelope, topic field or newline. Received frames use the same format.

The default inbound/outbound JSON limit is 1,048,576 bytes (1 MiB), matching the
current Liminal default. `--max-frame-bytes` changes the CLI limit; configure the
receiver consistently. The four-byte prefix is excluded from the limit. Invalid
non-finite JSON and oversized outbound payloads fail before sending. Oversized
inbound prefixes close the connection before reading their body. Fragmented and
coalesced inbound frames are buffered correctly.

Streams with the same transport/host/port share an adapter and TCP socket. Separate
endpoints get separate connections. I/O runs in background workers so partial
writes or replies do not block controls. Initial connection setup may wait up to
five seconds per endpoint. The engine still has one in-flight send globally.
Across distinct connections, downstream arrival/processing order can still vary;
one replay clock does not enforce an event-time merge inside Liminal.

## Completion and reception

TCP completion means the whole frame was written to the **local socket**, not
that Liminal received or processed it. MQTT QoS 1 completion means broker ACK;
QoS 0 means local transmission. The pending-send status makes this distinction.
Failure may follow partial delivery. There is no automatic reconnect/resend;
reset, reconnect and begin a new experiment after a failure.

TCP has no subscriptions. The received pane displays framed replies on the same
connection, if the server sends any. A normal Liminal TCP input does not reply,
so zero received messages is expected. A shared connection cannot attribute a
reply to one stream without application-level correlation. Logs/previews are
bounded; this is not a packet recorder or a listener for separate TCP outputs.

TCP is plain. TLS, CA files, usernames/passwords, QoS, MQTT topics and subscription
filters apply only to MQTT. MQTT-only connection options are rejected for an
all-TCP command. In mixed mode TLS applies to MQTT and TCP remains plain. The
example inputs bind to loopback.

## Tests

```sh
python -m unittest discover -v
LIMINAL_TEST_TCP=1 python -m unittest tests.test_tcp_integration -v
python -m tests.terminal_smoke --transport tcp
python -m tests.terminal_smoke --transport mqtt
python -m tests.liminal_tcp_smoke --liminal /path/to/liminal
```

The opt-in tests use only ephemeral loopback ports. They cover full shared,
separate and mixed replays, real-time replay, fragmented replies, large writes,
frame limits, disconnect/reconnect and pause/resume. The separate Liminal test
starts the specified binary with temporary inputs/outputs and verifies all 2,680
forwarded payloads. It does not exercise your production fusion configuration
or contact your configured MQTT broker.
