# ROS3-Limassol Python and ROS 2 package

OpenPELAOS receiver-arrival monitoring prototype, version 0.3.1. Developed by Charalampos
Nadiotis; initial project idea credited to Christos Paparistodemou. [Apache-2.0](LICENSE).

**Start here:** Choose **Standalone Python** if you want a quick synthetic demonstration
without ROS. Choose **ROS 2 Humble** or **ROS 2 Jazzy** if you want ROS topics,
a simulator publisher or a receive-only recorder. These ROS 2 steps require a
separately installed ROS distribution; this project is not an official ROS release.

**Directory conventions:** Standalone `python -m` commands below run from this
package directory (`robotics/ros3_limassol/`). ROS build and launch steps run
from the **repository root** (the directory containing `robotics/`). Use a
separate terminal for each concurrently running ROS process, and source the
same ROS distribution and workspace in each terminal.

## Standalone Python

From this directory, with Python 3.10 or newer:

```sh
python -m ros3_limassol.demo
python -m ros3_limassol.demo --realtime --json
python -m ros3_limassol.demo --record run.jsonl
python -m ros3_limassol.replay run.jsonl --json
```

The default blackout suppresses samples for `2.0 <= t < 5.0` seconds. The monitor
becomes STALE at 2.9 seconds and HEALTHY at 5.0 seconds: 51 accepted, zero rejected,
30 suppressed samples. Virtual time is the default; `--realtime` paces the source.

Use `python -m ros3_limassol.demo --help` for duration, rate, timeout and blackout
options. Replay supports `--robot-id`, `--stale-after` and `--json`. See the
[recording format](docs/RECORDING.md) before supplying your own trace.

## Offline evidence report

For an existing version-1 receiver recording (synthetic or a receive-only ROS
recording), create a machine-readable report **without a ROS installation**:

```sh
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 --stale-after 1.0 > evidence.json
```

The command validates the whole file before printing JSON, includes the source
SHA-256 digest, counts received payloads and silence ticks, reports accepted and
rejected messages, and records **observed** link-state transitions and recoveries.
It neither republishes telemetry nor sends vehicle commands. SHA-256 identifies
the exact input bytes; it does not authenticate the recording or establish its
provenance. A failed read emits no JSON report. See the
[evidence specification](docs/EVIDENCE.md) for interpretation and limitations.

## Receive-only MAVLink input (experimental)

Observe a MAVLink sender over UDP **without ROS or pymavlink**:

```sh
python -m ros3_limassol.mavlink_bridge --listen 127.0.0.1:14550 --record run.jsonl
```

`GLOBAL_POSITION_INT` and `SYS_STATUS` from one system ID are mapped explicitly to
telemetry schema v1, so the recording replays and exports evidence like any
other. The bridge never sends MAVLink; the sender must already stream to it.
See the [MAVLink mapping and limits](docs/MAVLINK.md).

## Link-impairment experiments

Score the monitor against declared outages under seeded delay, jitter,
independent and bursty loss, duplication and publisher restarts, for several
robots at once, **without ROS**:

```sh
python -m ros3_limassol.impairment docs/impairment-example.json --record-dir runs/example
```

The report gives detection and recovery latency per outage, missed outages and
STALE episodes no outage explains; recordings replay with the standard tools.
See the [impairment guide](docs/IMPAIRMENT.md), including a threshold sweep.

## Optional read-only offline analytics

```sh
python -m ros3_limassol.analysis features evidence.json > features.json
python -m ros3_limassol.analysis fit train01.json train02.json train03.json train04.json train05.json > baseline-model.json
python -m ros3_limassol.analysis score baseline-model.json heldout.json > anomaly-score.json
python -m ros3_limassol.multimodal evidence.json vera-vision.json --vlm vera-vlm.json > multimodal-report.json
```

The `--vlm` argument is optional. This is an **offline** research comparison,
not a VLM inference implementation, field-validated detector or navigation
controller. Read the [evidence and multimodal guide](docs/MULTIMODAL.md).

## Local LLM diagnostics (optional, read-only)

ROS3 can run a **real local Ollama chat model** to explain validated LinkStatus
and aggregate offline recording evidence. Ollama and model weights are separately
installed; automated CI uses a fake model response and does not download weights.

From this package directory after exporting evidence, with the local model
server running at `127.0.0.1:11434`:

```bash
python -m ros3_limassol.llm_diagnostics --evidence evidence.json --model llama3.2
```

In a sourced ROS 2 workspace (repository root), run the normal
`usv_demo.launch.py` and a separate read-only observer:

