# ROS3-Limassol

An **OpenPELAOS** project for telemetry arrival-liveness monitoring in intermittently connected robotic systems.

**Project lead and paper author:** [Charalampos Nadiotis](https://github.com/n0711).
**Initial project idea:** [Christos Paparistodemou](https://www.researchgate.net/profile/Christos-Paparistodemou).

[Paper (PDF)](docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) · [Package guide](robotics/ros3_limassol/README.md) · [Recording format](robotics/ros3_limassol/docs/RECORDING.md) · [Validation](robotics/ros3_limassol/docs/VALIDATION.md)

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

## Existing LearnTwin components

This repository was initialized with LearnTwin files. They remain under
`frontend/`, `backend/`, `learntwin/` and the existing documentation and tests.
Their [original guide](LEARNTWIN_README.md) remains available. ROS3-Limassol lives
under `robotics/ros3_limassol/` with its own package and test configuration.

## Licenses

The ROS3-Limassol package uses [Apache-2.0](robotics/ros3_limassol/LICENSE), with
attribution in [NOTICE](robotics/ros3_limassol/NOTICE). Existing LearnTwin material
retains the repository's [MIT license](LICENSE).

