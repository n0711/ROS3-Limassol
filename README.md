# ROS3-Limassol

An **OpenPELAOS** project for telemetry arrival-liveness monitoring in intermittently connected robotic systems.

**Project lead and paper author:** [Charalampos Nadiotis](https://github.com/n0711).
**Initial project idea:** [Christos Paparistodemou](https://www.researchgate.net/profile/Christos-Paparistodemou).
**PELAOS research overview:** https://n0711.github.io/pelaos-tech/ros3-limassol/ — source, credits, validation limits and links to the preliminary report.

[ResearchGate edition (PDF)](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.pdf) · [Manuscript licence](docs/papers/MANUSCRIPT_LICENCE.md) · [Original paper (PDF)](docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) · [arXiv preparation](docs/papers/ARXIV.md) · [Updated manuscript (PDF)](docs/papers/ROS3_Limassol_arxiv_preparation.pdf) · [Package guide](robotics/ros3_limassol/README.md) · [Recording format](robotics/ros3_limassol/docs/RECORDING.md) · [Validation](robotics/ros3_limassol/docs/VALIDATION.md)

The ResearchGate edition dated **25 October 2026** is a preliminary technical report and has not been peer reviewed. Its [editable XeLaTeX source](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.tex) is included. **Military use of the licensed manuscript and its adaptations is prohibited.** The custom licence applies to that manuscript edition; the software licences are listed below.

## Run the prototype

Use Python 3.10 or newer. The core uses only the standard library.

```sh
git clone https://github.com/n0711/ROS3-Limassol.git
cd ROS3-Limassol/robotics/ros3_limassol
python -m ros3_limassol.demo
```

On Windows, `py -3` can replace `python`; on Linux, use `python3` if needed.
The default experiment uses virtual time and finishes immediately.

```text
t= 0.0s  WAITING
t= 0.0s  HEALTHY
t= 2.9s  STALE
t= 5.0s  HEALTHY
Accepted: 51; rejected: 0
```

## Record and replay

From the same directory:

```sh
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.replay run.jsonl --json
python -m ros3_limassol.replay run.jsonl --stale-after 2.0
```

Recording includes silent observation ticks during the blackout. Replay uses the
recorded receiver-relative clock and can compare timeout choices against the same
observations. Recording creates a new file and refuses to overwrite one.

## Export offline telemetry evidence

Summarize an existing receiver-observation recording without ROS:

```sh
cd robotics/ros3_limassol
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 > evidence.json
```

The generated report contains a SHA-256 recording fingerprint, accepted/rejected
counts and observed stale/recovery transitions, but not the original telemetry.
It does **not** establish network delay, delivery reliability, actual
sensor freshness or field performance. See the
[offline evidence guide](robotics/ros3_limassol/docs/EVIDENCE.md).

## Offline anomaly and vision evidence (experimental)

The read-only, standard-library `ros3_limassol.analysis` tool extracts
aggregate receiver-observation features and fits an exploratory median/MAD
baseline from at least five distinct training recordings. Optional
`ros3_limassol.multimodal` bundles those features with independent VERA-MOT
tracker summaries and declared external-VLM annotations. No real VLM runs in
this repository; synchronized clocks, GNSS-denied localization, navigation
and hardware validation remain unverified.

See the [multimodal research guide](robotics/ros3_limassol/docs/MULTIMODAL.md).

## Current implementation

- Strict version-1 JSON telemetry with explicit units and bounded payloads.
- WAITING, HEALTHY and STALE states driven by accepted receiver arrivals.
- Duplicate, out-of-order and retired-session rejection with bounded history.
- A synthetic USV source and a repeatable blackout/recovery scenario.
- Streaming JSONL recording/replay, including malformed-payload rejections.
- A receive-only ROS telemetry recorder with independent silence ticks and new-file protection.
- An optional ROS 2 Humble/Jazzy publisher, observer and recorder adapter.
- Core, packaging and ROS graph checks in [GitHub Actions](https://github.com/n0711/ROS3-Limassol/actions/workflows/ros3-ci.yml).

`HEALTHY` means accepted telemetry arrived recently. It does not establish sensor
capture freshness, navigation accuracy or vehicle health. This prototype has no
vehicle-command interface. ROS3-Limassol is an independent project using ROS 2,
not an official ROS distribution.

The paper records the original 0.1.0 experiment. Version 0.2.0 adds offline
recording/replay; 0.3.0 adds live ROS recording; 0.3.1 adds Humble compatibility.
Current validation is documented separately.

After building the ROS package, record an existing `/limassol/usv01/telemetry`
stream in a second sourced terminal:

```bash
ros2 launch ros3_limassol record_telemetry.launch.py output_path:=run.jsonl
```

Stop with Ctrl+C and replay from the package directory using
`python -m ros3_limassol.replay run.jsonl --json`. Paths are relative to each
terminal's working directory; use an absolute path when the terminals differ.

## Development

From the package directory:

```sh
python -m unittest discover -s tests -v
```

The optional transport targets Humble on Ubuntu 22.04 and Jazzy on Ubuntu 24.04.
The [package guide](robotics/ros3_limassol/README.md)
contains build, launch, topic-inspection and test commands. See the
[architecture](robotics/ros3_limassol/docs/ARCHITECTURE.md),
[telemetry contract](robotics/ros3_limassol/docs/TELEMETRY.md),
[roadmap](robotics/ros3_limassol/docs/ROADMAP.md) and [contributor guide](CONTRIBUTING.md).

## CI/CD and editor validation

This GitHub repository uses [GitHub Actions](.github/workflows/) for its existing
automated checks. An [optional GitLab mirror pipeline](.gitlab-ci.yml) covers the
Python telemetry core, Rust core, ROS 2 Humble and Jazzy adapters, LearnTwin
frontend, and academic backend. GitLab's official CI JSON Schema is associated
with that YAML file for supported editors; the schema does not execute any jobs.

See the [CI/CD coverage and validation guide](docs/CI.md) for configuration,
GitLab runner requirements, and the difference between synthetic tests and
field-validation evidence.

## Experimental Rust core

[`robotics/ros3_core/`](robotics/ros3_core/README.md) adds a Rust telemetry validator,
arrival monitor and streaming replay CLI. It preserves the telemetry-v1 contract
and offers optional HMAC-SHA256 envelopes with no unsigned fallback in keyed mode.
Differential tests compare replay states against the Python implementation. The
existing ROS adapter remains Python and does not yet support the signed envelope.
This is not a ROS replacement or a measured performance claim.

## Existing LearnTwin components

This repository was initialized with LearnTwin files. They remain under
`frontend/`, `backend/`, `learntwin/` and the existing documentation and tests.
Their [original guide](LEARNTWIN_README.md) remains available. ROS3-Limassol lives
under `robotics/ros3_limassol/` with its own package and test configuration.

## Licenses

The ROS3-Limassol package uses [Apache-2.0](robotics/ros3_limassol/LICENSE), with
attribution in [NOTICE](robotics/ros3_limassol/NOTICE). Existing LearnTwin material
retains the repository's [MIT license](LICENSE).

The [ResearchGate manuscript edition](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.pdf) and its
[XeLaTeX source](docs/papers/ROS3_Limassol_ResearchGate_No_Military_Use.tex) use the
[**Civilian-Use Licence (No Military Use), Version 1.0**](docs/papers/MANUSCRIPT_LICENCE.md).
Civilian reuse, including commercial civilian reuse, is permitted with attribution,
retention of the licence and idea credit, and identification of changes.
Military use of the licensed manuscript or its adaptations is prohibited.
These custom manuscript terms do not amend the software's Apache-2.0 or MIT
licences or revoke previously granted rights.


## Support this project

If this project is useful to you, you can support its development with a one-off contribution via Revolut:

**[revolut.me/nadiotis](https://revolut.me/nadiotis)**
