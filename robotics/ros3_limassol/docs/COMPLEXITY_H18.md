# H18 — Experimental Bounded Ring for Late-Packet Sequence Tracking

Date: 2026-11-02. **Experimental tools only:** the repository's production
`LinkMonitor`, ROS 2 nodes, telemetry format, default `late_samples=reject`
policy, receiver clocks and recording/replay behavior are unchanged.

## 1. Motivation

The optional production `late_samples=liveness` tracker uses a Python
set and a min-heap of up to `W` recent accepted sequences. Its aggregate
heap work is amortized `O(N log(W+1))`, but a single forward sequence jump
can expire up to `W` entries (conservative upper bound
`O(W log(W+1))` heap work for that call).

We investigate a *different sequence-memory data structure* which needs no
per-observation sweep of expired entries:

```text
For a sender sequence number q and a window size W:
slot = q mod W
ring[slot] = (generation, q)
```

`generation` changes when an accepted publisher session changes. This
allows the old session's slots to be logically retired in constant time
without clearing all `W` slots. Two distinct sequences inside the same
interval of `W` integers cannot share the same remainder modulo `W`.
An exact full-sequence match therefore distinguishes a previously seen
accepted packet from an unseen late packet in that interval.

## 2. Algorithmic argument

Let `q_max` be the highest accepted sequence in the active session.
A late sequence `q` may be accepted iff:

```text
q <= q_max
q_max - q < W
ring[q mod W] != (current_generation, q)
```

The inherited monitor retains all other rules, including strict JSON
validation, receiver-clock monotonicity, unexpected-robot rejection,
session limits and retired-session rejection.

The ring alternative uses:

- `O(W)` memory and initialization per monitor when late mode is enabled.
- `O(1)` ring-index calculation, slot compare and slot write for every
  accepted sequence (fixed bounded 64-bit sequence integers).
- `O(1)` logical reset of the ring on an accepted session change.

In contrast, the current heap needs `O(W log(W+1))` operations to expire
a large window in one arrival. **Only the late-sequence bookkeeping
has a deterministic constant-operation count.** Whole-payload JSON parsing
and Python session sets still follow their own bounds and assumptions.
Neither implementation provides a hard real-time execution guarantee.

An intentionally dense `W`-slot ring can use *more* memory than the
heap/set when only a few sequences have been received. It also touches
`O(W)` memory at monitor initialization. Consequently, this is an
experimental engineering tradeoff, not an unconditional optimization.

## 3. Correctness verification

`tests/test_h18_ring_equivalence.py` compares `RingLinkMonitor`
against the unmodified production `LinkMonitor` using deterministic
seeded streams, with all of the following:

- In-order, out-of-order, duplicate and missing observations.
- Large forward jumps and sequence wrap of the ring index.
- Publisher restarts, retired sessions and configured session limit.
- Malformed JSON and a message belonging to a different robot.
- Strictly increasing receiver timestamps and cross-checks of
  `LinkStatus` and `late_accepted` at every step.
- Exact bounded ring slot count and a test forbidding heap push/pop
  calls in the experimental subclass.

This is a *tested equivalence claim over those cases*, not a formal
verification of every possible input. The subclass deliberately inherits
the existing monitor's non-sequence logic and overrides only the two
late-sequence methods `_is_unseen_late` and `_remember`.

## 4. Reproducible synthetic evaluation

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h18_ring_equivalence.py' -v

python3 tools/benchmark_ring_h18.py \
  --windows 8 32 128 512 --samples 1024 --repeats 3 \
  > h18-experimental-ring.json
python3 -m json.tool h18-experimental-ring.json
```

The benchmark runs both implementations on identical prebuilt JSON frames,
including periodic large sequence jumps and delayed/duplicate samples.
It asserts equality of accepted/rejected totals, last sequence, rejection
reason, late-acceptance count and accepted-index checksum. It separately
measures wall-time medians and Python-tracked peak memory. The prebuilt
trace is excluded from the measured heap snapshot.

**No fixed speedup is promised.** Observed timings include JSON parsing
and Python overhead, are noisy, and cannot prove deterministic
wall-clock bounds. H18 benchmark results in GitHub Actions are not
measurements from the Raspberry Pi 3B or other physical target hardware.

## 5. Decision gate before production changes

Do **not** replace the production heap until:
1. CI passes on supported Python versions and ROS 2 distributions.
2. Edge cases and expected acceptance/rejection semantics are reviewed.
3. The fixed `O(W)` allocation tradeoff is measured on a resource-limited
   target and compared to the existing heap/set under realistic traffic.
4. Existing H13/H14 white-box heap assertions are updated in a separately
   reviewed migration without weakening their underlying proof obligations.
5. Replaying older recordings yields identical transitions under both
   policies, and the decision is recorded.

This milestone does not validate radio, USB, physical links, DDS, live
autonomy, real-time deadlines, or field robustness.

Related: [H13](COMPLEXITY_H13.md), [H14](COMPLEXITY_H14.md),
[H17](COMPLEXITY_H17.md).
