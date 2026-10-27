# Development roadmap

The paper's 0.1.0 core, synthetic source and optional ROS 2 adapter are included.
Version 0.2.0 adds bounded streaming observation recording/replay, configurable
replay timeout, installed-wheel verification and CI jobs. Version 0.3.0 adds a
receive-only ROS recorder with independent silence ticks and a DDS-to-replay
blackout/recovery test.

The historical 0.2.0 main-branch [CI run](https://github.com/n0711/ROS3-Limassol/actions/runs/40036934415)
passed all four jobs, including the Jazzy build and original DDS test. Version
0.3.0 added live recorder checks; 0.3.1 added Humble compatibility. Consult
[validation](VALIDATION.md) and the [current CI runs](https://github.com/n0711/ROS3-Limassol/actions)
for results associated with each commit. Configured jobs are not proof of a pass.

## LLM diagnostics milestone

The optional local Ollama text interpreter is a **read-only observer** of
valid ROS3 receiver-arrival status and offline aggregate features. Model
availability does not affect liveness monitoring. It is not real-world
robot intelligence, a trained perception model, or VLA autonomy. To make
stronger research claims, compare several local models using held-out
non-sensitive observation traces, measured inference latency, and human-
reviewed diagnostic correctness while keeping autonomy and actuation out
of scope.

## Opt-in camera vision milestone

A separate ROS 2 compressed-image observer can invoke a **real local vision
model** and publish read-only scene descriptions. It is not calibrated
perception, tracker-validated recognition or Vision-Language-Action control.
Next measure end-to-end inference time with a declared local model, record
held-out evaluation data with consent, compare against a deterministic
perception baseline, and quantify camera/telemetry clock alignment before
attempting multimodal research claims. The existing telemetry monitor remains
independent of the VLM.

## Receiver-side camera/telemetry co-observation

An optional bounded status snapshot can accompany each sampled VLM
image diagnostic, using a shared observer-process monotonic callback
clock. The record reports observer-session/sample identity, last
status-delivery age and explicit no-synchronization flags. Expired status
is omitted, and no image or telemetry content is stored by this helper.
This is a **temporal co-observation**, not sensor exposure timing, ground
truth, physical robot identity or VERA-MOT track association.

Next: independently measure camera capture delay, status publication
delay and the clock-offset/error bounds across recording and camera
machines, then design a versioned alignment contract before asserting
multimodal fusion.

## Next steps

1. Retain recorder CI evidence, then collect a shareable ROS recording on a
   workstation with the intended publisher. Document the receiver configuration,
   independently known outage times and unrecordable-payload count.
2. ~~Exercise multiple robot namespaces and controlled delay, jitter, loss and
   restarts. Define timing ground truth before comparing repeated runs.~~
   Synthetic, seeded version added ([IMPAIRMENT.md](IMPAIRMENT.md)). Open
   question it raised: whether late in-session samples should refresh
   liveness instead of counting as rejected under jitter.
3. ~~Add a receive-only MAVLink adapter with explicit message-to-schema mappings.~~
   Initial UDP adapter added ([MAVLINK.md](MAVLINK.md)) and run against
   ArduPilot Rover 4.6.3 SITL with scripted outages ([VALIDATION.md](VALIDATION.md)).
   Next: MAVLink 2 signature verification before any radio link, and possibly
   `GPS_RAW_INT` fix quality. PX4 SITL is not yet covered.
4. Evaluate a companion computer and a physical marine-robotics telemetry link.

Vehicle commands and autonomy are outside the current prototype. Arrival liveness
and measurement capture freshness remain distinct.
