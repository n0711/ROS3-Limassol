# ROS3-Limassol

**Telemetry arrival monitoring for robots with intermittent connections.**

ROS3-Limassol is an experimental OpenPELAOS research prototype that monitors whether telemetry messages are arriving at a receiver. It detects communication silence and recovery, and supports reproducible offline recording and replay.

**It is not ROS 3, an official ROS distribution, or a replacement for ROS 2.** Its ROS 2 integration is optional.

## What does it do?

A robot sends telemetry to a receiver. ROS3-Limassol validates incoming messages and tracks three states:

| State | Meaning |
| --- | --- |
| `WAITING` | No valid telemetry has arrived yet. |
| `HEALTHY` | Valid telemetry has arrived recently. |
| `STALE` | No valid telemetry has arrived within the configured timeout. |

**Important:** `HEALTHY` describes *receiver arrival recency*, not vehicle safety, sensor freshness, navigation accuracy, network latency, or delivery reliability. The prototype does not send vehicle commands.

## Choose a starting point

- **Just want to understand it?** Run the Python demo below; it requires no ROS installation.
- **Already use ROS 2?** Follow the [ROS package guide](robotics/ros3_limassol/README.md) for Humble/Jazzy setup and topic recording.
- **Interested in Rust?** See the [experimental Rust core](robotics/ros3_core/README.md); it does not connect to ROS 2 by itself.

## Quick start (no ROS required)

Requires Python 3.10+; the core uses only the standard library.

```bash
git clone https://github.com/n0711/ROS3-Limassol.git
cd ROS3-Limassol/robotics/ros3_limassol
python -m ros3_limassol.demo
```

On Linux, use `python3` if necessary; on Windows, `py -3` may replace `python`. The demo uses virtual time and finishes immediately.

Example output:

```text
t= 0.0s  WAITING
t= 0.0s  HEALTHY
t= 2.9s  STALE
t= 5.0s  HEALTHY
Accepted: 51; rejected: 0
```

## Record, replay, and export evidence

Run these commands from `robotics/ros3_limassol`:

```bash
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.replay run.jsonl --json
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 > evidence.json
```

Recordings include receiver observation ticks during communication silence. The exporter summarizes accepted/rejected messages and stale/recovery transitions with a SHA-256 recording fingerprint; it does not export raw telemetry. Recording refuses to overwrite an existing file.

See [recording format](robotics/ros3_limassol/docs/RECORDING.md) and [evidence guide](robotics/ros3_limassol/docs/EVIDENCE.md).

## Offline anomaly and vision evidence (experimental)

The read-only, standard-library `ros3_limassol.analysis` tool extracts
aggregate receiver-observation features and fits an exploratory median/MAD
baseline from at least five distinct training recordings. Optional
`ros3_limassol.multimodal` bundles those features with independent VERA-MOT
tracker summaries and declared external-VLM annotations. No real VLM runs in
this repository; synchronized clocks, GNSS-denied localization, navigation
and hardware validation remain unverified.

See the [multimodal research guide](robotics/ros3_limassol/docs/MULTIMODAL.md).

## Optional local LLM diagnostics (experimental)

ROS3 now includes an **actual local Ollama language-model inference adapter**
for explaining receiver-arrival link status. It is read-only and independent of
the core monitor. The LLM receives bounded, validated status/evidence fields,
**not raw telemetry**, and never controls a robot.

With a local Ollama server and a locally installed model (e.g. `llama3.2`),
run from `robotics/ros3_limassol/`:

```bash
python -m ros3_limassol.llm_diagnostics --evidence evidence.json --model llama3.2
```

For ROS 2 use `ros2 launch ros3_limassol llm_diagnostics.launch.py model:=llama3.2`
after building and sourcing the package. The model must already be running;
CI uses a mock, not downloaded model weights. Output is **unverified diagnostic
text**, not autonomy, VLM/VLA, or field validation. See the
[LLM integration guide](robotics/ros3_limassol/docs/LLM.md).

## Local VLM camera inspection (experimental)

