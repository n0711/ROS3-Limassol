# H21: offline source-to-receiver clock bounds

**Status: 13 focused unittest checks passed in a Python 3.13.5 local staging
environment on 2026-11-07.** GitHub core and ROS Humble/Jazzy CI also passed
([run 42403210258](https://github.com/n0711/ROS3-Limassol/actions/runs/42403210258));
the separate Rust workflow passed
([run 42403210271](https://github.com/n0711/ROS3-Limassol/actions/runs/42403210271)).
Hardware verification remains unavailable.

The read-only `ros3_limassol.clock_bounds` module propagates an *externally
declared* clock offset and its uncertainty to a conditional range of ages from
sensor capture to receiver callback. It does not measure the offset, synchronize
clocks, verify exposure timestamps, estimate pose, or authorize vehicle commands.
The existing ROS 2 node and `ReceiverObservationContext` remain unchanged.

## Clock and error model

Let:

- `c`: capture timestamp in seconds from a continuous source monotonic clock
- `r`: callback timestamp in seconds from a continuous receiver monotonic clock
- `theta`: receiver-clock-minus-source-clock offset estimate in seconds
- `epsilon_0`: independently bounded initial offset uncertainty
- `d`: nonnegative absolute drift bound in parts per million
- `t`: elapsed seconds since the offset was characterized

Then `epsilon = epsilon_0 + d*t/1_000_000`. Assuming the true offset is in
`[theta-epsilon, theta+epsilon]`, possible nonnegative capture-to-callback
ages are the intersection of

`[r-c-theta-epsilon, r-c-theta+epsilon]` with `[0, +infinity)`.

With a declared upper freshness threshold `L`, the five outcomes are:

- `within_declared_bound`: every possible physical age is at most `L`
- `outside_declared_bound`: every possible physical age exceeds `L`
- `indeterminate`: the age interval crosses `L`
- `inconsistent_clock_bound`: even the greatest possible age is negative
- `calibration_unavailable`: offset/calibration absent, no age inferred

These labels are conditional on the user-supplied clock assumptions. The module
always emits `alignment_verified: false` and `navigation_authority: false`.

## Reproducible synthetic example

From `robotics/ros3_limassol/`:

```sh
cat > /tmp/ros3-h21.json <<'JSON'
{
  "schema_version": 1,
  "freshness_limit_s": 0.3,
  "calibration": {
    "offset_s": 0.2,
    "uncertainty_s": 0.01,
    "drift_ppm": 100,
    "elapsed_s": 10
  },
  "samples": [
    {"sample_id": "camera.1", "capture_time_s": 10.0, "receive_time_s": 10.4},
    {"sample_id": "camera.2", "capture_time_s": 10.5, "receive_time_s": 11.0}
  ]
}
JSON
python -m ros3_limassol.clock_bounds /tmp/ros3-h21.json
python -m unittest discover -s tests -p 'test_clock_bounds.py' -v
```

The declared error is `0.011 s`. `camera.1` yields a conditional
`[0.189, 0.211] s` interval within the `0.3 s` threshold. `camera.2`
yields `[0.289, 0.311] s`, therefore `indeterminate`. These are
constructed timestamps, **not real-device or measured synchronization results**.

## Constraints and validation limits

- JSON input is bounded to 65,536 bytes, with 1-128 observations.
- Unknown or duplicate JSON keys, repeated sample IDs, wrong versions, invalid
  numeric values and receiver timestamps going backwards are rejected.
- Input clock offset, uncertainty, drift and capture timestamp provenance are
  declarations, not independently verified measurements.
- Driver buffering, exposure timestamp error, timestamp-conversion uncertainty,
  asymmetry, drift-model errors and malicious inputs can invalidate the
  declared bound. They must be accounted for before making physical claims.
- H21 has no changes to current telemetry, MAVLink, DDS, ROS 2 monitoring,
  recording schemas, or vehicle actuation.

**H22 exit gate:** independently measure source/receiver clock offsets on the
target camera/companion, bound measurement error and drift, check repeated
held-out timestamp pairs against that bound, and report measured failure cases.
Do not mark synchronization verified without this evidence.
