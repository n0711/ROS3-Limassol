# ROS3-Limassol: 2026 robotics skills milestone checklist

Updated **2026-11-07** against `main` commit
`e9d2ac282471f9edd4f9eeb2b5eece49bf196699`.
Each box is an acceptance gate, not a claim of mastery or full system
deployment. Code presence below was checked; previous test evidence was
not replayed in this isolated workspace.

## Domain 1 - Perception and sensing

- [x] Existing optional ROS 2 compressed-image observer and bounded
  receiver-side status co-observation identified.
- [x] **H21:** offline conditional sensor-clock age bounds, guarded JSON
  CLI, 13 focused local tests and documentation.
- [ ] **H22:** measure independent timestamp and offset uncertainty on a
  real camera/companion device, including provenance and clock drift.
- [ ] **H23:** bounded multisensor quality evidence, calibration,
  timestamps, uncertainty and missing-data handling.

## Domain 2 - Localization and state estimation

- [ ] **H24:** define frames, sensor calibrations, GNSS/IMU/odometry data
  and independently measured reference trajectory.
- [ ] **H25:** evaluate offline EKF/SLAM or odometry baselines using
  held-out trajectory error, failure, and recovery metrics.
- [ ] **H26:** propose a ROS 2 estimator adapter only after evidence review.
  Arrival liveness must not be relabeled as pose confidence.

## Domain 3 - Planning and control

- [ ] **H27:** define separate authenticated/authorized command contract,
  freshness deadlines, manual override, safe state and fail-closed rules.
- [ ] **H28:** compare PID/MPC or path planning in isolated simulation.
- [ ] **H29:** independently review control-capable physical interfaces.
  `HEALTHY` never establishes permission to command a vehicle.

## Domain 4 - Robot learning and foundation models

- [x] Existing optional read-only LLM/VLM diagnostics identified,
  **not** a deployed VLA controller.
- [ ] **H30:** define consented held-out vision set, accuracy metrics
  and deterministic baselines with inference timing.
- [ ] **H31:** evaluate VLA candidates in an action-disabled sandbox/replay
  with scored hypothetical decisions and clear refusal behavior.
- [ ] **H32:** report policy generalization and failure analysis.

## Domain 5 - Simulation and validation

- [x] Existing replay, synthetic impairment/outage, BER and H13-H20
  tools identified, not rerun in this workspace.
- [x] **H21 focused local check:** 13 unittest cases passed and compileall
  succeeded under Python 3.13.5.
- [x] **H21 repository CI gate:** Python 3.10/3.12 (Linux), Python 3.12
  (Windows), wheel verification, ROS Humble/Jazzy, and Rust core passed.
  See [ROS3-Limassol run 42403210258](https://github.com/n0711/ROS3-Limassol/actions/runs/42403210258)
  and [Rust run 42403210271](https://github.com/n0711/ROS3-Limassol/actions/runs/42403210271). Human review pending.
- [ ] **H22 measurement gate:** replay paired timestamps from independent
  calibrated capture/receiver devices and report interval violations.
- [ ] **H33:** separate SITL, HIL, and field trials with raw provenance.

## Domain 6 - Software, embedded and hardware

- [x] Existing ROS 2 Python package, separate experimental Rust core,
  MAVLink receive bridge and CI identified.
- [ ] **H34:** memory/CPU/latency bounds on resource-limited hosts.
- [ ] **H35:** Raspberry Pi/companion integration and lifecycle recovery
  with timestamps and independent watchdog observations.
- [ ] **H36:** security and authorization review of future opt-in
  bidirectional communication.

## H21 evidence log

- **Date:** 2026-11-07.
- **Aim:** propagate independently declared receiver/source clock-offset
  bounds into conservative conditional capture age intervals.
- **Code:** `ros3_limassol/clock_bounds.py`.
- **Tests:** `tests/test_clock_bounds.py`, 13 focused tests passed locally;
  Python compileall passed locally.
- **Explanation:** `docs/CLOCK_ALIGNMENT_H21.md`.
- **GitHub CI passed:** core (Linux/Windows), wheel, Humble and Jazzy jobs,
  plus separate Rust workflow on the H21 PR head at first CI run.
- **Not run / not established:** independent PTP/PPS, hardware timestamps,
  real sensor delay, radio, field, localization or vehicle control.
- **Decision:** stay offline/read-only pending independent clock evidence.

For historical receiver tests and earlier synthetic work, see existing
`docs/VALIDATION.md` and H13-H20 reports. Do not restate older measurements
as validation of this new module.
