# Testing Liminal Desk CLI

Run from the repository root with the Python environment active. No application
installation is needed. Install Paho for any test involving MQTT:

```sh
python -m pip install 'paho-mqtt>=2,<3'
```

## Offline checks

```sh
python -m unittest discover -v
python -m liminal_desk_cli --check
python -m liminal_desk_cli --transport tcp --check
```

At the TCP implementation checkpoint, discovery lists 48 tests: 31 offline cases
run, and 17 opt-in network cases are skipped. These counts describe that
checkpoint and may change as tests are added. The skipped tests are not silently
counted as successful network checks.

Offline checks cover parsing and malformed inputs, scheduling, timestamps,
pause/resume, batch formatting and scrolling, module launch, connection settings,
framing and frame limits, MQTT serialization/callbacks, and completion receipts.

## Isolated network integration

```sh
LIMINAL_TEST_MQTT=1 python -m unittest tests.test_mqtt_integration -v
LIMINAL_TEST_TCP=1 python -m unittest tests.test_tcp_integration -v
```

These opt-in fixtures bind to ephemeral ports on `127.0.0.1`. They do not contact
your configured MQTT broker or Liminal instance. The MQTT fixture implements the
packet subset used by the CLI; it is not a complete production broker.

The MQTT suite checks real Paho publication, subscription readiness, full replay
at QoS 0/1, rejected subscriptions and reconnect. The TCP suite checks shared and
separate connections, mixed MQTT/TCP routing, framing, fragmented/coalesced
replies, large frames, disconnects, limits, pause/resume and full replay. The TCP
suite's mixed/MQTT cases also require Paho even though TCP-only playback does not.
Each suite contains a real-time automatic replay taking about 66 seconds.

## Actual terminal controls

```sh
python -m tests.terminal_smoke --transport mqtt
python -m tests.terminal_smoke --transport tcp
```

These launch the application in a pseudo-terminal against isolated local test
servers. They exercise connect, stepping, batch scrolling, previous-batch view,
reset, automatic replay, pause/resume and quit. Terminal transcripts are saved in
the operating system's temporary directory as `liminal-ui-mqtt-transcript.txt`
and `liminal-ui-tcp-transcript.txt`.

## Compatibility with an actual Liminal binary

```sh
python -m tests.liminal_tcp_smoke --liminal /path/to/liminal
```

This starts the specified binary with a temporary configuration and loopback
ports, sends the example traces, then checks the payloads forwarded by Liminal's
TCP outputs. It expects all 36 machine and 2,644 sensor payloads intact and does
not change your running Liminal configuration. It is a transport compatibility
check, not a test of the shop-floor fusion rules. It requires a suitable compiled
Liminal binary; the command does not build one.

## Limits and historical results

The fixtures establish tested behavior, not delivery or scheduling guarantees.
Local TCP write completion does not prove remote processing; MQTT broker ACK
does not prove downstream processing. Live authenticated/TLS broker behavior and
production shop-floor fusion are outside these checks.

See [verification history](verification.md) for observed results from the
16 November 2026 audits. Those timings and counts are dated observations, not
new measurements each time this document is read. Unused-import cleanup and a
graphify refresh were identified separately and have not been performed by this
documentation update.