ROS3 now has an **opt-in camera-to-vision-model path**: a ROS 2
`sensor_msgs/msg/CompressedImage` subscriber samples bounded JPEG/PNG frames,
uses a separately installed **local** Ollama vision model, and publishes a
read-only `vlm_diagnostics` topic. It does **not** require ROS 2 to run a
single-file image inspection:

```bash
# From robotics/ros3_limassol; requires a local vision model in Ollama
python -m ros3_limassol.vlm_diagnostics --image frame.jpg --model gemma3:4b
```

The optional ROS launch is `vlm_observer.launch.py`. It never sends vehicle
commands or connects its descriptions to navigation. Tests use a fake model;
real-world visual accuracy is **not validated**. See the
[VLM setup and boundaries](robotics/ros3_limassol/docs/VLM.md).

## What is implemented?

- Bounded, versioned JSON telemetry validation with explicit units.
- Duplicate, out-of-order, and retired-session rejection.
- Arrival-based `WAITING`, `HEALTHY`, and `STALE` states.
- Deterministic simulated communication blackout and recovery.
- Streaming JSONL recording and replay.
- Optional ROS 2 Humble/Jazzy simulator publisher and link observer, plus a separate receive-only recorder.
- Experimental Rust validation, monitoring, and replay tools.

The Rust core has optional HMAC-SHA256 envelopes; the Python ROS adapter does **not** support those signed envelopes yet.

## ROS 2 integration (optional)

Supported targets: **ROS 2 Humble / Ubuntu 22.04** and **ROS 2 Jazzy / Ubuntu 24.04**.

Follow the [ROS package guide](robotics/ros3_limassol/README.md) to build and source your environment. To record an existing telemetry stream, run in a sourced terminal:

```bash
ros2 launch ros3_limassol record_telemetry.launch.py output_path:=run.jsonl
```

Stop with Ctrl+C. The output path is relative to that terminal's working directory; an absolute path is safer when replaying elsewhere.

## Testing and validation

From `robotics/ros3_limassol`:

```bash
python -m unittest discover -s tests -v
```

Automated checks cover synthetic scenarios, including silence and recovery. **Physical robot and field validation remain pending.** Do not interpret these tests as measured network performance or vehicle safety evidence.

See [validation](robotics/ros3_limassol/docs/VALIDATION.md), [CI details](docs/CI.md), and [GitHub Actions](.github/workflows/). An optional GitLab mirror pipeline is also included.

## Documentation

- [ROS package setup](robotics/ros3_limassol/README.md)
- [Architecture](robotics/ros3_limassol/docs/ARCHITECTURE.md)
- [Telemetry contract](robotics/ros3_limassol/docs/TELEMETRY.md)
- [Rust core](robotics/ros3_core/README.md)
- [Roadmap](robotics/ros3_limassol/docs/ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Original LearnTwin components](LEARNTWIN_README.md) — retained in this repository, separate from the ROS3 prototype.

## Research and credits

**Project lead and paper author:** [Charalampos Nadiotis](https://github.com/n0711)  
**Initial project idea:** [Christos Paparistodemou](https://www.researchgate.net/profile/Christos-Paparistodemou)

[Research overview](https://n0711.github.io/pelaos-tech/ros3-limassol/) · [Preliminary ResearchGate report](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.pdf) · [Original paper](docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) · [Manuscript source](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.tex) · [arXiv preparation](docs/papers/ARXIV.md)

The ResearchGate report (25 October 2026) is preliminary and **not peer reviewed**. It describes an earlier experimental version; later implementations include recording/replay, ROS recording, and Humble compatibility.

## Licences

- ROS3-Limassol software: [Apache-2.0](robotics/ros3_limassol/LICENSE) ([NOTICE](robotics/ros3_limassol/NOTICE)).
- Existing LearnTwin material: [MIT](LICENSE).
- ResearchGate manuscript and its adaptations: [Civilian-Use Licence (No Military Use), v1.0](docs/papers/MANUSCRIPT_LICENCE.md). Military use of that manuscript edition and its adaptations is prohibited; these manuscript terms **do not change the software licences**.

## Support

Optional one-off support: [Revolut](https://revolut.me/nadiotis).
