# H19 — Seeded Differential Liveness and Session-State Verification

Date: 2026-11-02. H19 is an **offline, synthetic test milestone** for
`ros3_limassol.monitor.LinkMonitor`. No hardware or live network is needed.

## 1. Research question

Can an independent, specification-style reference automaton reproduce
the current monitor's acceptance decisions, counters, session history,
sliding late-sample window and receiver-clock liveness states across
thousands of deterministic interleaved multi-robot events?

This is **differential testing**, not exhaustive model checking or a
formal proof of correct behavior for every possible sequence.

## 2. State transition model

For robot `r`, define state:

```text
X_r = (session, seen_sessions, highest_sequence, seen_recent_sequences,
       last_accepted_receiver_time, accepted, rejected, last_rejection)
```

At receiver time `t`, telemetry is accepted if:

- The payload is valid and intended for robot `r`.
- Its session is current, with a higher sequence; or
- Late-sample liveness is enabled and its lower sequence lies in the
  `W`-sized interval below the highest sequence and is unseen; or
- It starts a previously unseen session while the session-history cap permits.

Invalid, unexpected-robot, duplicate/out-of-order, retired-session, and
session-limit observations are rejected and do **not** update liveness.

Receiver liveness follows:

```text
state(r,t) =
  WAITING, if no observation was accepted
  HEALTHY, if t - last_accepted_time < stale_after_s
  STALE,   otherwise
```

The H19 oracle deliberately **does not use** `LinkMonitor._remember()`,
its binary heap or its ingestion code. Instead, it maintains a reference
sequence set and filters it explicitly after an accepted observation.
This reduces the chance of a shared implementation bug, although both
implementations still follow the same intended specification.

## 3. Deterministic test strategy

`tools/audit_h19.py` generates receiver events using a local seeded
pseudo-random generator, with explicitly bounded sizes:

- `1 <= robots <= 32`
- `8 <= ticks <= 384`
- `0 <= seed <= 2^31-1`
- Up to 20,000 total robot-tick checks across requested policies
- `max_sessions=4`, `late_window=16`, `stale_after_s=1.0`

The generated event stream includes losses (no observation), messages
from unexpected robot IDs, malformed JSON, duplicates, reordered
sequences, new publisher sessions and returns to retired sessions.
Every robot receives an independent `LinkMonitor` and independent
reference oracle. All clocks advance monotonically in deterministic
0.25-second increments. All position, speed, heading and battery values
are placeholders; they are **not sensor measurements**.

After each tick, the test compares the live state with the reference:
state, age, acceptance and rejection counters, highest sequence,
last rejection reason, and the bounded late-sample set. The test
fails on the **first observed mismatch**. It checks the `R*S` session
and `R*W` late-window storage bounds on every tick.

A SHA-256 digest fingerprints the generated trace and observed states,
allowing exact reproduction from its seed/settings. This is *not*
a cryptographic attestation of a physical experiment.

## 4. Mathematical complexity

Let `R` be monitored robots, `T` ticks per robot, `B` the bounded
payload size, `S` max sessions and `W` late window size.

Production monitor, default rejection policy:

```text
Expected total time: O(R*T*B)
```

Production monitor, late-liveness policy:

```text
Expected amortized total time: O(R*T*(B + log(W+1)))
Retained monitor state: O(R*(S + W))
```

The **reference oracle** uses a different, deliberately less efficient
implementation: after an accepted sample it explicitly filters up to
`W` retained sequence identifiers, hence up to `O(W)` reference
work per such update. This is a test oracle, not a production replacement.

The event generator creates and processes one packet at a time rather
than storing a full `R*T` trace. Counters, monitors and SHA digest
therefore use memory proportional to bounded per-robot state,
`O(R*(S+W))`, excluding Python runtime and temporary JSON buffers.

Assumptions include expected Python hash-table behavior. Neither
algorithmic reasoning nor seeded tests establish deterministic worst-case
wall-clock execution time, distributed throughput or a scheduling deadline.

## 5. Execution

From `robotics/ros3_limassol`:

```bash
python3 -m unittest discover -s tests -p 'test_h19_liveness_oracle.py' -v
python3 tools/audit_h19.py --robots 8 --ticks 192 --seed 17 > h19-seed17.json
python3 -m json.tool h19-seed17.json
```

The regression module also runs the same interleavings under both policies,
multiple robot counts, and independent seeds, plus explicit session/late
boundary checks and malformed CLI input rejection. No external dependencies
or ROS installation are required for these offline tests.

## 6. Interpretation and limitations

What passing results establish: for the *tested finite event sequences*,
the production state machine matches the separate reference specification,
including receiver-time liveness and session-history boundaries.

What they do **not** establish:

- Correctness for every possible input sequence.
- Memory safety or worst-case execution time guarantees.
- ROS 2 DDS, radio, MAVLink transport or simultaneous fleet performance.
- Raspberry Pi-specific timings, unless independently measured on that Pi.
- Physical field or vehicle autonomy validation.

Next proposed milestone (after H19), H20: **replay equivalence with seeded multi-robot
interleavings and audit-preserving synthetic JSONL traces**, while keeping
real USB observations and synthetic recordings strictly separated.

Related: [H13](COMPLEXITY_H13.md), [H14](COMPLEXITY_H14.md),
[H15](COMPLEXITY_H15.md), [H16](COMPLEXITY_H16.md),
[H17](COMPLEXITY_H17.md), [H18](COMPLEXITY_H18.md), and separately reported
[H8-H10 physical USB experiments](../../../docs/hardware/ARDUINO_USB_VALIDATION_2026-11-02.md).
