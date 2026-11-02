# H19 — Bounded Exhaustive Equivalence for the Experimental Late Ring

Date: 2026-11-02. Scope: deterministic synthetic receiver observations and
the optional `RingLinkMonitor` experiment from H18. Production
`ros3_limassol.monitor.LinkMonitor` is unchanged.

## 1. The verification problem

H18 showed seeded equivalence between the ring prototype and the current
late-window heap under a selection of traces. H19 explores **every**
length-`D` event sequence over a *fixed finite event alphabet*, comparing
the reference and experiment after every receiver observation.

This is exhaustive for the declared finite test domain, **not a proof of
equivalence for all 64-bit sequence values, all payloads or all timings.**

Ten possible events form the alphabet:

- Receiver silence (no packet).
- Malformed JSON input.
- Valid JSON for another robot.
- Session `b0` sequences 0, 1, 3, and 10.
- Session `b1` sequences 0 and 1.
- Session `b2` sequence 0 (exceeds configured 2-session limit in traces
  that have already accepted `b0` and `b1`).

The receiver time is fixed at `step*0.5` seconds; threshold is 0.75
seconds, and the retained-session limit is 2. For each word the test checks
that both implementations return identical accept/reject results, then
checks `LinkStatus`, `late_accepted`, final state and ring allocation size.

## 2. Number of test scenarios

With alphabet size `A=10`, depth `D=4`, and `K=3` late-window sizes
`W in {1,2,4}`, the number of full input traces is:

```text
Q = K * A**D
  = 3 * 10**4
  = 30,000 complete traces
```

The number of intermediate state-step comparisons is:

```text
C = D * Q = 120,000 receiver-state steps
```

Many paths contain silence and therefore fewer than 120,000 actual
packet ingestions; the tool reports this separately.

The harness enumerates events lazily with `itertools.product`, so it does
not store all `A**D` event sequences in RAM. Each trace creates a fresh
pair of monitors, then checks the entire bounded trace. A safety budget
limits the requested cases to 200,000 state transitions.

## 3. Mathematical ring-index invariant

Within a window of `W` consecutive sequence integers,
`q, q+1, ..., q+W-1`, all residues modulo `W` are unique:

```text
(q+i) mod W = (q+j) mod W
=> W divides (i-j)
and 0 <= i,j < W
=> i=j.
```

This justifies why a ring slot can represent a unique sequence in the
active late-acceptance interval. The generation tag prevents a previous
publisher session's old slot values from appearing as accepted sequences
in the new session. H19 checks the modular injection property for many
window sizes and starting sequences as a regression invariant.

## 4. Commands (software only, no Arduino required)

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h19_exhaustive_ring.py' -v
python3 tools/exhaustive_ring_h19.py --depth 4 --windows 1 2 4 \
  > h19-bounded-equivalence.json
python3 -m json.tool h19-bounded-equivalence.json
```

The JSON reports alphabet, depth, window sizes, traces checked,
state checks, processed payloads, and the claim boundary.

## 5. Interpretation and production decision

Passing every enumerated trace strengthens confidence that the two
late-window representations behave identically over the declared finite
domain. It is not a complete model-checker proof of all states or a
symbolic proof over arbitrary sequences. This study also does not establish
a hard real-time bound, wireless-network scaling or field reliability.

Do **not** migrate the production tracker without target-device memory
measurements, a design review of the O(W) initial allocation tradeoff,
recording/replay conformance checks and a separate migration PR updating
the H13/H14 heap-specific regression tests. Physical USB testing remains
stopped.

Related: [H18](COMPLEXITY_H18.md), [H17](COMPLEXITY_H17.md).
