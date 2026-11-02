# ROS3-Limassol: Arduino USB Hardware Validation

Date: 2026-11-02
Status: H8, H9 and H10 passed
Environment: Raspberry Pi 3B, Ubuntu Server 22.04

## 1. Hardware

- Raspberry Pi 3B: receiver and ROS3 monitoring host
- Arduino Nano Every: telemetry source 1
- Arduino Mega 2560: telemetry source 2
- Connection: USB serial, 9600 baud
- Flight controller: not used
- Radio link: not used

## 2. Test configuration

Both Arduino boards transmitted heartbeat messages:

    ROS3,<device_id>,HEARTBEAT,<millis>

The experimental Python adapter converted valid heartbeat
messages into ROS3 telemetry envelopes.

Monitoring used the repository's LinkMonitor implementation.

Stale threshold: 3.0 seconds
Experiment duration: 90 seconds

Telemetry measurement fields not supplied by the Arduino
firmware were placeholders, not physical measurements.

## 3. Physical USB experiment

The Arduino Mega was disconnected while the Nano remained
connected.

Observed events:

| Time (s) | Event |
|---:|---|
| 0.00 | Nano USB opened |
| 0.00 | Mega USB opened |
| 0.10 | Nano became HEALTHY |
| 0.96 | Mega became HEALTHY |
| 19.63 | Mega USB disconnected |
| 22.05 | Mega became STALE |
| 44.77 | Mega USB reopened, session 2 |
| 45.72 | Mega returned to HEALTHY |

USB-loss-event to STALE interval: 2.42 seconds.
USB-open-event to HEALTHY interval: 0.95 seconds.

These are observed intervals, not worst-case guarantees.

No Nano STALE transition was reported during the experiment.

## 4. Recording and replay

Nano:
- Recording: 20261102T062027_nano.jsonl
- Accepted: 90
- Rejected: 0
- Replay: WAITING -> HEALTHY

Mega:
- Recording: 20261102T062027_mega.jsonl
- Accepted: 64
- Rejected: 0
- Replay: WAITING -> HEALTHY -> STALE -> HEALTHY

Replay commands, from robotics/ros3_limassol:

    python3 -m ros3_limassol.replay \
      /path/to/20261102T062027_nano.jsonl \
      --robot-id nano --stale-after 3

    python3 -m ros3_limassol.replay \
      /path/to/20261102T062027_mega.jsonl \
      --robot-id mega --stale-after 3

## 5. Recording integrity

Nano SHA-256:
dad01932b789332cb66e0ad89157b579890608d256b755f3c0d3d295630ee292

Mega SHA-256:
8a10dbc02ce4f618031adf21d0be640810e143164ea5e756ddc60ce72a86cb93

Recordings were generated outside the repository at:

    ~/projects/ros3-hardware/evidence/

The hashes identify the recordings but do not establish
that they have been independently archived.

## 6. Validation boundaries

Established:
- Physical USB heartbeat reception
- Independent monitoring of two serial sources
- Detection of Mega telemetry loss
- Automatic Mega USB reconnection
- Recovery to HEALTHY
- Replay of recorded observations

Not established:
- MAVLink flight-controller integration
- Radio-link reliability
- ROS 2 distributed transport performance
- Three-vehicle SITL validation
- Field deployment
- Worst-case detection or recovery guarantees

## 7. Conclusion

The experimental ROS3 Arduino USB adapter successfully
detected and recovered from a physical Mega USB
disconnection.

Recorded observations reproduced the monitoring state
transitions using the existing ROS3 replay implementation.

These findings are limited to the tested USB heartbeat
monitoring configuration.
