# H13: computational bounds and offline scaling protocol

Date: 2026-11-02. Scope: standalone Python `LinkMonitor`, recording reader,
`run_replay`, and **synthetic** Arduino-like dual-source monitoring. This is
not a physical USB, radio, ROS 2 transport, or field-performance benchmark.

## Parameters and assumptions

- `N`: number of observations processed; `R`: independently monitored robots.
- `B`: telemetry payload bytes, at most 4,096; `L`: recording-line bytes,
  at most 32,768; `N` is limited to 1,000,000 per recording reader.
- `S`: retained session identities per monitor, `1 <= S <= 4,096`.
- `W`: late-sample sequence window, `1 <= W <= 65,536`.
- Set membership/insertion/deletion is **expected** O(1), not a deterministic
  upper bound for arbitrary Python hash-table behavior. Heap operations take
  O(log(W + 1)) worst-case per push/pop.
- We count Python-level operations, not hard real-time CPU deadlines; payload
  construction, allocator behavior, IO and thread scheduling are not bounded
  in wall-clock time by this analysis.

## Operation bounds

| Operation | Time | Retained/working space | Conditions |
| --- | --- | --- | --- |
| Decode/validate one telemetry message | O(B) | O(B) | bounded JSON input |
| Snapshot one monitor | O(1) | O(1) | monotonic receiver clock |
| Ingest, default `late_samples=reject` | expected O(B) | O(B) transient | set membership expected O(1) |
| Ingest, late-sample mode | amortized expected O(B + log(W + 1)) | O(B + W) | can expire many heap entries on one call |
| Switch publisher session | expected O(B + W) | O(S + W) retained | clears previous late window |
| Stream N observations through replay | amortized expected O(N(L + log(W + 1))) | O(L + S + W) | consumer does not retain all yielded events |
| R independent active monitors | per snapshot sweep O(R) | O(R(S + W)) | excludes IO and message buffers |

One late-mode ingestion can trigger removal of up to `W` heap entries after
an abrupt sequence-number jump, so **single-call** time can be
O(B + W log(W + 1)) assuming expected O(1) hash operations. Switching
sessions also clears O(W) state. Over the entire stream, each heap entry is
added once and removed at most once (or cleared once on session rotation),
which gives the amortized expected bound above. Python set collisions and
interpreter scheduling prevent deterministic worst-case guarantees.

With **default** late rejection, the recent-sequence heap/set stay empty.
Across `R` monitors, the retained session identifiers take O(R*S) space,
and late-mode sequence tracking takes O(R*W) additional space. The recording
reader iterates bounded lines; an external `list(run_replay(...))` caller
would instead allocate O(N) output storage.

## Liveness threshold is not a scheduling guarantee

For most recent accepted receiver time `t_last` and current receiver time `t`:

`age = t - t_last`; `HEALTHY` iff `age < stale_after_s`, else `STALE`.

`LinkMonitor.snapshot()` is O(1), but a transition is **observed** only when
`snapshot()` is called. If a separate scheduler can establish a maximum
snapshot gap `delta`, observation occurs no earlier than the threshold and
no later than `threshold + delta` under that scheduler assumption. The
repository has not established a hard maximum `delta`, so no deterministic
real-time detection bound is claimed. Sender timestamps do not control
liveness, and only accepted observations refresh it.

## Reproducible checks

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q ros3_limassol tests tools
python3 tools/benchmark_h13.py --sizes 2000 4000 8000 16000 --repeats 3
```

The H13 unittest module checks two-source isolation during repeated simulated
outages, bounded late-window state, session-cap behavior, and lazy recording
replay. It does **not** benchmark serial devices.

The benchmark executes default ingest, late-mode ingest and streamed replay.
It prints medians, per-message times, doubling ratios and separately measured
`tracemalloc` peak memory. A measured `T(2N)/T(N)` near 2 is consistent with
linear scaling but **does not prove** a Big-O upper bound; timings are noisy,
small samples have overhead, and `tracemalloc` does not measure all process
memory. Benchmark output is diagnostic: CI should never reject a change based
on absolute timing or an empirical ratio without a controlled environment.

## Evidence status

- Source-level complexity bounds: reasoned from the specified data structures.
- Deterministic state-invariant tests: added in H13, execution must be checked
  in the repository CI and on the target machine.
- Hardware H8-H10 evidence: separately reported in
  `docs/hardware/ARDUINO_USB_VALIDATION_2026-11-02.md`.
- No new physical test, measurement, radio-link validation or real-time
  deadline claim is implied by this document.
