# Development roadmap

The paper's 0.1.0 core, synthetic source and optional ROS 2 adapter are included.
Version 0.2.0 adds bounded streaming observation recording/replay, configurable
replay timeout, installed-wheel verification and CI jobs. Version 0.3.0 adds a
receive-only ROS recorder with independent silence ticks and a DDS-to-replay
blackout/recovery test.

The 0.2.0 main-branch [CI run](https://github.com/n0711/ROS3-Limassol/actions/runs/40036934415)
passed all four jobs, including the Jazzy build and original DDS test. Version
0.3.0 adds recorder checks; consult its own PR checks for their execution status.

## Next steps

1. Retain recorder CI evidence, then collect a shareable ROS recording on a
   workstation with the intended publisher. Document the receiver configuration,
   independently known outage times and unrecordable-payload count.
2. Exercise multiple robot namespaces and controlled delay, jitter, loss and
   restarts. Define timing ground truth before comparing repeated runs.
3. Add a receive-only MAVLink adapter with explicit message-to-schema mappings.
4. Evaluate a companion computer and a physical marine-robotics telemetry link.

Vehicle commands and autonomy are outside the current prototype. Arrival liveness
and measurement capture freshness remain distinct.
