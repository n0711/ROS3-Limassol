# Validation record

## MAVLink bridge against ArduPilot Rover SITL (27 October 2026)

This is the first run of the receive-only MAVLink bridge against an autopilot
stack (issue #28). It followed the [SITL runbook](SITL.md) and used
`tools/udp_outage_relay.py` and `tools/compare_outages.py`.

**Setup.** ArduPilot `Rover-4.6.3` (commit
`3fc7011a7d3dc047cbb17d8bd98ee94577d144c6`), built with
`./waf configure --board sitl && ./waf rover`. It was started at the default
CMAC home (−35.363261, 149.165230) with the command the runbook gave at the
time, `sim_vehicle.py -v Rover --out udp:127.0.0.1:14550 --no-rebuild`. The
moving run added `--out udp:127.0.0.1:14560` for the driver. See the runbook
corrections below. MAVProxy 1.8.75 (pymavlink 2.4.50) ran at its
default 4 Hz stream rate, with `--mavproxy-args="--non-interactive"` because
the run was headless. The host was Ubuntu 24.04.5 with Python 3.13.17, and
everything ran on loopback. The bridge used its defaults: system ID 1,
`--stale-after 1.0`, `--tick 0.5`, `--battery-max-age 5.0`. The relay scheduled
outages at 30–35 s and 70–72 s after its first datagram, ran for 120 s, and
the bridge for 180 s.

There were two runs:
- **Stationary.**
- **Moving.** The rover was driven in `MANUAL` by RC overrides from a separate
  pymavlink script on a second MAVProxy output, with `ARMING_CHECK 0` in SITL.
  That script is outside this repository and outside the measured path; the
  relay and bridge sent nothing to the vehicle. Speed ranged 0–8.8 m/s and
  heading 0.6–358.9°.

| Run | Window (s) | Dropped | Arrival gap (s) | STALE after scheduled drop (s) | STALE − (last forwarded + 1.0 s) | STALE after last accepted sample (s) | HEALTHY after resume (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Stationary | 30–35 | 487 | 5.171 | 1.103 | 0.248 | 1.257 | 0.324 |
| Stationary | 70–72 | 194 | 2.174 | 1.104 | 0.197 | 1.206 | 0.083 |
| Moving | 30–35 | 487 | 5.164 | 1.093 | 0.229 | 1.239 | 0.324 |
| Moving | 70–72 | 195 | 2.161 | 1.093 | 0.221 | 1.232 | 0.085 |

**In both runs:**
- Each run had two STALE→HEALTHY recoveries, each matched to its window, with
  no unexplained STALE. A further STALE came after the relay stopped, as
  expected.
- No sample fell inside a window.
- Replay reproduced the live transitions: the same state sequence, with a
  maximum time difference of 0.24 ms (stationary) and 1.1 ms (moving).
- Clock alignment spread was 0.9 ms and 2.5 ms.
- Each run accepted 406 samples and rejected 0.
- The bridge received exactly the datagrams the relay forwarded: 10,057 and
  10,078.
- `crc_errors`, `bad_length`, `signed_skipped`, `heading_unknown`,
  `out_of_schema` and `other_source` were all 0. About 9,250 other MAVLink
  messages per run were counted as unsupported.

**Withheld samples, one per run each:**
- `battery_unknown`: the first `GLOBAL_POSITION_INT` arrived before the first
  `SYS_STATUS`. SITL reported a battery value from the first sample on, so −1
  was never seen.
- `battery_stale`: after the 5 s outage, the first position arrived before a
  new `SYS_STATUS`, and the last battery report was more than 5 s old. That is
  why `HEALTHY` returned 0.32 s after traffic resumed for the 5 s window, but
  0.08 s for the 2 s window.

**Position sanity check.** In each run the first six samples were (0, 0). They
were sent before the EKF origin existed and were accepted as valid schema-v1
telemetry, as [MAVLINK.md](MAVLINK.md) warns. After that, stationary positions
were 0.89–0.91 m from the SITL home and moving positions 0.2–8.3 m. Battery was
100 % when stationary and 100 → 77 % while moving. This is a sanity check of
the mapping, not a positioning claim.

**Finding: the default 1 Hz position stream sits on the default threshold.**
For the first 11 s of position data, before MAVProxy's stream request took
effect, `GLOBAL_POSITION_INT` arrived at 1 Hz, Rover's default `SRx_POSITION`.
Each run had 11 such gaps between 0.990 and 1.009 s, and 5–6 of them were above
the 1.0 s `--stale-after`. No false STALE occurred, but only because no 0.5 s
tick landed in the few milliseconds when the age exceeded 1.0 s. With a
sustained 1 Hz stream this would produce intermittent false STALE changes.
[MAVLINK.md](MAVLINK.md#choosing---stale-after) now says how to choose
`--stale-after`.

**Runbook corrections, now in [SITL.md](SITL.md):**
- `sim_vehicle.py` already passes `--out 127.0.0.1:14550`, so the runbook's
  extra `--out` sent every message twice. The relay forwarded only the first
  source and counted the copy (`other_sources` 10,738 and 10,760, equal to
  forwarded plus dropped), so the measurement was unaffected.
- "STALE − expected" uses the last forwarded datagram of any type. Here the
  last datagram came 8–11 ms after the last position, so the values fell
  between 0 and one tick. In general they can be negative by up to one
  position interval.

**Not established:**
- PX4 SITL, or any router or ground station other than MAVProxy.
- A companion computer, a radio or any physical link.
- Real network delay, jitter or loss: these outages were clean drops on
  loopback.
- MAVLink 2 signing, or more than one vehicle.
- Long runs: each run lasted about 3 minutes.
- Behaviour under a sustained 1 Hz stream.

Vehicle dynamics are SITL's model. This is simulation evidence, not field
validation, and says nothing about vehicle safety.

## Seeded link-impairment experiments (27 October 2026)

`impairment.py` adds a virtual-time, seeded link model (delay, jitter,
independent and Gilbert–Elliott burst loss, duplication, declared outages,
publisher restarts) for several robots, scored against the declared outages.
Its monitor counts come from `run_replay` over the same observations it can
write as recordings. Fourteen tests cover exact clean-link latencies, delay,
missed short outages, outages beginning while already STALE, burst-induced
unexplained STALE episodes, duplicate and jitter rejections, restart sessions,
per-robot independence, common random numbers, recording/evidence agreement,
the documented example and strict scenario validation. Local runs pass on
Python 3.11 and 3.13 under unittest and pytest.

The threshold sweep in [IMPAIRMENT.md](IMPAIRMENT.md) is a synthetic result.
It does not measure a network, DDS, radio or vehicle link.

## Receiver-only context alongside local VLM (27 October 2026)

The optional camera node now retains **one** recently delivered
`LinkStatus` and snapshots it as a camera frame callback is accepted.
A bounded configurable age limit rejects old status, a mismatched robot
ID is ignored, and the snapshot cannot be retroactively updated during
model inference. The frame report marks capture-time, source-clock,
physical robot identity and VERA-MOT track association unverified.
A new ROS-independent test suite covers staleness, absent status,
clock-regression errors, wrong robot ID and context immutability.
The ROS DDS graph test requires an independently delivered status before
a camera frame and checks the resulting read-only diagnostic context.

**Configured, not confirmed passed until CI reports completion.**
Passing CI is evidence only for synthetic message flow and same-process
receiver callback timing, not camera/sensor timestamp synchronization
or field performance.


## Local compressed-image VLM observer (introduced 26 October 2026)

This change adds an opt-in `sensor_msgs/msg/CompressedImage` ROS 2
subscriber, independent bounded JPEG/PNG validation, actual local Ollama
vision `/api/chat` request construction, and a separate read-only
`vlm_diagnostics` output topic. Python tests mock the model response and
exercise input-size, image-header, output-schema and CLI limits; ROS 2
tests exercise a DDS compressed-frame-to-diagnostic round trip using a
fake inference result. The optional ROS VLM launch is checked in Humble
and Jazzy CI, with `sensor_msgs` installed in both environments.

**Configured does not mean passed:** consult the specific GitHub Actions
run before claiming execution. Even successful CI does not verify a
vision model's accuracy, real camera throughput, synchronized multimodal
fusion, object-tracker agreement, physical hardware, or safety.
See [VLM.md](VLM.md).


## Local LLM diagnostic integration (introduced 26 October 2026)

`llm_diagnostics.py` makes a real local Ollama `/api/chat` request at
`127.0.0.1:11434`, with non-streaming JSON output, strict parsing, output
bounds and inference timeouts. CI uses a mocked response; no external model
is installed or run in CI. The ROS 2 `LLMDiagnosticNode` runs model calls
off the callback thread, publishes to `llm_diagnostics`, and has no actuator
publisher or tool-call interface. New tests cover bounded status filtering,
model request contracts, schema rejection, and a ROS topic round trip
with mocked inference.

**This documents configured checks, not passed results until a CI run is
observed.** Even when green, neither actual model accuracy, latency under
field load, field telemetry, autonomy nor safety is established. See
[LLM.md](LLM.md).


## Installed ROS package smoke check (configured 26 October 2026)

Both ROS CI jobs now invoke `tools/check_ros_quickstart.py` after building and
sourcing their respective Humble/Jazzy installations. This is a separate check
from the ROS graph unit tests. It starts in a temporary directory, asks the
`ros2` CLI to discover the installed node entry points, then runs the public
Python demo, replay, and evidence command-line interfaces. The script checks the
synthetic state transitions, accepted/rejected counts, recording observation
counts, and SHA-256 fingerprint. A nonzero result fails the CI job.

**Status:** this describes configured checks, not a verified pass. Refer to the
corresponding GitHub Actions job outcome before claiming success. It does not
measure DDS timing, network delay, sensor freshness, field reliability, or
vehicle safety. The source-tree unit tests and DDS graph tests are still required.


## Recording input validation follow-up, 25 October 2026

The local suite discovers 47 tests: 44 pass and three ROS integration tests are
skipped because `rclpy` is absent. New regression checks verify that invalid demo
options leave no output file, a corrected retry succeeds, and invalid UTF-8 on
the first or second recording line produces CLI exit status 2 with the correct
line number. The original deterministic experiment and record/replay equivalence
continue to pass. These results do not establish a new ROS or field execution.

Date: 24 October 2026. Package: ROS3-Limassol 0.3.1.

## Local implementation checks

- Python 3.12.14: 45 tests discovered; 42 passed and three ROS integration tests
  explicitly skipped because `rclpy` is absent locally.
- The virtual-time experiment reproduces WAITING at 0.0 seconds, HEALTHY at 0.0
  seconds, STALE at 2.9 seconds and HEALTHY at 5.0 seconds. Final counts: 51
  accepted, zero rejected.
- Recording captures 81 observation ticks, including 30 null ticks during the
  blackout. Replay reproduces every original event and final count.
- Tests cover changed replay timeouts, final silence, malformed telemetry,
  duplicates, wrong robots, retired sessions, schema errors, clock ordering,
  bounded input, CLI errors and file overwrite protection.
- Eleven new pure-Python live-recorder tests cover relative receiver time,
  independent silence, blackout/recovery replay, rejected-message preservation,
  timeout comparison, exclusive file creation, record-count bounds, flush/close
  behavior and invalid clocks/payloads.
- An offline wheel build and isolated installation passed. Record/replay from
  outside the source tree matched. The installed live writer also recorded a
  silent interval that replay classified STALE. The wheel includes the live
  recorder, ROS adapter, both launch files, manifest, marker, license and notice.
- Python source, package XML and workflow YAML parsing passed.

## ROS and CI

The local environment has no ROS installation or container engine. The
[workflow](https://github.com/n0711/ROS3-Limassol/actions/workflows/ros3-ci.yml)
defines Linux/Python 3.10 and 3.12, Windows/Python 3.12, installed-wheel checks and
a Jazzy package build with a DDS blackout/recovery test. A separate Humble job
uses Ubuntu 22.04, `ros:humble-ros-base` and its system Python 3.10. Both ROS jobs
build the package, inspect both launch files and run the same 45-test suite,
including the DDS recording/replay and parameter/file-protection cases.
Check each actual job
result; configuration alone does not establish that a platform passed.

The pre-change 0.2.0 main commit `764e1533e1903c04b0a50e02ab1eff41e20c593c`
[passed all four jobs](https://github.com/n0711/ROS3-Limassol/actions/runs/40036934415),
including Jazzy, on 23 October 2026 UTC (24 October in Cyprus).
This is historical evidence for that commit, not a recorder test result.

The 0.3.0 ROS suite adds a real DDS subscription-to-file-to-replay test. It waits
for received traffic before cancelling the publisher timer, checks STALE from
independent ticks, restores publication and checks HEALTHY recovery. Simulation
time is enabled without a `/clock` publisher to exercise the steady timer.
A separate ROS test checks invalid parameters and existing-file protection.
Local ROS execution remains unavailable; see the PR's actual Humble and Jazzy
job results. Adding a job is not itself a successful Humble execution.

The 0.3.0 recorder commit `ee71cdbbcbd6e8a718ec22d938bfd0f43f7ffaae`
[passed four CI jobs](https://github.com/n0711/ROS3-Limassol/actions/runs/40053034634)
on 24 October 2026. Jazzy reported 45 tests, zero errors, zero failures and zero
skips. That run predates the Humble job and is evidence for Jazzy only.

The first Humble run used Python 3.10.12 and built the package successfully,
but all three ROS integration tests failed when importing the Jazzy-only
`rclpy.clock_type` module. Version 0.3.1 uses the shared `rclpy.clock.ClockType`
export instead. The Humble job must pass the same integration tests; it does
not skip or relax them to accommodate the older distribution.

These checks use synthetic observations. Real vessel behavior, wireless timing,
synchronized capture age and field reliability remain unmeasured. The original
paper remains the historical 0.1.0 report.
