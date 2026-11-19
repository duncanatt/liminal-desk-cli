# Usage and replay controls

Follow [README setup](../README.md) to install `requirements.txt` into your virtual
environment, then launch `python -m liminal_desk_cli` from the repository root.
Python 3.10+ and Textual are required for the interface; Paho is required for MQTT.
`--help` and `--check` remain usable without either dependency or a terminal.

## Workspace and controls

The One Dark Textual workspace has stream/connection information, driver and step
selectors, replay controls, progress, Sent batches and Received tabs, and an optional
payload inspector. Prefer a terminal at least 120 columns × 36 rows. Smaller
terminals retain scrollable tables and shortcuts; below 105 columns the batch
sidebar hides, and below 100 columns the mouse control row hides. V / Shift+V / F still select
previous / next / latest batches. The exact RGB palette requires a true-colour terminal and no
`NO_COLOR` environment variable.

| Key | Action |
|---|---|
| C | Connect/disconnect both streams; enables simulated connections in dry run |
| B | Edit per-stream MQTT/TCP settings and MQTT options |
| O / L | Browse and validate a trace file for either stream |
| A | Start automatic replay |
| D | Arm manual step mode |
| N | Send the next batch using the selected step mode |
| P / Space | Pause/resume an active automatic replay or step batch |
| R | Reset replay; next A/D creates a new Unix origin |
| Enter | Select a history batch or inspect the selected message |
| Escape | Close inspector or cancel dialog |
| Arrows / Page Up/Down / Ctrl+Home/End | Navigate the focused table |
| V / Shift+V / F | Select preceding / following / latest batch |
| E | Focus the sent-event table |
| Q | Close connections and quit |

These shortcuts apply in the workspace. In file/settings dialogs, text input and
selectors handle their own keys; Escape cancels. Mouse clicks and wheel scrolling
are also supported. Connect with C; wait for MQTT subscription readiness and/or TCP
connections before A or D. A shared endpoint uses one connection. Start brokers or
TCP receivers separately; the CLI does not start them.

Files and connection settings can change only before a run or after completion/reset.
Reset clears sent history and retains received history. An in-flight send finishes
before reset; an errored run closes the uncertain connection before resetting.
Reset cannot undo delivered messages. Connection loss stops replay; automatic
reconnect/resend is disabled. Reset and reconnect before starting a fresh experiment.

## Files and connection settings

O opens a directory browser. Choose a stream, then select a JSON file or enter its
path and press Enter. Enter on a directory navigates there. The preview validates
both the selected file and its shared timestamp origin with the other trace before
enabling Load trace. Cancel or invalid input leaves the existing trace unchanged.

Recent files and last folder are stored in `~/.config/liminal-desk-cli/ui.json`.
This contains paths only, not trace payloads or credentials. Source JSON is never
rewritten. A read-only home directory simply disables persistence.

B edits each stream's transport, host, port and MQTT topic, plus MQTT subscription
filters, QoS, TLS, username and CA certificate. TCP remains plain length-prefixed
JSON. The password is read from `MQTT_PASSWORD`, never stored by the interface.
Settings are validated before disconnecting/replacing the existing connections.

Startup options remain compatible:

```sh
python -m liminal_desk_cli --host localhost --port 1883
python -m liminal_desk_cli --transport tcp --host 127.0.0.1
python -m liminal_desk_cli --sensor-transport tcp --sensor-port 9002
python -m liminal_desk_cli first.json second.json
python -m liminal_desk_cli --dry-run
python -m liminal_desk_cli --check
```

See [TCP and mixed connections](tcp.md) for framing, ports and receiver setup.

## Timeline and stepping

Delay steps accumulate into trace offsets. Both streams share one replay clock and
Unix origin. Immediately before sending, a payload copy receives
`timestamp_ms = run_origin_ms + offset_ms`. All other fields are preserved. Only
payloads are sent, without the Desk send envelope.

