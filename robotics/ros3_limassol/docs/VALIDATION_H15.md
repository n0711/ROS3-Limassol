# H15 — Three-stream synthetic isolation and replay metamorphic checks

Date: 2026-11-02. These checks run **entirely offline** through the existing
`ros3_limassol.impairment` virtual-time implementation. The names `nano`
and `mega` identify synthetic sources; no Arduino is connected. `rover`
is a third synthetic source, **not** a third vehicle in SITL.

## Objective

Check *metamorphic properties* of a seeded multi-source experiment rather
than asserting a particular stochastic metric. A property remains meaningful
even when the absolute loss/reorder counts change across seeds.

For a three-source report function `F(seed, models, policy)`, let `F_r`
return only the report for source `r`.

**Isolation under independent fault injection:**

```text
F_nano(seed, [nano, mega, rover], policy)
  == F_nano(seed, [nano, mega_with_outage, rover], policy)

F_rover(seed, [nano, mega, rover], policy)
  == F_rover(seed, [nano, mega_with_outage, rover], policy)
```

These equalities are expected because the simulated link fate draws are
seeded independently per robot ID, with no shared-link contention model.
They would **not** be a valid expectation for a real shared radio.

**Permutation invariance:** Reordering the independent robot definitions
must not change each robot's report once indexed by robot ID.

**Recording/replay agreement:** For each source, replaying its recorded
receiver observations with the same stale threshold and late-sample policy
must yield the same accepted/rejected counts and final liveness state.

## How to run

From `robotics/ros3_limassol`:

```sh
python3 -m unittest discover -s tests -p 'test_h15_three_stream_isolation.py' -v
python3 -m unittest discover -s tests -v
```

The regression suite exercises both `reject` and `liveness` policies,
seed variations, deterministic link delay/jitter/loss/duplication/restarts,
a Mega-only injected outage, and exact replay agreement. A separate
clean-link control checks that unaffected neighbors do not go stale.

## Scope and limitations

- Virtual-time observations are **synthetic** and reproducible.
- Per-robot independent random streams do not model shared-medium
  interference, simultaneous network saturation or radio contention.
- A passing test does not measure detection latency on physical USB or
  prove a fleet-scale complexity bound.
- Issue #41's **three-vehicle SITL validation remains separate and
  incomplete** unless independently supported by its own recorded
  evidence and repository status.
- No vehicle commands, physical transport, ROS 2 graph tests or field
  validation are performed by H15.

H8-H10 physical USB evidence remains in the repository's
`docs/hardware/ARDUINO_USB_VALIDATION_2026-11-02.md`.
H13-H14 computational bounds remain separately documented in
`COMPLEXITY_H13.md` and `COMPLEXITY_H14.md`.
