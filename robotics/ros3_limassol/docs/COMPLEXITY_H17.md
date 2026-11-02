# H17 — Single-Observation Tail Latency and Heap-Expiry Analysis

Date: 2026-11-02. Scope: synthetic, offline LinkMonitor ingestion only.
No physical Arduino/USB testing, no MAVLink link, no live ROS 2 graph,
no distributed network, no field trials, and no Raspberry Pi benchmark result
are claimed by this milestone.

## 1. Mathematical problem: amortized versus single-call cost

Let:

- `N` be the count of accepted observations;
- `B` be bounded input payload bytes (at most 4096 for schema v1);
- `W` be the late-sequence history window (max 65536 in LinkMonitor);
- `S` be the maximum number of distinct recorded sessions (max 4096).

The optional `late_samples=liveness` policy stores accepted sequences in
a Python set and binary min-heap. Each accepted sequence is inserted once
and removed by a later expiry (or cleared upon session rotation).

Thus the **total** heap work across `N` arrivals is
`O(N log(W+1))` under expected O(1) hash-table operations, so the
**amortized expected** ingestion time is `O(B + log(W+1))`.

However, a single message that advances the maximum sequence far enough
can expire all `W` retained entries at once. Consequently, that call's
upper bound is `O(B + W log(W+1))`, assuming expected hash operations.
A long stream's amortized bound does **not** imply a bounded per-message
latency or hard real-time deadline.

The default `late_samples=reject` policy never populates the late-sequence
set/heap and has expected `O(B)` ingestion, apart from bounded session
tracking, still without worst-case wall-clock guarantees.

## 2. Test method

The deterministic H17 regression suite:
1. Counts exact heappop operations on one forward sequence jump for
   several window sizes, independent of CPU timing.
2. Verifies the default rejection policy performs no heap operations.
3. Tests percentile calculation and benchmark validation boundaries.
4. Exercises the small synthetic benchmark and checks that it never
   asserts physical validation or deterministic execution times.

The accompanying benchmark:
1. Pre-fills an active session's late window with `W` observations.
2. Records `K` consecutive in-order ingest-call durations.
3. Records one further large forward sequence jump that expires `W` entries.
4. Repeats the experiment for each configured window and late policy.
5. Reports nearest-rank p50, p95, p99, baseline max, and jump-call time in
   microseconds, using medians across independent repeat trials.

JSON serialization is done **outside** the timed ingest call. Decoding and
validation are inside. Each probe is run on one receiver only, on a
synthetic monotonic clock, without waiting for wall-clock packet arrivals.

**Caution:** Python's `perf_counter_ns` is an elapsed-time observation.
Thread scheduling, memory allocation, cache state, thermal throttling and
platform configuration affect results. Percentiles are calculated from a
bounded sample, not a statistical confidence interval or certified deadline.

## 3. Reproducible commands

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h17_single_call.py' -v
python3 tools/benchmark_h17.py \
  --windows 8 64 256 --samples 256 --repeats 3 \
  > h17-synthetic-local.json
python3 -m json.tool h17-synthetic-local.json
```

For Raspberry Pi 3B, run these after synchronizing `main` on the device,
without any Arduino attached. Preserve the results as a new, dated artifact,
along with Python version and device temperature/CPU load if recorded.
GitHub runner results are not Pi results.

## 4. Acceptance and limitations

- CI core and ROS 2 matrix passes.
- The new regression tests pass in both supported Python environments.
- Actual heap removals are verified through operation counting, not inferred
  from timing ratios.
- The benchmark produces bounded, labelled, synthetic JSON measurements.
- No threshold is enforced for tail latency; no claims about hardware
  receiver responsiveness or closed-loop control are made.
- No production LinkMonitor code is changed by this milestone.

Further work should improve the data-structure choice only after real
latency requirements and target-system measurement evidence are available.

Related: [H13](COMPLEXITY_H13.md), [H14](COMPLEXITY_H14.md),
[H15](COMPLEXITY_H15.md), [H16](COMPLEXITY_H16.md).
