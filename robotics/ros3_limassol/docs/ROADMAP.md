# Development roadmap

The paper's 0.1.0 core, synthetic source and optional ROS 2 adapter are included.
Version 0.2.0 adds bounded streaming observation recording/replay, configurable
replay timeout, installed-wheel verification and CI jobs.

## Next steps

1. Run the Jazzy build, launch and DDS blackout/recovery test on a ROS workstation
   or CI runner. Retain the job result as transport evidence.
2. Add a receive-only live recorder using version-1 observations, with periodic
   ticks independent of incoming messages.
3. Exercise multiple robot namespaces and controlled delay, jitter, loss and
   restarts. Define timing ground truth before comparing repeated runs.
4. Add a receive-only MAVLink adapter with explicit message-to-schema mappings.
5. Evaluate a companion computer and a physical marine-robotics telemetry link.

Vehicle commands and autonomy are outside the current prototype. Arrival liveness
and measurement capture freshness remain distinct.
