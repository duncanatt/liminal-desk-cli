# Liminal terminal replay

`replay_traces.py` is a coordinated publisher and subscriber for the two version-1
Desk trace files. It uses Python's built-in terminal UI on macOS/Linux and the
Paho MQTT client. It does not modify the trace files or the Desk application.

## Setup and launch

In Terminal:

```sh
cd /Users/duncan/Dropbox/Postdoc/Development/liminal-desk-cli
python3 -m venv .venv-replay
.venv-replay/bin/python -m pip install 'paho-mqtt>=2,<3'
.venv-replay/bin/python replay_traces.py --host localhost
```

Replace `localhost` with the host used by your Desk MQTT connection. The default
port is 1883. The tool does not start a broker. Give the terminal at least 110
columns and 34 rows to see the batch summary and subscription log together.
In smaller windows, E opens a dedicated scrollable payload view.

The default files are `machine_events.json` and `sensor_events.json` beside the
script. Alternatively pass two paths, in that order:

```sh
.venv-replay/bin/python replay_traces.py machine_events.json sensor_events.json \
  --host localhost --port 1883
```

Run without MQTT or external dependencies to explore the interface:

```sh
python3 replay_traces.py --dry-run
```

Validation without a terminal or network:

```sh
python3 replay_traces.py --check
```

## Controls

