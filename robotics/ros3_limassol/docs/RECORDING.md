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
Invalid demo options are rejected before creating the output file, so a corrected
retry can reuse the requested path. This includes invalid timeouts, blackout
settings and configurations exceeding the observation-count limit.

Replay rejects invalid UTF-8 with the affected recording line number and exits
with CLI status 2. It decodes bounded binary lines individually so a damaged
later line is not attributed to an earlier buffered read. A failure can follow
already emitted transitions; only a successful exit and final summary establish
that replay reached the end of the recording.

Replay advances virtual receiver time without sleeping. It evaluates status at
recorded observation instants and reports transitions and a final summary. Null
ticks preserve observations during silence, including after the last message.
Replay does not invent evaluations in missing intervals. Empty files produce
WAITING with zero accepted/rejected messages.

## Offline analysis report

After creating an existing version-1 recording, you can produce a read-only
[receiver-observation evidence report](EVIDENCE.md) with
`python -m ros3_limassol.evidence run.jsonl`. This is a deterministic summary
of observation and monitor state, not a network-performance measurement.

## Limits and interpretation

- Each line is bounded to 32768 UTF-8 bytes, including any line ending.
- Non-null payloads are bounded to 4096 UTF-8 bytes, matching the core contract.
- Traces are limited to one million observations and processed incrementally.
- Unknown fields, duplicate envelope keys, booleans used as numbers, non-finite
  times and backwards time are errors. Oversized payloads are recording errors;
  this format does not preserve oversized incoming messages.

## Live ROS recording (0.3.0)

`telemetry_recorder` subscribes to the existing `telemetry` topic; it does not
publish application telemetry, link status or vehicle commands. The
`record_telemetry.launch.py` launch selects `/limassol/<robot_id>/`. Start it in a
sourced ROS workspace with `output_path:=run.jsonl`; see the [package guide](../README.md).

The transport-independent `LiveRecorder` creates the file exclusively and writes
an initial null observation at time zero. Callback arrivals and periodic null
ticks share offsets from one receiver `time.monotonic()` clock. The timer uses a
steady ROS clock, so silence continues to be observed without incoming messages
and when ROS simulation time is paused. Timer callbacks do not establish a hard
scheduling bound. Shutdown closes the file without inventing an additional tick.

Each observation is flushed for incremental reading. This does not call `fsync`
or guarantee persistence during a crash or power loss. Writes run synchronously;
a slow disk can delay callback processing. A broken final line after an I/O or
process failure is reported as an input error by replay, rather than repaired.

The default maximum is one million observations, counting arrivals and null
ticks together, including the initial observation. `max_records` may reduce that
limit. At the limit, or on a file/clock error, the recorder process exits nonzero;
the existing file is retained. There is no silent rotation or automatic overwrite.
Choose a new path for a new session. Bounded malformed JSON is recorded unchanged
and rejected later by replay. Oversized/non-UTF-8 payloads cannot fit this format:
the ROS node counts them, warns on the first occurrence, and logs the total on
shutdown. They do not appear in the replay rejection count.

The recorder uses best-effort, volatile, depth-1 telemetry QoS. It records only
callbacks actually delivered to this subscriber; it may miss discovery-time
traffic, dropped messages or samples superseded before callback execution. Its
receiver arrival clock differs from a separately running monitor's clock and
timer schedule. Replay reproduces this recorder's observations and does not
promise identical transition times to that other monitor.

UDP and MAVLink input remain future work. Sender timestamps remain payload
metadata. Replay reproduces the application rule; it does not measure network
latency, discovery, scheduling or sensor capture freshness.