```bash
ros2 launch ros3_limassol llm_diagnostics.launch.py model:=llama3.2
```

Inspect `/limassol/usv01/llm_diagnostics` (`std_msgs/msg/String`).
The LLM does not issue commands, validate vehicle safety, or implement
Vision-Language-Action. Read the full [LLM integration guide](docs/LLM.md)
before interpreting output.

## Local vision-language camera observer (optional)

With a separately running local Ollama **vision** model, ROS3 can consume
`sensor_msgs/msg/CompressedImage` from an existing camera and publish
read-only scene descriptions. No camera driver or model weights are bundled.
From the **package directory** an authorized existing image can be inspected
without ROS:

```bash
python -m ros3_limassol.vlm_diagnostics --image frame.jpg --model gemma3:4b
```

From the **repository root**, after building/sourcing ROS 2:

```bash
ros2 launch ros3_limassol vlm_observer.launch.py model:=gemma3:4b camera_topic:=/camera/image_raw/compressed
```

View output at `/limassol/usv01/vlm_diagnostics`. The input must be an existing
compressed JPEG/PNG camera topic. The observer can also receive
`/limassol/usv01/link_status`, embedding a **bounded receiver-delivery
snapshot** when that status was delivered recently (default
`max_status_age_s:=1.0`). It explicitly reports missing/old status as
unavailable; it does not synchronize camera capture and telemetry clocks.
Requests are local, bounded, rate-limited, and read-only; they do not
establish image interpretation accuracy or navigation authority. See [VLM instructions](docs/VLM.md).

## ROS 2 Humble on Ubuntu 22.04

Run the following commands from the **repository root**, not the package directory.

Install [Humble](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html)
and the standard ROS development tools separately. Use the system Python 3.10
from this ROS installation. From the **repository root**, in a fresh workspace:

```bash
source /opt/ros/humble/setup.bash
rosdep install --from-paths robotics --ignore-src --rosdistro humble -y
colcon build --base-paths robotics --packages-select ros3_limassol --symlink-install
source install/setup.bash
ros2 launch ros3_limassol usv_demo.launch.py
```

In a second terminal at the same repository root:

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch ros3_limassol record_telemetry.launch.py output_path:=run.jsonl
```

Stop the recorder with Ctrl+C and replay from that root:

```bash
python3 -m ros3_limassol.replay run.jsonl --json
```

Use separate workspaces/checkouts for Humble and Jazzy. Their sourced
environments and generated `build/`, `install/` and `log/` trees are not
interchangeable. Do not source both distributions in the same terminal.

## ROS 2 Jazzy on Ubuntu 24.04

Run the following commands from the **repository root**, not the package directory.

Install Jazzy and the standard ROS development tools separately. From the
**repository root**:

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths robotics --ignore-src --rosdistro jazzy -y
colcon build --base-paths robotics --packages-select ros3_limassol --symlink-install
source install/setup.bash
ros2 launch ros3_limassol usv_demo.launch.py
```

