# Verification history — 16 November 2026

For current test commands and prerequisites, see [testing.md](testing.md).
The results below are dated audit observations, not fresh measurements from
17 November or guarantees for a running deployment.

The missing `json` import in `transports/mqtt.py` was corrected after the first
real-send failure. The original dry-run checks bypassed serialization and were
insufficient to validate that path. A real-adapter regression now covers it.

## Initial MQTT refactor audit

- Static undefined-name analysis (Ruff F821/F822/F823): passed across the package and tests.
- Offline tests: 20 passing, including serialization, callbacks, subscription readiness, auth/TLS setup arguments, errors, launch paths, timing and batch scrolling.
- Five opt-in local-network tests passed using the real Paho client and an isolated loopback MQTT 3.1.1 test server: full step replay at QoS 0 and 1; real-time automatic replay; connection loss and reconnect; rejected subscription.
- Each full replay verified all 2,680 messages against the source schedule: topics, order, every payload field, rebased Unix timestamps, input hashes and subscription echoes.
- Real-time automatic playback completed in 66.009 s, with maximum measured scheduler lag 16.7 ms in that run. These are observed test results, not timing guarantees.
- The real curses module launch passed connect/subscription, two manual steps, scrolling to event 42, previous-batch view, retry, automatic playback, pause/resume and clean quit against the local test server.
- Nothing was published to the configured/user broker. Existing input traces were not changed.

## Initial MQTT audit commands

From the repository root, with the project's environment active:

```sh
python -m unittest discover -v
LIMINAL_TEST_MQTT=1 python -m unittest tests.test_mqtt_integration -v
python -m tests.terminal_smoke
```

The first command is offline; the five integration tests are skipped unless
explicitly enabled. The last two commands bind only to 127.0.0.1 on ephemeral
ports. The full automatic integration test takes approximately 66 seconds.

The local MQTT fixture implements the packet subset used by the application;
it is not a substitute for testing a production broker. Authentication and TLS
configuration were checked with mocks, not an actual secured broker. There is
no end-to-end Liminal processing validation in these tests. This audit tests
the MQTT/curses player at the initial refactor checkpoint. Later TCP coverage is
recorded below; Textual remains unimplemented.

## TCP addition — 16 November 2026

- 31 offline checks pass, including new framing, configuration, receipts, routing
  and connection-menu checks. The normal suite lists 48 cases, skipping 17
  opt-in networking cases by default.
- The TCP integration checks passed for shared/separate endpoints, mixed MQTT/TCP,
  MQTT through the manager, fragmented/coalesced replies, large frames, limits,
  disconnect/reconnect, refused ports, global stop and pause/resume.
- A full automatic TCP replay completed in 66.009 s, with observed maximum
  scheduler lag 9.5 ms. All 2,680 received payloads matched their scheduled order,
  values, topics/destinations and rewritten timestamps. Source JSON hashes match.
- Four existing fast MQTT integration checks were rerun successfully; the original
  66-second MQTT timing result above was not remeasured in this TCP audit.
- Terminal smoke tests passed using the actual module launch over both MQTT and
  TCP. The TCP smoke test forces a full terminal redraw to verify the final event
  number rather than assuming incremental ANSI output contains complete lines.
- The existing local Liminal binary received, parsed and forwarded all 36 machine
  and 2,644 sensor payloads intact over TCP, through separate temporary inputs and
  outputs. The fixture uses unique stage names and an explicit test log filter.
  This is compatibility with that binary, not validation of production fusion.
- MQTT reconnect now discards old queued session callbacks, preventing a stale
  subscription confirmation from enabling a new replay prematurely.

See [TCP instructions](tcp.md) for the framing contract, limits and rerun commands.


## Textual / One Dark interface — 17 November 2026

The curses interface was replaced by Textual while retaining the replay engine and
MQTT/TCP adapters. Added driver selection, three manual step modes, complete run
batch history, stable scrolling, filters, payload inspection, validated file
browsing and connection dialogs. The two example trace files were unchanged.

- Offline discovery: 55 cases, 38 run successfully and 17 opt-in cases skipped.
- Explicit loopback integration: all 17 MQTT/TCP cases passed, including full
  66-second automatic replays and comparison of original payload fields.
- Real pseudo-terminal MQTT and TCP checks passed connection, two N batches,
  scrolling/inspection, previous batch, reset, automatic replay, pause/resume and quit.
- Full-duration Textual run with machine MQTT and sensor TCP delivered all
  36 + 2,644 messages, recording every completed send. Maximum observed send lag
  in this headless rendering test was 107.8 ms; this is a measurement, not a timing
  guarantee. Payload timestamps still derive from the unchanged trace offsets.
- Headless interaction checks exercise file rejection/load/cancel, settings
  validation, retained event numbers under filters, scroll/selection across tabs
  and batches, alternate driver/modes, and a small 80×24 terminal.

These tests use isolated local protocol fixtures. They do not verify a production
broker, TLS credentials, downstream fusion rules, or Liminal processing ACKs.
Graphify outputs have not been refreshed by this UI implementation.
