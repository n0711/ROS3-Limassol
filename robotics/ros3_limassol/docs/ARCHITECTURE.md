# Architecture

ROS3-Limassol is an OpenPELAOS project. Version 0.1.0 has a transport-independent
Python core and an optional ROS 2 adapter. The core imports only Python's
standard library. ROS provides discovery, serialization of the outer message,
and transport between nodes in ROS mode.

## Data flow

1. `UsvSimulator` produces synthetic geodetic telemetry and drops samples during
   one configured blackout. Its generated sequence continues during the blackout.
2. `Telemetry` validates fields and encodes a compact schema-v1 JSON payload.
3. In the local demo, that payload goes directly to `LinkMonitor`. In ROS mode,
   it travels in `std_msgs/msg/String` on the relative `telemetry` topic.
4. The monitor validates the payload, robot ID, session, and sequence before
   recording the arrival time from its own monotonic clock.
5. The ROS observer periodically publishes a JSON status on `link_status`.

The simulator and monitor run in separate ROS nodes. The plain-Python demo is an
in-process experiment; it does not exercise a network or DDS.

## Liveness rule

`age_s = receiver_now_s - last_accepted_arrival_s`

With a 1.0 s timeout and a last accepted arrival at 1.9 s, an observation at
2.9 s has `age_s = 1.0` and is STALE.

Before the first valid sample, status is WAITING. After a valid arrival it is
HEALTHY while `age_s < stale_after_s`; otherwise it is STALE. Any later accepted
sample restores HEALTHY. Invalid or replayed samples do not reset the timeout.

This is an arrival-liveness estimate. A stopped publisher, transport disruption,
and loss of upstream sensor data may all cause STALE. A source that transmits
old measurements with increasing sequences can still appear HEALTHY. Assessing
measurement age requires a separate clock and timestamp model.

## Sessions and bounds

A publisher generates a session UUID when it starts. Within the active session,
sequence numbers must strictly increase. A first-seen session switches the active
session and permits the sequence to restart. Previously observed, retired
sessions are rejected for the monitor's lifetime.

The default monitor remembers at most 128 sessions and fails closed for an
additional unseen session. The current session may continue. A deliberate monitor
restart clears the history. This bounds state in the starter; persistent restart
history and authenticated session negotiation remain future work. The monitor
assumes one legitimate publisher per robot ID; it cannot arbitrate competing or
malicious publishers.

Payloads are limited to 4096 UTF-8 bytes before JSON decoding. Both the character
and byte length are checked, and invalid nesting, duplicate keys, unsupported
versions, non-finite values, and unexpected fields are rejected.

## ROS topic policies

Telemetry uses KEEP_LAST depth 1, BEST_EFFORT, VOLATILE on both ends. This chooses
recent arrivals over queued historical telemetry. It does not guarantee delivery.
Status uses KEEP_LAST depth 1, RELIABLE, VOLATILE and is published every 0.1 s.
The observer logs state transitions instead of logging every sample.

An observer of `link_status` should independently detect missing status arrivals:
the monitor itself can stop. This version does not provide a downstream status
watchdog. The ROS nodes use steady-clock timers, and the domain monitor uses
`time.monotonic()` rather than sender wall time or simulated ROS time.

JSON in `std_msgs/String` keeps this first adapter small. Generated ROS interfaces,
`sensor_msgs` outputs, and schema migration require separate design work.

## Observation recording and replay

Version 0.2.0 adds `recording.py` and `replay.py`. The simulator can write bounded
JSONL observations at every virtual tick, including null payloads during silence.
Replay feeds raw payloads through the same validator and LinkMonitor while
advancing the recorded receiver clock. It does not replace the ROS transport or
simulate network timing. See [RECORDING.md](RECORDING.md) for the format and limits.

Version 0.3.0 adds a separate `TelemetryRecorderNode`. It subscribes to the same
telemetry topic using the existing QoS and delegates file writes to the
standard-library-only `LiveRecorder`. A steady-clock timer writes null ticks
independently of subscriptions. Relative timestamps are sampled inside a writer
lock, so writes from parallel callers cannot reorder the receiver clock.
File creation is exclusive; writes are incremental and bounded by observation
count. No telemetry schema or transport is changed. Recording is optional and
does not run inside the live liveness monitor.

## Evidence and references

- [Official Jazzy Python publisher/subscriber tutorial](https://docs.ros.org/en/jazzy/Tutorials/Beginner-Client-Libraries/Writing-A-Simple-Py-Publisher-And-Subscriber.html): node, package, entry-point, and dependency conventions.
- [Official Jazzy QoS documentation](https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Quality-of-Service-Settings.html): history, reliability, durability, and compatibility.
- [Official ROS distributions](https://docs.ros.org/en/jazzy/Releases.html): Jazzy support period.

References checked on 23 October 2026. The code is an independent implementation;
the documentation does not establish that this project's ROS graph has passed.
The recorder's node/timer/cleanup APIs were also checked against the official
[Jazzy rclpy source](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/node.py)
on 24 October 2026. Executed checks are recorded in [VALIDATION.md](VALIDATION.md).

The same adapter targets Humble on Ubuntu 22.04. Its timer, subscription and
cleanup APIs were checked against the official
[Humble rclpy source](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/node.py)
on 24 October 2026. Both versions support an explicit timer clock; the adapter
uses no Jazzy-only `create_timer` arguments. Separate ROS CI jobs exercise the
same package and test suite on each distribution. The standalone Python core
and schema-v1 recording format are shared.
