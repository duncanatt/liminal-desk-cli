# Architecture

One transport-independent replay engine serves one Textual interface for MQTT,
TCP and mixed connections. Launch from the repository root with
`python -m liminal_desk_cli`; application installation is optional.

- `cli.py` validates inputs and defers Textual imports until interactive launch.
  `config.py` resolves paths, endpoints, authentication and protocol options.
- `replay/trace.py` validates version-1 Desk JSON. `schedule.py` merges trace offsets
  and selects driver, timestamp or single-message boundaries. Timestamp ties retain
  stream order, independently of the selected driver.
- `replay/engine.py` owns the common monotonic clock, timestamp rebasing, pause,
  one-in-flight-send rule, confirmation tracking and complete run batch history.
  Manual steps have both a time boundary and an end index, so single-message steps
  do not accidentally consume other messages at the same timestamp.
- `transports/manager.py` routes streams, shares adapters at identical endpoints,
  and assigns receive record sequence numbers for the UI. `base.py` abstracts
  completion; `mqtt.py` wraps Paho and `tcp.py` implements framed background I/O.
- `ui/app.py` owns workspace interaction and polls replay/transport progress.
  Rendering is throttled independently from the send pump. `screens.py` contains
  transactional file/connection dialogs. `theme.py` and `desk.tcss` define the
  explicit One Dark palette. UI selection and scrolling are independent of network
  arrival. `widgets.py` retains pure scrolling helpers tested by earlier checks.

The engine and transports import no UI libraries. `--check` and `--help` require
neither Textual nor Paho. MQTT still needs Paho at runtime; TCP needs no MQTT
library. Textual is needed for any interactive transport. The flat package layout
and conventional module launch are unchanged.

The schedule and engine support multiple stream indices; the current launcher and
file/settings UI expose two streams with the existing machine/sensor labels. Either
can be driver, and payloads need no shop-floor-specific fields beyond the trace
format's timestamp. Arbitrary stream creation remains outside this release.

Sent history is held in memory for a run. Received display is bounded to 3,000
records; adapter queue/log/body limits are independent. Reset replaces the engine
and clears sent history, while received session records remain available. UI file
preferences contain recent paths and folder only.

Tests cover deterministic clocks/publishers, real Textual widgets with headless
Pilot interactions, launch subprocesses, isolated MQTT/TCP fixtures and a real
pseudo-terminal launch. See [testing](testing.md). Graphify outputs are an older
navigation snapshot until explicitly refreshed; source and tests are authoritative.
