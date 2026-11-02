# H16 — Multi-robot receiver scaling (synthetic, offline)

Date: 2026-11-02. No new physical USB, UAV/USV/ROV, ROS 2 DDS, radio-link,
network or field validation was performed as part of H16. All telemetry
measurement fields in this experiment are placeholders.

## 1. Research question

For `R` **independent in-process LinkMonitor instances**, how do the
observed execution time and Python-tracked peak allocations vary with the
number of monitors, holding the number of receiver ticks per robot constant?

This is a standalone sequential dispatch experiment. It neither represents
actual concurrent robots nor measures DDS/network latency or fleet throughput.

Definitions:

- `R`: number of independent monitors (1..64 in this benchmark).
- `T`: snapshot epochs per robot (8..128).
- `B`: maximum telemetry JSON size (4096 bytes in the ROS3 schema).
- `W`: optional late-sample window (1..65536).
- `S`: maximum distinct publisher sessions per monitor (16 in H16).
- `A`: total accepted synthetic observations (at most `R*T`).

## 2. Complexity argument

Each receiver has one session set (size at most `S`) and optionally one
late-sequence set and heap (each size at most `W`). The H16 workload
additionally keeps `O(R)` counters, monitor references and identifiers.
It does **not** store all observations or snapshots.

```text
Persistent state:
M(R) = O(R*(S + W)) + O(R) = O(R*(S + W))

With default late policy:
T(R,T) = expected O(R*T*B)

With late tracking enabled:
T(R,T) = amortized expected O(R*T*(B + log(W+1)))
```

The time bounds include one telemetry-generation/validation path per
delivered message and one O(1) snapshot per receiver per epoch.
They use *expected* O(1) Python set operations, not deterministic
worst-case time. The late-window heap can expire `W` entries during one
sample, so individual ingestion latency is not constant.

Holding `T`, `S`, `W` and the payload bound `B` fixed makes
the theoretical growth **linear with R**. That does not imply a
real-time deadline or distributed scalability claim.

## 3. Experiment design

For every tick `epoch = 0..T-1`:

1. Every even-indexed monitor accepts its own schema-v1 heartbeat.
2. Every odd-indexed monitor skips epochs `4..7` modulo 16 (synthetic outage).
3. Every monitor gets a receiver-clock snapshot at the same epoch.
4. Its state is checked against the timestamp of its *own* last accepted
   observation using `stale_after_s = 2.0`.
5. A new synthetic publisher session begins every 16 epochs.

All messages are constructed with placeholder latitude, longitude, speed,
heading and battery. The benchmark validates state correctness while running
so a performance number cannot silently describe an incorrect state.

The clock is simulated and advanced explicitly. The benchmark is
not paced in real time. State transition observations occur only on
snapshot epochs.

## 4. Deterministic regression suite

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h16_multirobot.py' -v
```

Cases include:

- Eight independent robot monitors and a four-tick blackout: unaffected
  monitors remain HEALTHY; affected monitors become STALE and then recover.
- Repeated blackouts, including an outage at the final simulation epoch.
- Retained sets/heaps bounded by `R*S` and `R*W` for multiple robot counts.
- Unexpected robot IDs cannot refresh another receiver.
- CLI emits correct source/scope fields and rejects invalid or oversized runs.

These tests assert semantics and storage invariants, not wall-clock thresholds.

## 5. Reproducible benchmark

```sh
python3 tools/benchmark_h16.py \
  --robots 1 2 4 8 16 --ticks 24 --repeats 3 --window 32 \
  > h16-synthetic-local.json
python3 -m json.tool h16-synthetic-local.json
```

The JSON records platform/Python labels, workload parameters, median wall
time per workload, time per robot-tick, separate `tracemalloc` peak,
receiver-state validation counts, and number of retained session/sequence
entries. It contains no raw physical sensor data.

For consecutive fleet sizes `R_1` and `R_2`:

```text
empirical ratio = median_time(R_2) / median_time(R_1)
finite-size slope = log(ratio) / log(R_2/R_1)
```

A ratio near `R_2/R_1` and slope near 1 is *consistent* with
linear scaling for these finite experimental sizes, but does not prove
a Big-O bound. Measurements include synthetic JSON creation and validation.
Python's allocator, operating-system scheduling, CPU throttling and
background load affect measured timings. Tracemalloc excludes memory
allocated outside the Python-tracked allocator.

The command limits robot counts, ticks, repetitions and total work to
protect resource-limited targets (including a Raspberry Pi 3B). Run it
on the Pi **without Arduino boards connected** to obtain an actual
device-specific software baseline. Never present GitHub Actions runner
timings as Pi measurements.

## 6. Claims, decisions, and next milestone

Established by code review and deterministic tests (subject to CI):
- Independent in-process liveness states under synthetic outages.
- Retained state limits for configured session/late windows.
- Explicit expected and amortized Big-O assumptions for the monitored path.

Not established:
- Physical fleet, ROS 2 DDS graph, radio or network scaling.
- Raspberry Pi 3B execution-time or RSS measurements (until separately run).
- Deterministic worst-case execution time, real-time response deadlines,
  scheduling guarantees, field performance, or distributed autonomy.

**Next milestone H17:** Analyse per-operation latency distributions
under synthetic burst arrivals and large sequence jumps. Include
measurements separately from operation-count proofs and prohibit
hard real-time claims absent an independently verified scheduler bound.

Prior evidence: [H13 complexity](COMPLEXITY_H13.md),
[H14 amortized operation counts](COMPLEXITY_H14.md),
[H15 controlled benchmark comparisons](COMPLEXITY_H15.md),
and [H8-H10 USB validation](../../../docs/hardware/ARDUINO_USB_VALIDATION_2026-11-02.md).
