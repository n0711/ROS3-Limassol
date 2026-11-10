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

## H22 acquisition and review procedure (pending hardware)

1. Record the camera and receiver models, firmware, driver, timestamp API,
   clock IDs, tick units, resolution and timestamp origin for each session.
   Identify whether the camera stamps exposure start, end or driver delivery.
   Specify the physical event whose age is being tested.
2. Use a common observable edge independently latched in both clock domains.
   Record the source and receiver edge timestamps, a shared edge ID, and the
   measured or specified bounds on differential path delay, latch latency and
   quantization. If either clock cannot observe the reference, stop the run.
   A camera timestamp paired with its arrival callback includes transport
   delay and cannot serve as this reference.
3. Start at least three independent acquisition sessions. Within each, label
   calibration and later held-out edge IDs before fitting. Use the first
   calibration edge difference (receiver minus source) as the offset at the
   reference epoch. Declare initial uncertainty, drift bound, validity duration
   and their evidence before examining held-out edges. Keep the operating
   conditions and duration with the results.
4. For each held-out edge compute the reference difference and its independent
   uncertainty u (seconds). At elapsed time t, compare the reference interval
   [difference - u, difference + u] with the H21 offset interval
   [theta - epsilon(t), theta + epsilon(t)]. Record full containment,
   disjoint intervals (a definite violation), or partial overlap (unresolved).
   Report per-session counts, largest excess beyond the declared interval,
   and the offending edge IDs. Keep all observations, including failures.
5. A clock-edge result alone covers only the clock mapping. To claim
   exposure-to-callback age, also bound the displacement between the camera
   stamp and the declared exposure event, plus any conversion to the callback
   clock. Document where buffering occurs relative to those timestamps.
   Leave unsupported capture paths out of the claim.
6. Mark the session unusable for age inference on missing calibration,
   unknown clock IDs, a clock reset, invalid bounds or expiry. The acquisition
   caller must check validity before supplying H21 calibration. Link HEALTHY
   describes receiver arrival recency only.
7. Archive raw edge pairs, split labels, calibration metadata, uncertainty
   budget, analysis script and per-edge output. Record the analysis command,
   repository revision and SHA-256 checksums of the archived inputs and script.
   Submit the evidence for independent review under issue #77.
