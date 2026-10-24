# Validation record

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
