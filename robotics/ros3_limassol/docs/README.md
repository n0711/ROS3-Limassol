# ROS3-Limassol documentation

Start with the [project README](../../../README.md): it explains what
ROS3-Limassol is, runs a two-minute demo, and shows what has been validated. The
[package guide](../README.md) covers installation, the ROS 2 builds and every
command-line tool. The documents below go deeper.

## Concepts and formats

| Document | Read it to… |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Understand the components, the liveness rule, and what each part does and does not tell you |
| [TELEMETRY.md](TELEMETRY.md) | See the schema-v1 message, its validation, sessions and sequence rules, and the late-sample policy |
| [RECORDING.md](RECORDING.md) | Read or write receiver-observation recordings and replay them |
| [EVIDENCE.md](EVIDENCE.md) | Interpret evidence reports and their recording fingerprint |

## Inputs

| Document | Read it to… |
| --- | --- |
| [Package guide: ROS 2](../README.md#ros-2-humble-on-ubuntu-2204) | Build for Humble or Jazzy, launch the simulator and monitor, and record a live stream |
| [MAVLINK.md](MAVLINK.md) | Use the receive-only MAVLink bridge: its message mapping, choosing `--stale-after`, and its limits |

## Experiments and evidence

| Document | Read it to… |
| --- | --- |
| [IMPAIRMENT.md](IMPAIRMENT.md) | Run the seeded link-impairment model, read its scores, and choose a timeout |
| [SITL.md](SITL.md) | Reproduce the ArduPilot SITL check with scripted outages |
| [VALIDATION.md](VALIDATION.md) | See what has been run, with results and what each does not establish (newest first) |
| [ROADMAP.md](ROADMAP.md) | See what is planned next |

## Experimental extensions

These are optional and read-only; none can command a vehicle or change the
monitor's state.

| Document | Read it to… |
| --- | --- |
| [LLM.md](LLM.md) | Use local Ollama text diagnostics of link status |
| [VLM.md](VLM.md) | Use local vision-model descriptions of camera frames |
| [SIMREADY.md](SIMREADY.md) | Record SimReady/Isaac Sim experiment provenance and check camera formats |
| [MULTIMODAL.md](MULTIMODAL.md) | Use offline analytics and multimodal evidence bundles |

## Elsewhere in the repository

- [Rust core](../../ros3_core/README.md): the experimental alternative core, with signed envelopes.
- [CI notes](../../../docs/CI.md): the GitHub Actions jobs and the optional GitLab mirror.
- [Papers](../../../docs/papers/ARXIV.md): the manuscripts and arXiv preparation.
- [Contributing](../CONTRIBUTING.md) and the [agent guide](../../../CLAUDE.md).

## How evidence is described

The documents use these terms consistently:

- **Tested:** automated tests with synthetic inputs, run locally and in CI.
- **CI:** a GitHub Actions job. A claim that rests on CI should name the run.
- **SITL:** ArduPilot software-in-the-loop simulation on one host, over loopback.
- **Not established:** no evidence yet. Every document lists what its results
  do not show.

No document claims physical-robot, field or vehicle-safety validation.
`HEALTHY` always means only that valid telemetry arrived recently.
