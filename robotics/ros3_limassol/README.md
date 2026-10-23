# ROS3-Limassol package

OpenPELAOS telemetry-liveness prototype, version 0.2.0. Developed by Charalampos
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

The Jazzy CI job performs the same package build, launch-argument inspection and
DDS blackout/recovery test. Consult actual job results and the [validation record](docs/VALIDATION.md).

The [paper](../../docs/papers/ROS3_Limassol_OpenPELAOS_A4.pdf) describes version
0.1.0. Recording/replay are additions in 0.2.0. No physical marine dynamics,
MAVLink adapter or field deployment has been verified. See the [roadmap](docs/ROADMAP.md).
