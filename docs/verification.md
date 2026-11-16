# Refactor verification — 16 November 2026

The missing `json` import in `transports/mqtt.py` was corrected after the first
real-send failure. The original dry-run checks bypassed serialization and were
insufficient to validate that path. A real-adapter regression now covers it.

## Results

- Static undefined-name analysis (Ruff F821/F822/F823): passed across the package and tests.
- Offline tests: 20 passing, including serialization, callbacks, subscription readiness, auth/TLS setup arguments, errors, launch paths, timing and batch scrolling.
- Five opt-in local-network tests passed using the real Paho client and an isolated loopback MQTT 3.1.1 test server: full step replay at QoS 0 and 1; real-time automatic replay; connection loss and reconnect; rejected subscription.
- Each full replay verified all 2,680 messages against the source schedule: topics, order, every payload field, rebased Unix timestamps, input hashes and subscription echoes.
- Real-time automatic playback completed in 66.009 s, with maximum measured scheduler lag 16.7 ms in that run. These are observed test results, not timing guarantees.
- The real curses module launch passed connect/subscription, two manual steps, scrolling to event 42, previous-batch view, retry, automatic playback, pause/resume and clean quit against the local test server.
- Nothing was published to the configured/user broker. Existing input traces were not changed.

## Rerun

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
the current MQTT/curses player; TCP/Textual remain unimplemented.