| Key | Action |
|---|---|
| B | Set broker host, port, and comma-separated subscription filters |
| C | Connect/disconnect; in dry run, enable/disable the simulated connection |
| L | Load and validate both files by path; Enter retains the current path |
| A | Start automatic replay |
| D | Arm step mode; does not send yet |
| N | Send the next machine-timestamp slice and its sensor batch |
| Up / Down | Scroll the sent-batch viewer by row |
| Page Up / Page Down | Scroll by a viewport |
| Home / End | Jump to the first/last rows of the batch |
| E | Expand/collapse the sent-step payload view |
| V | In expanded view, switch between current and previous batch |
| J / K | Scroll payload detail down/up |
| ] / [ | Page payload detail down/up |
| P or Space | Pause/resume automatic replay or a running step batch |
| R | Reset the experiment; then A or D starts again with a new Unix origin |
| Q | Disconnect and close; Ctrl-C also closes |

Connect first and wait for subscriptions to become active, then press A, or D
followed by N. To change files or connection during a run, press R first.
R restarts the whole experiment, not just an interrupted message. It cannot undo
messages already published. If using downstream monitors, reset their state
between experiments as appropriate. Automatic reconnect/resend is disabled;
connection loss stops the partial replay so a reconnect cannot silently splice
two experiments together. Press R, C to disconnect if necessary, C to reconnect,
then A/D to begin a new experiment.

## Timing and stepping

Each trace is parsed into offsets by adding its delay steps. Both streams share
one start time and one monotonic replay clock. A payload is copied immediately
before publishing and `timestamp_ms` is replaced by `run_origin_ms + offset_ms`.
Files and all other payload fields remain unchanged. Only the payload is
published, not the Desk `send` envelope.

Automatic mode preserves the relative schedule specified by delays. It schedules
against absolute offsets so processing overhead does not accumulate on every
delay. This is an intentional difference from Desk's per-step minimum waits:
Desk waits after a send finishes; this coordinated tool keeps both streams on
one timeline. A slow broker can still delay sends. The UI reports maximum send
lag instead of claiming real-time guarantees. It serializes sends and waits for
each publish confirmation; under backpressure, overdue messages are sent in
chronological order without dropping any. Large lag means the run is no longer
keeping up with real time; pause/reset rather than treating it as a timing test.

At timestamp ties, all machine events go first, then the sensor readings in
their source-file order. Sensor interleaving is retained. Both streams' trailing
delays are honored. Automatic replay of the supplied files lasts approximately
66 seconds plus connection setup and final transmission overhead.

P pauses both streams and freezes the remaining delay. A send already in flight
may complete, but no next message starts while paused. Resuming continues from
the frozen replay time. Payload timestamps represent simulated event time;
after a manual pause they no longer correspond to wall-clock delivery times.

In step mode, N advances through all events up to and including the next pending
machine-event timestamp. It ignores wall-clock waits, but preserves event-time
offsets and chronological publication. All machine events sharing a timestamp
form one step. Earlier sensors in the slice go first; at its ending timestamp,
machine events precede sensors. The first step for the supplied files sends the
two t=0 picks and four t=0 sensor observations. The second sends the sensors at
t=0.1–0.9, the two t=1 undocks, and the four t=1 sensors. No boundary sensors are
sent twice. If sensors continue after the final machine event, one more N sends
the remaining sensor tail. The next-step preview shows timestamp, batch counts,
and machine operation names before sending. Long batches can be paused.

### Inspecting the last step

**N now opens the sent-batch viewer automatically.** All confirmed machine and
sensor messages in that slice remain available for scrolling, even when the
batch is much taller than the terminal. It starts at the top and does not
automatically follow incoming messages, so your reading position stays stable.
Use arrow keys, Page Up/Down, Home/End, or J/K and ]/[. Mouse-wheel scrolling is
also supported where the terminal supplies wheel events. Use E for the overview
and V for the previous batch. Pressing N during an active batch does not reset
your scroll position or start a second overlapping batch.

Each event is numbered from 01 within its batch, followed by the local send time,
MQTT topic, and compact outgoing JSON. Numbers expand to three digits for large
batches. Wrapped continuation rows are indented beneath the same event rather
than numbered as separate events. Colors identify message kinds: machine
messages blue, vibration brown (yellow on basic 8-color terminals), and LiDAR
purple. The previous batch retains these colors but is dimmed. Local send time
is when the publish was initiated; the outgoing payload timestamp remains the
simulation's Unix event time. Only confirmed sends enter the list; an in-flight
message may not yet appear. In dry-run mode sends are simulated.

After N, the green **Sending step** pane shows the step number, timeline range,
machine/sensor totals, and confirmed-send count. It changes to **Last step sent**
only after the entire slice completes. Below it are the machine operation names
and sensor counts and first/last timestamps grouped by device and modality.
The preceding batch is separated by a divider and dimmed. The first step covers
t=0 only; later steps cover (previous timestamp, current timestamp]. Steps can
span multiple seconds, including the 20-second jump from t=13 to t=33.

E opens the batch payload inspector. It shows only confirmed outgoing payloads,
including their actual rewritten Unix timestamps and destination topics. V
switches to the dimmed previous batch. J/K scroll by line and ]/[ by page. N
can advance while inspecting; the view returns to the newest batch. P also
works while inspecting. A reset or file reload clears batch history. Only the
current and previous batches are retained. In dry run these are simulated sends.
This pane is separate from broker subscription receipts, which may include
echoes, retained messages and unrelated publishers. Automatic replay keeps its
existing progress display; the last-step pane is for manual step mode.

## Broker, subscriptions, and progress

Publish topics default to `liminal/machine_data` and `liminal/sensor_data`; set
`--machine-topic` and `--sensor-topic` to change them. The tool uses one connection
for both publishing and subscribing, with a unique broker-assigned client ID.
It subscribes to both publish topics by default, allowing you to observe its own
messages and other publishers on those topics. Keep Desk playback stopped when
using this publisher, to avoid duplicate experiments.

Add `--subscribe 'liminal/#'` or repeat `--subscribe` for selected filters,
including output topics for the monitors you want to inspect. Explicit
`--subscribe` options replace the default subscription list. The receive pane
shows topic counts and recent payloads; retained messages are marked. It is an
inspection view, not a permanent packet capture: the log holds 300 messages,
payload previews are limited to 2,048 bytes, and a 2,000-message pending display
queue drops new display entries if overloaded (with an omission counter).

The two progress bars count send events, not delay steps. Cyan is machine data;
magenta is sensor data. Each shows X/Y and a percentage, next-message countdown,
and last completed message. Trace elapsed excludes pauses, while wall elapsed
includes time spent paused or waiting for the next manual step.

Default QoS is 1: a send is counted after the broker's acknowledgment, which is
not acknowledgment of Liminal processing. QoS 1 can deliver duplicates; this tool
does not claim exactly-once processing. `--qos 0` counts local transmission
completion and provides no broker acknowledgment. Subscription receipt likewise
does not establish that a downstream monitor processed a message. At equal
timestamps this tool controls publication order; consumers on different
connections can still observe different delivery timing. Published messages
are never retained.

Optional authentication and TLS:

```sh
export MQTT_PASSWORD='your-password'
.venv-replay/bin/python replay_traces.py --host broker.example \
  --username your-user --tls --port 8883 --ca-file /path/to/ca.pem
```

Omit `--ca-file` for the default trusted certificate authorities. Passwords are
read from the environment and are not displayed by the UI. B changes host, port,
and subscriptions; authentication, TLS and publish topics are startup options.

## Checks performed

`python3 -m unittest -v test_replay_traces.py` covers the real supplied schedules,
machine-first ties, every step batch, fresh timestamps without source mutation,
pause timing, full automatic completion with a fake clock, in-flight ACKs,
disconnect failure, malformed traces, and sensor tails/trailing delays.

The terminal was exercised in a pseudo-terminal with dry-run connection and
multiple manual steps. An isolated local protocol test with the real Paho client
confirmed subscription acknowledgment, all 2,680 QoS-1 publishes and their ACKs,
and all 2,680 subscription echoes. No experiment was published to your broker.
TLS, authentication, and behavior with your particular broker and Liminal
deployment have not been exercised.

MQTT API reference: [Eclipse Paho Python client documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
