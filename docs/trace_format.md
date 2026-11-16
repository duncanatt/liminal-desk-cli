# Trace format

Each input is a JSON object with exactly `version` (integer 1) and `steps` (array).
Each step is either `{"type":"send","payload":{...}}` or
`{"type":"delay","duration_ms":100}`. Delays are non-negative integers.
Send payloads are objects with an integer `timestamp_ms`. Duplicate JSON keys,
nonfinite constants, unknown steps, missing sends and timestamp/delay disagreement
are rejected before transmission. Both traces must use the same timestamp origin.

Delays define cumulative event offsets. At launch, outgoing payload copies get
`timestamp_ms = run_origin_ms + offset_ms`; source files remain unchanged. All
other payload fields pass through. Inputs are not restricted to the shop-floor
field names, but the current CLI interface labels its two streams machine/sensor.
At equal times first-stream messages precede second-stream messages; each input's
own tie order is preserved. N advances through the next first-stream timestamp,
including second-stream observations up to that boundary. A final step handles
any sensor tail and trailing delays. See usage.md for timing and ACK caveats.