In another terminal at the repository root:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 topic echo /limassol/usv01/link_status std_msgs/msg/String
```

For raw telemetry, match the publisher's best-effort reliability:

```bash
ros2 topic echo /limassol/usv01/telemetry std_msgs/msg/String --qos-reliability best_effort
```

Launch overrides:

```bash
ros2 launch ros3_limassol usv_demo.launch.py robot_id:=usv02 stale_after_s:=1.5 blackout_start_s:=4.0 blackout_duration_s:=3.0
```

Add `late_samples:=liveness` to let delayed but new in-session samples refresh
liveness instead of being rejected; the default is `reject`. See
[late samples](docs/TELEMETRY.md#late-samples).

Each robot uses `/limassol/<robot_id>/`. Startup parameters are read once; restart
the nodes to change them. Steady-clock timers and receiver monotonic time drive
liveness. No hard scheduling bound is established.

## Record a live ROS stream

This section records messages delivered to the recorder's subscriber; it cannot
prove how many messages the sender transmitted. For the demo publisher and
observer, start `usv_demo.launch.py` first as shown above. To record an
**existing** telemetry publisher, only the recorder launch is necessary.

After building, run the demo above or an existing schema-v1 telemetry publisher.
In a second terminal with the same ROS distribution and `install/setup.bash` sourced:

```bash
ros2 launch ros3_limassol record_telemetry.launch.py output_path:=run.jsonl
```

The launch starts only a recorder in `/limassol/usv01/`, with best-effort telemetry
QoS. It creates a new file, records raw arrivals and independent steady-clock
ticks every 0.1 seconds, and closes the file on Ctrl+C. Replay it with:

```sh
python -m ros3_limassol.replay run.jsonl --json
```

Use the same working directory or an absolute recording path. For another robot:

```bash
ros2 launch ros3_limassol record_telemetry.launch.py robot_id:=usv02 output_path:=usv02.jsonl tick_period_s:=0.05
```

Then replay with `--robot-id usv02`. For a custom telemetry topic, use the node
directly and remap it:

```bash
ros2 run ros3_limassol telemetry_recorder --ros-args -r telemetry:=/my_robot/telemetry -p output_path:=run.jsonl
```

`tick_period_s` must be in `(0, 60]`. `max_records` must be an integer from 1 to
1,000,000 and includes the initial WAITING tick, arrivals and silence ticks.
Reaching the limit or encountering a clock/file error stops recording with a
nonzero process exit. Existing files are never overwritten. Oversized or
non-UTF-8 payloads cannot be represented in version 1 and are counted/logged
separately. See [recording details and limitations](docs/RECORDING.md).

## Optional NVIDIA SimReady provenance experiment

The optional **read-only** manifest tool binds a declared USD dataset
revision/path/license and a locally checked asset SHA-256 to a separately
recorded ROS3 receiver trace. It does not run Isaac Sim or claim a camera,
ROS bridge or real robot was observed.

```bash
python -m ros3_limassol.simready_evidence simready-manifest.json run.jsonl --asset-file /path/to/asset.usd
```

Review [SIMREADY.md](docs/SIMREADY.md) for the complete protocol, example
manifest and explicit validation limits.

## Read-only ROS 2 camera format probe (optional)

After building and sourcing ROS 2 Humble or Jazzy, observe an existing
`sensor_msgs/msg/CompressedImage` topic **without** running a vision model:

```bash
ros2 run ros3_limassol simready_camera_probe --ros-args \
  -p camera_topic:=/camera/image_raw/compressed \
  -p max_frames:=20 -p timeout_s:=15.0 \
  -p output_path:=/tmp/ros3-camera-probe-01.json
```

The probe writes an exclusive JSON report containing only receiver-side
codec/size/header counts (no images, frame hashes or captions). H264/HEVC
`CompressedImage` is **not** compatible with this package's JPEG/PNG
VLM subscriber. See the [SimReady camera integration protocol](docs/SIMREADY.md)
for raw-image-to-JPEG conversion, verify-before-inference requirements and
the `simready_evidence --camera-report` command. Passing synthetic DDS
tests does not verify real Isaac Sim output or camera timing.

## Tests and packaging

From this package directory:

```sh
python -m unittest discover -s tests -v
python -m compileall -q ros3_limassol launch tests tools
python -m pip wheel --no-deps --no-build-isolation --wheel-dir dist .
python tools/check_wheel.py
```

The build requires setuptools and wheel in the active environment. The check
expects exactly one wheel in `dist/`; remove an older build when building another
version. It verifies installed record/replay from outside the source tree.

The ROS graph test skips when `rclpy` is absent. On a sourced ROS workstation,
run from the repository root after building:

```bash
colcon test --packages-select ros3_limassol --event-handlers console_direct+
colcon test-result --verbose
```

The Humble and Jazzy CI jobs each build the package, inspect both launch files,
run the installed-package quickstart smoke check, and execute ROS/DDS integration
tests, including blackout/recovery, live recording/replay and recorder
configuration/file-protection checks. The exact test count can change.

To check an **installed** ROS package manually from the repository root, after
sourcing the ROS distribution and `install/setup.bash`, run:

```bash
python3 robotics/ros3_limassol/tools/check_ros_quickstart.py
```

This test checks package discovery, synthetic demo/replay agreement, and the
SHA-256 evidence report from a temporary directory, not physical telemetry
or network performance. Consult actual job results and the
[validation record](docs/VALIDATION.md).

The [paper](../../docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) describes version
0.1.0. Offline recording/replay were added in 0.2.0; live ROS recording in 0.3.0.
Version 0.3.1 adds Humble compatibility and dual-distribution ROS CI.
An experimental receive-only MAVLink UDP adapter is tested with
independently encoded frames and against ArduPilot Rover SITL over loopback
(see [validation](docs/VALIDATION.md)). No physical marine dynamics, PX4 SITL,
physical MAVLink link, or field deployment has been verified. See the
[roadmap](docs/ROADMAP.md).
