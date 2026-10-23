# Validation record

Date: 24 October 2026. Package: ROS3-Limassol 0.2.0.

## Local implementation checks

- Python 3.12.14: 32 tests discovered; 31 passed and the ROS graph test explicitly
  skipped because `rclpy` is absent.
- The virtual-time experiment reproduces WAITING at 0.0 seconds, HEALTHY at 0.0
  seconds, STALE at 2.9 seconds and HEALTHY at 5.0 seconds. Final counts: 51
  accepted, zero rejected.
- Recording captures 81 observation ticks, including 30 null ticks during the
  blackout. Replay reproduces every original event and final count.
- Tests cover changed replay timeouts, final silence, malformed telemetry,
  duplicates, wrong robots, retired sessions, schema errors, clock ordering,
  bounded input, CLI errors and file overwrite protection.
- An offline wheel build and isolated installation passed. Record/replay from
  outside the source tree matched; the wheel contains the ROS adapter, launch
  file, package manifest, resource marker, license and attribution notice.
- Python source, package XML and workflow YAML parsing passed.

## ROS and CI

The local environment has no ROS installation or container engine. The
[workflow](https://github.com/n0711/ROS3-Limassol/actions/workflows/ros3-ci.yml)
defines Linux/Python 3.10 and 3.12, Windows/Python 3.12, installed-wheel checks and
a Jazzy package build with a DDS blackout/recovery test. Check each actual job
result; configuration alone does not establish that a platform passed.

These checks use synthetic observations. Real vessel behavior, wireless timing,
synchronized capture age and field reliability remain unmeasured. The original
paper remains the historical 0.1.0 report.
