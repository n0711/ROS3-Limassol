# Receiver observation recording, version 1

The recording is UTF-8 JSON Lines. Each line has exactly three fields:
`record_version` (integer 1), `time_s` (finite nonnegative receiver-relative
seconds), and `payload` (raw telemetry JSON text, or null for an observation tick).
Time must be non-decreasing. Simultaneous arrivals are permitted.

```json
{"time_s":2.9,"payload":null,"record_version":1}
```

A payload is a JSON string containing the complete [telemetry object](TELEMETRY.md),
not a nested object. Raw text preserves malformed JSON and duplicate telemetry
keys for replay. A malformed recording envelope aborts with its line number.
Malformed telemetry increments the rejection counter without refreshing liveness.

## Usage

From `robotics/ros3_limassol/`:

```sh
python -m ros3_limassol.demo --record run.jsonl --json
python -m ros3_limassol.replay run.jsonl --json
python -m ros3_limassol.replay run.jsonl --stale-after 2.0 --json
```

The first two outputs match for the same timeout. The default file contains 81
observations, including 30 null ticks during the blackout. Recording refuses to
overwrite existing files; use a new filename for another experiment.

Replay advances virtual receiver time without sleeping. It evaluates status at
recorded observation instants and reports transitions and a final summary. Null
ticks preserve observations during silence, including after the last message.
Replay does not invent evaluations in missing intervals. Empty files produce
WAITING with zero accepted/rejected messages.

## Limits and interpretation

- Each line is bounded to 32768 UTF-8 bytes, including any line ending.
- Non-null payloads are bounded to 4096 UTF-8 bytes, matching the core contract.
- Traces are limited to one million observations and processed incrementally.
- Unknown fields, duplicate envelope keys, booleans used as numbers, non-finite
  times and backwards time are errors. Oversized payloads are recording errors;
  this format does not preserve oversized incoming messages.

The demo records synthetic observations. A live ROS, UDP or MAVLink recorder is
future work. External recorders must use offsets from one receiver monotonic
clock and periodic null ticks to represent silence. Sender timestamps remain
payload metadata. Replay reproduces the application rule; it does not measure
network latency, discovery, scheduling or sensor capture freshness.
