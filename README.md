# Liminal Desk CLI

A terminal-based MQTT/TCP trace player for Liminal, with synchronized replay,
interactive stepping and live message inspection.

## Setup

Python 3.9 or newer on macOS/Linux. Run commands from the repository root.
The application does not need to be installed.

For a fresh checkout, create and activate a Python environment:

```sh
cd liminal-desk-cli
python3 -m venv .venv
source .venv/bin/activate
```

If you already use the existing `venv/`, activate it with
`source venv/bin/activate` instead. Install the MQTT dependency if using MQTT:

```sh
python -m pip install 'paho-mqtt>=2,<3'
```

TCP-only replay, offline validation and dry-run mode use the Python standard
library and do not require Paho. The current interface uses curses, not Textual.

## Launch

```sh
# MQTT: both streams use localhost:1883 by default.
python -m liminal_desk_cli

# TCP: machine input on 8080, sensor input on 8081.
python -m liminal_desk_cli --transport tcp --host 127.0.0.1

# Mixed: machine MQTT on 1883; sensor TCP on 9002.
python -m liminal_desk_cli --sensor-transport tcp --sensor-port 9002

# Inspect the interface without connecting or sending.
python -m liminal_desk_cli --dry-run

# Validate both input traces without a terminal or network.
python -m liminal_desk_cli --check
```

Your broker or Liminal TCP server must already be running. The CLI does not
start either. See [TCP setup](docs/tcp.md) and the
[example Liminal TCP receiver](examples/shop_floor/liminal_tcp_inputs.toml).
The receiver prints raw inputs; it does not implement shop-floor fusion.

The default traces are in `examples/shop_floor/`. Supply your own in this order:

```sh
python -m liminal_desk_cli path/to/machine.json path/to/sensor.json --host localhost
```

## Controls

| Key | Action |
|---|---|
| C | Connect/disconnect both streams |
| B | Edit per-stream MQTT/TCP connection settings |
| L | Load the two trace files by path |
| A | Start automatic replay |
| D, then N | Enter step mode and send the next time slice |
| P / Space | Pause/resume |
| R | Reset for another run with fresh Unix timestamps |
| E / V | Toggle batch/overview or inspect the previous batch |
| Arrows, Page Up/Down, Home/End | Scroll the batch viewer |
| Q | Disconnect and quit |

Connect with C first; wait for MQTT subscription confirmation or TCP connection
readiness. Then use A or D followed by N. In a dry run, C enables the simulated
connection. N advances to the next timestamp in the first (machine) trace and
sends all unsent events from both traces through that boundary. It does not mean
one second or one message. Long batches remain scrollable and pauseable.

The supplied experiment spans 66 seconds. Timestamps are refreshed in outgoing
payload copies; source files are unchanged. TCP completion means a local socket
write, not confirmation of Liminal processing. See the usage guide for MQTT
acknowledgment and timing details.

## Documentation

- [Usage, controls and timing](docs/usage.md)
- [TCP and mixed MQTT/TCP connections](docs/tcp.md)
- [Trace format](docs/trace_format.md)
- [Architecture](docs/architecture.md)
- [Testing and verification](docs/testing.md)
- [Shop-floor scenario](docs/shop_floor_scenario.md)
- [Interactive presentation](docs/shop_floor_scenarios.html)

## Development

```sh
python -m unittest discover -v
```

The default suite performs offline checks; network tests are explicitly opt-in.
See [testing](docs/testing.md) for integration and terminal smoke commands.

Application code lives in `liminal_desk_cli/`, tests in `tests/`, sample inputs in
`examples/`, and documentation in `docs/`. `pyproject.toml` declares metadata and
dependencies; it is not required for the repository-root module launch.

MQTT and TCP are implemented with the existing curses UI and two-stream replay.
Textual, arbitrary stream counts, driver selection and alternative manual step
modes remain future work. File selection currently uses path prompts.

See [LICENSE](LICENSE) for licensing terms.
