# Telemetry schema v1

All fields are required. Unknown or duplicate fields are rejected. The message
must be a JSON object encoded as UTF-8, at most 4096 bytes.

- `schema_version`: the integer `1`.
- `robot_id`: 1-32 ASCII characters matching `[a-z][a-z0-9_]{0,31}`.
- `session_id`: 1-64 ASCII letters, digits, underscores, or hyphens. The supplied
  simulator uses a new UUID for each ROS publisher process.
- `sequence`: integer from zero through `2^63-1`, strictly increasing within a
  session. Gaps are permitted. Generated samples dropped by the simulator still
  consume a sequence number.
- `timestamp_ns`: nonnegative integer Unix timestamp in nanoseconds in ROS mode,
  at most `2^63-1`. Virtual nanoseconds from zero in the deterministic demo.
  Recording metadata only; it is not used to calculate arrival liveness.
- `latitude_deg`: finite number in [-90, 90], WGS 84 geodetic latitude.
- `longitude_deg`: finite number in [-180, 180], WGS 84 longitude.
- `heading_deg`: finite number in [0, 360), clockwise from true north.
- `speed_m_s`: finite number in [0, 100], metres per second. The upper bound is a
  version-1 application limit, not a physical claim about every robotic platform.
- `battery_pct`: finite number in [0, 100], percentage.

Booleans and strings are not accepted as numbers. NaN and Infinity are rejected.
The synthetic route, heading, speed, and battery are illustrative test signals;
they are not a physically consistent vessel dynamics or energy model.

Example:

```json
{"schema_version":1,"robot_id":"usv01","session_id":"boot_1","sequence":0,"timestamp_ns":0,"latitude_deg":34.67,"longitude_deg":33.04,"heading_deg":90.0,"speed_m_s":0.6,"battery_pct":85.0}
```

# Status payload

The observer emits `robot_id`, `state`, `age_s`, `accepted`, `rejected`,
`last_sequence`, and `last_rejection`.

`state` is WAITING, HEALTHY, or STALE. `age_s` and `last_sequence` are null before
the first accepted sample. Counters cover the monitor's lifetime. `last_rejection`
keeps the latest rejection reason even after recovery; it is null until the first
rejection. A status is an observation at publication time, not an enduring promise
that the source is alive.

Rejection reasons are `invalid_payload`, `unexpected_robot`,
`duplicate_or_out_of_order`, `retired_session`, or `session_limit`.

## Late samples

By default (`late_samples = reject`) a sample whose sequence is not above the
highest already accepted in its session is rejected as
`duplicate_or_out_of_order`, even if it is new and merely delayed.

With `late_samples = liveness` such a sample is **accepted** when its sequence
is within the last 256 of the highest and has not been seen before. It then
refreshes arrival recency, because it did arrive. It counts in `accepted`
(and in a separate `late_accepted` counter in evidence reports and the MAVLink
bridge summary), and `last_sequence` stays the highest. Repeats, samples too far
behind to check for repeats, and samples from retired sessions are still
rejected. The status payload fields are unchanged.

`HEALTHY` keeps its meaning under either policy: a valid sample has arrived
recently. Under jitter larger than the sample period, `reject` turns many fresh
samples into rejections; [VALIDATION.md](VALIDATION.md) has a measured
synthetic comparison of both policies. Choose
one policy per experiment, and compare or pool evidence reports only when
their `late_samples` values match.

Select it with `--late-samples liveness` on `replay`, `evidence` and
`mavlink_bridge`, or the `late_samples` parameter of the ROS `link_monitor`
node (`late_samples:=liveness` with `usv_demo.launch.py`).
