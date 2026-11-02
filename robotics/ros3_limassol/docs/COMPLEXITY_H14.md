# H14 — Deterministic amortized accounting and reproducible scaling evidence

Date: 2026-11-02. Scope: synthetic, offline tests for the receiver-side
`LinkMonitor` and recording/replay implementation. This work does **not**
run new USB hardware, radio, ROS 2 or field tests.

## 1. Complexity claim and assumptions

Let `N` be the number of arriving observations, `B` their maximum JSON
payload size, `W` the configured late-sequence window, `S` the retained
session limit, and `R` the number of separate monitors.

The current `LinkMonitor` uses a Python set and a min-heap for the optional
`late_samples=liveness` sequence window. Assuming *expected* O(1) hashing,
each accepted sample creates at most one heap entry. An entry can leave by
heap removal **once** or be cleared **once** during a session change. Thus,
over an entire run of `N` accepted samples:

```text
  number_of_heap_pushes <= N
  number_of_heap_pops <= number_of_heap_pushes
  number_of_cleared_entries <= number_of_heap_pushes
  each pushed entry exits by pop OR by clear, not both
```

Consequently, the total number of pushed/popped heap entries is O(N),
and heap work is O(N log(W+1)) on the accepted stream. Payload parsing adds
O(NB). Session clear work is O(N) in aggregate because the entries cleared
were previously inserted. Bounded retained state per monitor is O(S+W).

**Amortized expected ingestion**: O(B + log(W+1)) per observation.
**Single-call** expiry after a sequence jump: up to W removals, with an
O(B + W log(W+1)) safe upper bound assuming expected hash behavior.
**Default reject policy**: O(B) expected per ingestion with no late heap.
**R monitors**: O(R(S+W)) retained state.

These complexity estimates do not establish a deterministic worst-case
wall-clock bound: Python set operations have pathological worst cases and
scheduler/IO latency is not bounded. Replay input is bounded to 1,000,000
observations by the reader; `run_replay` only streams its output unless the
caller explicitly collects all yielded events.

## 2. Operation-count regression tests

Run from `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h14_operation_bounds.py' -v
```

The tests:

1. Count real `heapq.heappush`/`heapq.heappop` operations over 2,048
   in-order arrivals for window sizes 1, 2, 16, 64, 256.
   Expected: pushes = 2,048 and pops = 2,048 - W.
2. Trigger a forward sequence gap with W=64 to verify that one call can
   expire 64 entries, avoiding a false O(1) worst-case claim.
3. Verify a session change clears old late-window data and refuses the
   retired session.
4. Smoke-test the structured benchmark through a subprocess.

These tests assert data structure invariants and aggregate counts, **not**
execution-time thresholds. They deliberately know the current implementation;
an implementation change requires a renewed complexity argument.

## 3. Experimental runtime and memory probe

```sh
python3 tools/benchmark_h14.py \
  --sizes 1024 2048 4096 8192 --repeats 3 \
  > h14-synthetic-local.json
```

The generated JSON contains environment description, mode, observation
count, median elapsed seconds, seconds/observation, successive-size ratio,
finite-size logarithmic slope, and traced peak Python allocations.

For adjacent observations `N_1, N_2` and measurements `T_1, T_2`:

```text
ratio = T_2 / T_1
finite_size_log_slope = log(T_2/T_1) / log(N_2/N_1)
```

For a linear dominating term, the ratio approaches `N_2/N_1` and the slope
approaches 1. For O(N log N), the same finite-size slope can also look close
to 1, so **neither ratio nor slope proves Big-O**.

`benchmark_h14.py` reuses the end-to-end workload from `benchmark_h13.py`
(which includes synthetic payload construction). It does **not** isolate
`LinkMonitor.ingest` from JSON serialization overhead. Memory is measured
in a distinct instrumented run, because `tracemalloc` changes timings.
`tracemalloc` excludes allocations made outside Python's tracked allocator.
The tool caps maximum sizes, repeats and total input volume to make
accidental oversized runs less likely on a Raspberry Pi 3B.

For a Raspberry Pi 3B (once logged in, **no attached Arduinos required**):

```sh
cd ~/projects/ROS3-Limassol
git switch main
git pull --ff-only origin main
cd robotics/ros3_limassol
python3 -m unittest discover -s tests -v
python3 tools/benchmark_h14.py --sizes 1024 2048 4096 8192 --repeats 3 \
  > ~/h14-pi3b-synthetic.json
```

Output from the Raspberry Pi must be collected **before** claims about
that device's measured execution time or memory consumption can be made.
The GitHub Actions runs provide a separate CI environment, not Pi metrics.

## 4. Acceptance and scope

- PASS when new deterministic tests pass on supported Python platforms.
- PASS when `benchmark_h14.py` emits valid structured output under a
  small smoke-test workload.
- No timing, slope, memory-usage, physical-recovery or field-performance
  thresholds are silently asserted.
- Later work should compare repeated Pi measurements and consider profiling
  only if real performance constraints or regressions justify changes.

See `COMPLEXITY_H13.md` for the full prior source-level analysis and
`../../../docs/hardware/ARDUINO_USB_VALIDATION_2026-11-02.md` for the
earlier, separately reported H8-H10 USB experiment.
