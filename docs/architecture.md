# Architecture

This is a structural extraction of the original single-file MQTT player, not a
new replay implementation. Launch from the repository root with
`python -m liminal_desk_cli`. `__main__.py` calls `cli.main`; `config.py` retains
the existing arguments and resolves default example paths relative to the package.

`replay/trace.py` validates version-1 JSON and `schedule.py` merges two traces with
machine-first timestamp ties. `engine.py` owns replay state, the shared clock,
timestamp rebasing, stepping, pause and confirmation tracking. It imports neither
curses nor Paho; it receives the broker object used for delivery. `models.py`
holds events and batches, including existing pure text-formatting helpers.

`transports/mqtt.py` holds the existing Broker connection and subscription code.
No new transport interface or TCP behavior is introduced in this refactor.
`ui/app.py` retains curses rendering/key handling, `screens.py` contains path-entry
prompts, and `widgets.py` contains pure scrolling logic. UI imports are deferred
for --help and --check. The engine and transports never import UI code.

Existing behavior remains two streams, the first machine stream driving N steps,
one in-flight send and the original publication order. Textual, arbitrary streams,
other manual step modes and TCP are not implemented here.

Tests use a fake publisher and clock. Launch tests run subprocesses and verify
the example defaults without installing the application. Fixtures use the supplied
example JSON so relocated file paths and packaged-module imports are exercised.
