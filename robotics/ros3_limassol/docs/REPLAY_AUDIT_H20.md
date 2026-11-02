# H20 — Exact Synthetic Multi-Robot Recording and Replay Equivalence

Date: 2026-11-02. This milestone uses the existing production
`LinkMonitor`, `Observation`, `read_observations` and `run_replay` APIs
without modifying their behavior. It is **offline and synthetic only**.

## 1. Verification question

Does each receiver's version-1 JSONL recording reproduce **all** observed
`WAITING/HEALTHY/STALE` transitions and its final liveness/rejection
summary when processed through the independent replay entry point?

For each robot `r`, define:

```text
E_r = (e_0, e_1, ..., e_(T-1))
e_i = (receiver_time_i, raw_schema_v1_payload OR no payload)
```

Each `e_i` is serialized as one bounded `Observation` record.
A fresh `LinkMonitor` is fed the same events, taking a snapshot every
0.25 virtual seconds. Its emitted state transitions and summary are
compared for **exact equality** with `run_replay` of the serialized trace,
not just final counters.

This checks replay agreement for the finite tested sequences. Because
both paths intentionally use `LinkMonitor`, agreement is **not** an
independent correctness proof. The separately implemented H19 oracle
checks a different property.

## 2. Workload limits and identity safety

- Robot count: `1..16`.
- Ticks per robot: `16..256`.
- Policies: `reject` and/or `liveness`.
- Aggregate maximum: 8,192 synthetic robot-tick observations.
- Virtual monotonic time step: 0.25 seconds.
- Link stale threshold: 1.0 second.
- Each stream begins with a deterministic valid heartbeat to establish a
  healthy baseline before any scripted outage.

Synthetic events include six consecutive silent ticks every 24 ticks,
wrong-robot IDs, malformed packets, duplicates/out-of-order samples,
publisher restarts and retired sessions. All latitude, longitude,
heading, speed and battery fields are **placeholders**, not physical
measurements. None of the traces are radio, USB, ROS 2 DDS, MAVLink
transport or field data.

## 3. Reproducibility and integrity checks

Run from `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h20_replay_audit.py' -v

python3 tools/audit_replay_h20.py \
  --robots 4 --ticks 96 --seed 17 \
  --output-dir h20-synthetic-2026-11-02 > h20-summary.json
python3 -m json.tool h20-summary.json
```

The output directory **must not exist**. The tool writes new
`<robot_id>_<policy>.jsonl` files using exclusive creation and refuses
overwrites, preserving prior evidence by default. The summary has
SHA-256 digests and byte counts for every exact synthetic recording,
accepted/rejected counts and observed transition times. A digest
identifies bytes, not the origin or authenticity of a recording.

The script verifies all replay results **before creating** any output
directory. Files may still be partially written if a later filesystem
failure interrupts an export; a successful complete run and hash
recheck are necessary before treating an export as saved evidence.

To replay one synthetic recording manually:

```sh
python3 -m ros3_limassol.replay \
  h20-synthetic-2026-11-02/robot_001_reject.jsonl \
  --robot-id robot_001 --stale-after 1.0 --late-samples reject --json
```

These commands do not require connected Arduino devices or ROS.

## 4. Mathematical and memory bounds

Let `R` be robots, `T` observations per robot, `L` the maximum
recording-line length, `B` bounded payload size, `S` retained sessions,
and `W` late sequence window.

```text
Recorded payload storage in the in-memory audit: O(R*T*L)
Default expected processing: O(R*T*B)
Late-policy amortized expected processing: O(R*T*(B + log(W+1)))
Retained LinkMonitor state: O(R*(S+W))
```

`audit_replay_h20.py` uses `io.StringIO` for the bounded synthetic
recordings, so **this tool is not a constant-space replay benchmark**.
For constant auxiliary-memory streaming, use `run_replay` with a file
stream and consume results incrementally; storing a full list of replay
events adds output-proportional memory.

The bounds assume expected Python hash behavior. Real-time deadlines,
distributed throughput and physical availability have not been
established.

## 5. Acceptance and limitations

- Python 3.10/3.12 and ROS 2 CI matrix remains green.
- Every tested recording reproduces exactly the generated transitions
  and final summary; modified recordings fail comparison.
- Recorded timestamps are monotonic and the stream contains exactly
  `T` schema-v1 observation envelopes.
- Invalid CLI parameters are rejected without creating evidence.
- Exported traces and summary are explicitly labelled
  `synthetic_offline`.
- Raspberry Pi execution results remain **unmeasured** until a
  separately performed Pi benchmark is supplied.

Related milestones: [H13](COMPLEXITY_H13.md),
[H14](COMPLEXITY_H14.md), [H15](COMPLEXITY_H15.md),
[H16](COMPLEXITY_H16.md), [H17](COMPLEXITY_H17.md),
[H18](COMPLEXITY_H18.md), and
[H19 oracle](LIVENESS_ORACLE_H19.md).