Automatic mode schedules against absolute monotonic offsets to avoid accumulating
per-message processing overhead. This differs intentionally from a sequence of
minimum waits after each send. One send is in flight at a time. Backpressure can
make messages late, but does not reorder/drop them; maximum send lag is displayed.
Automatic replay honors trailing delays and lasts approximately 66 seconds for the
example, plus final transmission overhead. P freezes the replay clock; a send in
flight may complete, but no further send starts while paused. Pauses make simulated
event time differ from wall-clock delivery time. Wall elapsed includes pauses and
manual waiting; trace elapsed does not.

At equal timestamps, first-stream messages precede second-stream messages, with
source order preserved within each stream. Changing driver does not change this
publication ordering.

Choose a driver (first stream by default) and one manual step mode:

| Mode | N sends |
|---|---|
| Next driver event time | All pending messages through the next pending driver timestamp |
| Next timestamp | All pending messages at the next timestamp across both streams |
| Next message | Exactly one pending message, even when timestamps tie |

Manual steps ignore wall-clock delays and preserve payload event-time offsets. Once
the driver finishes, one further driver-mode N drains any remaining follower tail.
The preview shows the next boundary and stream counts. Selectors are locked during
an active batch/run or pause, and can change between completed manual batches.
Pressing N during an active batch does not start an overlapping batch.

With the example's default machine driver, N first sends 2 picks and 4 sensor
messages at t=0. The next N sends the sensors at t=0.1–0.9, two t=1 undocks, and
four t=1 sensors: 42 messages. A step can span multiple seconds, including t=13 to
33. With sensor driver or next timestamp, later boundaries are 100 ms apart. Next
message still sends one message at a time, with repeated event timestamps allowed.

## Sent history and payload inspection

Every manual batch remains available in the sidebar for the current run. Automatic
replay groups confirmed sends by timestamp. Select a batch and press Enter (or
click it) to view its events. N selects the newly requested manual batch. Switching
tabs or receiving traffic preserves selection and scrolling. Older batches are
dimmed; machine events are blue, vibration amber, LiDAR purple, other kinds cyan.

Rows show event number, local send initiation time, trace offset, stream, kind,
device and a short summary. Numbers restart at 01 for each batch. Filters by stream
and kind keep original numbers, making gaps visible. All rows remain scrollable;
Enter opens the full actual outgoing JSON and destination. Escape closes it.
With the inspector open, moving through the sent table updates the inspected event.

Only completed sends enter the table. The progress/status area identifies a pending
send or the next delay. Completion labels distinguish simulated sends, MQTT QoS 1
broker acknowledgment, MQTT QoS 0 local transmission, and TCP local socket writes.
None proves that Liminal processed the event. QoS 1 may deliver duplicates; no
exactly-once processing guarantee is made.

## Received traffic

Received is separate from sent history. MQTT subscriptions may contain echoes,
retained messages and other publishers. TCP displays framed replies only when the
server sends them; normal Liminal TCP inputs do not reply. Enter inspects body,
source, receive time and retained status. Incoming rows do not move your cursor.

The display retains the latest 3,000 received records, with globally increasing
receive row numbers for the session. Transport preview limits still apply: each
adapter retains 300 log records, truncates bodies to 2,048 bytes and bounds its
pending display queue at 2,000 entries. Overload omissions are reported separately.
This is an inspection display, not a permanent packet capture. Receive topic counts
restart when a connection is reopened; the visible session history is retained.

MQTT publish topics default to `liminal/machine_data` and `liminal/sensor_data`.
Subscriptions default to the MQTT publish topics. Repeat `--subscribe` to replace
them, e.g. `--subscribe 'liminal/#'`. Published messages are never retained. Separate
consumer connections can observe different delivery timing even though this sender
preserves its own publication order.

```sh
export MQTT_PASSWORD='your-password'
python -m liminal_desk_cli --host broker.example --username your-user \
  --tls --port 8883 --ca-file /path/to/ca.pem
```

Omit `--ca-file` to use default trusted authorities. Keep other replay publishers
stopped to avoid accidentally duplicating an experiment.
