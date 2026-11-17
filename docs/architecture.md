# Architecture

The player has transport-independent replay, MQTT/TCP adapters and one curses UI.
Launch from the repository root with
`python -m liminal_desk_cli`. `__main__.py` calls `cli.main`; `config.py` retains
the existing arguments and resolves default example paths relative to the package.

`replay/trace.py` validates version-1 JSON and `schedule.py` merges two traces with
machine-first timestamp ties. `engine.py` owns replay state, the shared clock,
timestamp rebasing, stepping, pause and confirmation tracking. It imports neither
curses nor Paho; it receives the shared transport manager used for delivery. `models.py`
holds events and batches, including existing pure text-formatting helpers.

`transports/manager.py` routes streams and shares connections at the same
transport/host/port. `base.py` defines neutral send completion. MQTT receipts
use broker ACK/local-write status; TCP receipts use local socket write completion.
`mqtt.py` contains the Broker; `tcp.py` implements length-prefixed JSON and
background I/O. The engine polls completion without implementing either protocol.
`ui/app.py` retains curses rendering/key handling, `screens.py` contains path-entry
prompts, and `widgets.py` contains pure scrolling logic. UI imports are deferred
for --help and --check. The engine and transports never import UI code.

Replay remains two streams, with the first driving N steps, one in-flight send
and the original publication order. Either stream can use MQTT or TCP. Textual,
arbitrary streams and other manual step modes remain future work.

Tests use a fake publisher and clock. Launch tests run subprocesses and verify
the example defaults without installing the application. Fixtures use the supplied
example JSON so relocated file paths and packaged-module imports are exercised.

Offline tests use fake publishers/clocks, while opt-in integration tests use real
Paho/TCP adapters against local protocol fixtures. Terminal smoke tests launch
the actual module in a pseudo-terminal; a separate compatibility check starts an
explicitly supplied Liminal binary. See [testing](testing.md) for commands and
scope. Generated graphify outputs are a navigation aid and require a refresh
after code changes; they are not an automatically maintained architecture view.
