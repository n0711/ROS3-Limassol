# Architecture

ROS3-Limassol is an experimental OpenPELAOS receiver-arrival monitoring project.
The Python telemetry monitor is transport-independent and requires only the
standard library. An optional ROS 2 Humble/Jazzy adapter provides a simulator
publisher, a status observer, and an independent receive-only recorder. An
experimental Rust core implements separate validation/replay utilities; it is
not wired into the Python ROS 2 nodes. This project is not an official ROS
version or a ROS 2 replacement.

## What each component tells you

- **Python demo:** tests liveness changes using synthetic messages and a virtual
  receiver clock. It does not test DDS, Wi-Fi, radio links, or a physical robot.
- **ROS 2 observer:** subscribes to best-effort telemetry and publishes status
  based on the receiver's accepted arrivals.
- **ROS 2 recorder:** separately saves delivered subscriber callbacks and
  independent silence observations for offline replay. It does not control
  the robot or guarantee that it recorded every transmitted message.
- **Offline replay/evidence:** analyzes *recorded* receiver observations; its
  state transitions are evaluated on the observation clock, not inferred between
  ticks.
- **Rust core:** experimental alternative validation/replay implementation with
  optional authenticated envelopes; the Python ROS 2 adapter does not accept
  those signed envelopes.

All modes distinguish **receiver arrival recency** from source measurement
freshness, delivery ratio, network delay, navigation correctness, and safety.

## Optional local language-model diagnostics

A separate `LLMDiagnosticNode` subscribes to validated `link_status`
messages (reliable ROS 2 status QoS). It never subscribes to raw telemetry,
positions or images. On a state change, it submits a bounded status snapshot
to a single worker for actual text inference through the fixed local Ollama
`/api/chat` endpoint. A ROS timer publishes the resulting bounded JSON
hypothesis on `llm_diagnostics` without blocking monitor callbacks.
Transitions are rate-limited and only one pending observation is kept.
Stale results and malformed responses are dropped; model outages never
change `LinkMonitor` behavior. No actuation, navigation or ROS tool calls
are implemented. The model's text is unverified.

Offline `llm_diagnostics.py` can summarize a checked evidence-v1 report by
extracting existing `analysis.evidence_features` aggregates; it does not
send raw recording files or coordinates to the model. This is genuine
**LLM** inference, but not VLM/VLA processing or an official ROS successor.
See [LLM.md](LLM.md) for its precise limits.

## Optional read-only vision inference

The independent `VLMObserverNode` subscribes to ROS 2
`sensor_msgs/msg/CompressedImage` on `camera/image/compressed`.
It accepts bounded JPEG/PNG payloads, samples at most one frame every
configured interval, and delegates actual local Ollama inference to one worker
thread. The ROS timer publishes only a validated JSON scene description and
image fingerprint on `vlm_diagnostics`. New input frames are dropped while the
worker is busy; results older than the configured maximum age are discarded.
No raw image is republished, and no command topics/services exist in this node.

`vlm_diagnostics.py` offers a corresponding ROS-independent one-image CLI.
The observer does not automatically associate its sampled frames with
VERA-MOT tracks, telemetry timestamps, or GNSS state. The independent
text LLM and camera VLM paths are not a control system. See [VLM.md](VLM.md).

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
executed software checks are tracked separately in [VALIDATION.md](VALIDATION.md)
and the repository's CI jobs. Those synthetic checks are not field validation.
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

Version 0.3.1 imports `ClockType` from `rclpy.clock`, which exports it on both
distributions. Humble does not provide the separate `rclpy.clock_type` module
used by the initial Jazzy adapter. The first Humble CI run exposed that import
error; the shared import preserves steady-clock behavior without a
distribution-name branch. See the official clock implementations for
[Humble](https://github.com/ros2/rclpy/blob/humble/rclpy/rclpy/clock.py) and
[Jazzy](https://github.com/ros2/rclpy/blob/jazzy/rclpy/rclpy/clock.py).
