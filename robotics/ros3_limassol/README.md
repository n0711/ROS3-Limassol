# ROS3-Limassol package

OpenPELAOS telemetry-liveness prototype, version 0.3.1. Developed by Charalampos
Nadiotis; initial project idea credited to Christos Paparistodemou. [Apache-2.0](LICENSE).

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

## ROS 2 Humble on Ubuntu 22.04

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

Each robot uses `/limassol/<robot_id>/`. Startup parameters are read once; restart
the nodes to change them. Steady-clock timers and receiver monotonic time drive
liveness. No hard scheduling bound is established.

## Record a live ROS stream

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
and run all 45 tests, including DDS blackout/recovery, live recording/replay and
recorder configuration/file-protection tests. Consult actual job results and the
[validation record](docs/VALIDATION.md).

The [paper](../../docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) describes version
0.1.0. Offline recording/replay were added in 0.2.0; live ROS recording in 0.3.0.
Version 0.3.1 adds Humble compatibility and dual-distribution ROS CI.
No physical marine dynamics,
MAVLink adapter or field deployment has been verified. See the [roadmap](docs/ROADMAP.md).
