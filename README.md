# ROS3-Limassol

**Telemetry arrival monitoring for robots with intermittent connections.**

ROS3-Limassol watches whether telemetry is still arriving at a receiver. It
reports when a link goes silent and when it recovers, records what the receiver
observed, and replays those recordings offline to the same result.

It is an experimental OpenPELAOS research prototype. **It is not ROS 3, an
official ROS distribution, or a replacement for ROS 2.** ROS 2 integration is
optional.

## What it does

A robot sends telemetry; the receiver validates each message and reports one of
three states:

| State | Meaning |
| --- | --- |
| `WAITING` | No valid telemetry has arrived yet. |
| `HEALTHY` | Valid telemetry has arrived within the timeout. |
| `STALE` | No valid telemetry has arrived within the timeout. |

**`HEALTHY` means only that valid telemetry arrived recently.** It says nothing
about vehicle safety, sensor freshness, navigation accuracy, network latency or
delivery reliability. ROS3-Limassol never sends commands to a vehicle.

## Quick start (no ROS needed)

Requires Python 3.10 or newer; the core uses only the standard library.

```bash
git clone https://github.com/n0711/ROS3-Limassol.git
cd ROS3-Limassol/robotics/ros3_limassol
python -m ros3_limassol.demo
```

Use `python3` on some Linux systems and `py -3` on Windows. The demo runs on
virtual time and finishes immediately:

```text
t= 0.0s  WAITING
t= 0.0s  HEALTHY
t= 2.9s  STALE
t= 5.0s  HEALTHY
Accepted: 51; rejected: 0
```

The simulated link drops out from 2 s to 5 s. The last message before the
dropout arrives at 1.9 s, so with the 1 s timeout the monitor reports `STALE` at
2.9 s, and `HEALTHY` again when messages resume at 5 s.

## Where to go next

| I want to… | Start here |
| --- | --- |
| Record, replay and export evidence | [Below](#record-replay-and-export-evidence) |
| Use it with ROS 2 Humble or Jazzy | [ROS package guide](robotics/ros3_limassol/README.md) |
| Watch a MAVLink autopilot without ROS | [MAVLink guide](robotics/ros3_limassol/docs/MAVLINK.md) |
| Test a timeout against delay, jitter and loss | [Link-impairment experiments](robotics/ros3_limassol/docs/IMPAIRMENT.md) |
| Reproduce the ArduPilot simulation check | [SITL runbook](robotics/ros3_limassol/docs/SITL.md) |
| Know what has and has not been validated | [Validation record](robotics/ros3_limassol/docs/VALIDATION.md) |
| Understand the design | [Architecture](robotics/ros3_limassol/docs/ARCHITECTURE.md) |
| Find any other document | [Documentation map](robotics/ros3_limassol/docs/README.md) |

## Status at a glance

| Part | What has been checked | Not established |
| --- | --- | --- |
| Monitor, telemetry validation, recording, replay, evidence (Python) | Unit tests in CI on Ubuntu (Python 3.10, 3.12) and Windows (3.12) | Timing over a real network |
| ROS 2 adapter: simulator, monitor, recorder | DDS graph tests in the Humble and Jazzy CI jobs | Multi-host or field DDS |
| Receive-only MAVLink bridge | Independently encoded frames; ArduPilot Rover 4.6.3 SITL on one host with scripted outages | PX4, radio links, companion computers, signed MAVLink |
| Link-impairment experiments | A seeded, virtual-time model scored against declared outages | Any real network |
| Rust core | Format, lint and tests in CI | Use by the ROS 2 nodes |
| LLM, VLM, SimReady and multimodal extensions | Mocked models and synthetic inputs | Model accuracy, real cameras, synchronised sensors |

**There is no physical-robot, field or vehicle-safety evidence.** The
[validation record](robotics/ros3_limassol/docs/VALIDATION.md) lists each check,
newest first, with CI run links and what each result does not establish.

## Record, replay and export evidence

From `robotics/ros3_limassol`:

```bash
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.replay run.jsonl --json
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 > evidence.json
```

- **Recordings** hold the receiver's observations, including periodic ticks
  during silence, so replay reaches the same states at the same times. Recording
  refuses to overwrite a file.
- **The evidence report** summarises accepted and rejected messages and every
  stale/recovery transition, with a SHA-256 fingerprint of the recording. It
  never exports raw telemetry.
- **Timeout:** replay and evidence use 1.0 s by default. Pass `--stale-after`
  when a recording was made with a different timeout.

See the [recording format](robotics/ros3_limassol/docs/RECORDING.md) and the
[evidence guide](robotics/ros3_limassol/docs/EVIDENCE.md).

## Other ways in

### ROS 2 (optional)

Supported: **Humble on Ubuntu 22.04** and **Jazzy on Ubuntu 24.04**. Build and
source the package as the [ROS package guide](robotics/ros3_limassol/README.md)
describes, then:

```bash
ros2 launch ros3_limassol usv_demo.launch.py                              # simulated USV and monitor
ros2 launch ros3_limassol record_telemetry.launch.py output_path:=run.jsonl  # record a live stream
```

Stop recording with Ctrl+C. The output path is relative to that terminal's
working directory; use an absolute path if you will replay elsewhere.

### MAVLink autopilots (experimental, no ROS)

```bash
python -m ros3_limassol.mavlink_bridge --listen 127.0.0.1:14550 --record run.jsonl
```

- **Input:** the bridge maps `GLOBAL_POSITION_INT` and `SYS_STATUS` from one
  MAVLink system onto the telemetry schema, so its recordings replay like any
  other.
- **Receive-only:** it **never sends MAVLink**: no heartbeats, stream requests
  or commands. A ground station or router must already stream to it.
- **Timeout:** choose `--stale-after` for your vehicle's position rate, and pass
  the same value to replay and evidence.

The [MAVLink guide](robotics/ros3_limassol/docs/MAVLINK.md) explains the
mapping, the timeout and the limits. The
[SITL runbook](robotics/ros3_limassol/docs/SITL.md) reproduces the ArduPilot
check.

### Link-impairment experiments

```bash
python -m ros3_limassol.impairment docs/impairment-example.json
```

This runs the monitor against a seeded model of delay, jitter, independent and
bursty loss, duplication, outages and publisher restarts, for one or more
robots. It scores the monitor against the declared outages: detection and
recovery latency, missed outages and false alarms. The model is synthetic and
runs on virtual time. [IMPAIRMENT.md](robotics/ros3_limassol/docs/IMPAIRMENT.md)
explains how to read the results and choose a timeout.

### Rust core (experimental)

The Rust core provides validation, monitoring and replay, with optional
HMAC-SHA256 signed envelopes. It does not connect to ROS 2, and the Python ROS
adapter does not accept its signed envelopes. See the
[Rust core guide](robotics/ros3_core/README.md).

## Experimental extensions

These are optional and read-only. None of them can command a vehicle or change
`HEALTHY` and `STALE`.

| Extension | What it does | Limits | Guide |
| --- | --- | --- | --- |
| LLM diagnostics | Asks a local Ollama model to explain link status from bounded, validated status and evidence fields | Never sees raw telemetry; output is unverified text; CI uses a mock | [LLM.md](robotics/ros3_limassol/docs/LLM.md) |
| VLM camera inspection | Describes sampled JPEG/PNG frames with a local Ollama vision model, from a file or a ROS 2 `CompressedImage` topic | Accuracy not validated; tests use a fake model | [VLM.md](robotics/ros3_limassol/docs/VLM.md) |
| SimReady provenance | Associates a version-pinned OpenUSD asset, and optionally a camera-format probe report, with a recording | Does not run Isaac Sim or prove the asset was loaded | [SIMREADY.md](robotics/ros3_limassol/docs/SIMREADY.md) |
| Offline analytics and multimodal bundles | Extracts aggregate observation features, fits an exploratory baseline, and bundles them with external tracker and VLM summaries | Exploratory; no synchronised clocks, localisation or hardware validation | [MULTIMODAL.md](robotics/ros3_limassol/docs/MULTIMODAL.md) |

## Run the tests

From `robotics/ros3_limassol`:

```bash
python -m unittest discover -s tests -v
```

- **ROS graph tests** are skipped without `rclpy`; the Humble and Jazzy CI jobs
  run them.
- **What the tests show:** all of them use synthetic inputs, so they are not
  network measurements or vehicle-safety evidence.
- **CI:** see the [GitHub Actions workflows](.github/workflows/) and the
  [CI notes](docs/CI.md), which also cover an optional GitLab mirror pipeline.

## Repository layout

```text
robotics/ros3_limassol/    Python package, ROS 2 nodes and launch files, docs/, tools/, tests/
robotics/ros3_core/        Experimental Rust core
docs/papers/               Manuscripts and arXiv preparation
docs/                      CI notes and LearnTwin documentation
backend/ frontend/ learntwin/   LearnTwin, the original classroom app (separate, MIT)
```

LearnTwin is unrelated to the monitor. See
[LEARNTWIN_README.md](LEARNTWIN_README.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Coding agents should also read
[CLAUDE.md](CLAUDE.md), which sets the boundaries, required checks and current
priorities. Work is planned in GitHub issues.

## Research and credits

**Project lead and paper author:** [Charalampos Nadiotis](https://github.com/n0711)  
**Initial project idea:** [Christos Paparistodemou](https://www.researchgate.net/profile/Christos-Paparistodemou)

[Research overview](https://n0711.github.io/pelaos-tech/ros3-limassol/) · [Preliminary ResearchGate report](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.pdf) · [Original paper](docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) · [Manuscript source](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.tex) · [arXiv preparation](docs/papers/ARXIV.md)

The ResearchGate report (25 October 2026) is preliminary and **not peer
reviewed**. It describes an earlier experimental version. Later work added
recording and replay, ROS recording, Humble support, the MAVLink bridge and the
impairment experiments.

## Licences

- ROS3-Limassol software: [Apache-2.0](robotics/ros3_limassol/LICENSE) ([NOTICE](robotics/ros3_limassol/NOTICE)).
- Existing LearnTwin material: [MIT](LICENSE).
- ResearchGate manuscript and its adaptations: [Civilian-Use Licence (No Military Use), v1.0](docs/papers/MANUSCRIPT_LICENCE.md). Military use of that manuscript edition and its adaptations is prohibited; these manuscript terms **do not change the software licences**.

## Support

Optional one-off support: [Revolut](https://revolut.me/nadiotis).
