# Agent guide for ROS3-Limassol

Read this before changing the repository. It applies to every coding agent and
human contributor; `CONTRIBUTING.md` has the full workflow.

## What this repository is

Two separate components share one repository:

- **ROS3-Limassol** (`robotics/`): receiver-side telemetry arrival monitoring
  (`WAITING` / `HEALTHY` / `STALE`), recording, replay and evidence export.
  Python core in `robotics/ros3_limassol`, experimental Rust core in
  `robotics/ros3_core`. Apache-2.0.
- **LearnTwin** (`backend/`, `frontend/`, `learntwin/`): the original classroom
  and degree-planner app. MIT.

Keep each change within one component. Do not mix ROS3 and LearnTwin work in a
single pull request.

## Hard boundaries

- **Receive-only.** Never add code that sends vehicle commands, MAVLink
  messages, heartbeats, stream requests or actuation of any kind. Existing tests
  enforce this; do not weaken them.
- **`HEALTHY` means receiver arrival recency only.** Never describe it as vehicle
  safety, sensor freshness, link quality or navigation accuracy.
- **LLM/VLM output is unverified diagnostic text.** It must stay read-only and
  independent of the liveness monitor, and it must never feed navigation.
- **The Python core stays standard-library only** and runnable without ROS.
  ROS 2 (Humble/Jazzy) integration remains optional.

## Before opening a pull request

1. Branch from current `main`; one focused change per branch.
2. ROS3 changes, from `robotics/ros3_limassol`:
   `python -m unittest discover -s tests -v`
3. Rust core changes, from `robotics/ros3_core`: `cargo fmt --check`,
   `cargo clippy --all-targets -- -D warnings`, `cargo test --locked`.
4. LearnTwin frontend, from `frontend/`: `npm test`, `npm run lint`,
   `npm run build`. LearnTwin Python, from the repo root: `python -m pytest`.
5. Run `git diff --check`.
6. Update the guide that documents the behaviour you changed (README, the
   relevant file in `robotics/ros3_limassol/docs/`, `KNOWN_ISSUES.md`).

In the PR description, state what you ran and the result. Report unrun checks
(no ROS install, no hardware, no model) as **not run**, never as passed.
Simulated, synthetic or mocked results are not field validation.

## Never commit

Virtual environments, `.env` files (use `.env.example`), recordings
(`*.jsonl`), databases, `*.ros3-key` keys, build output, model weights, student
data or personal academic records.

## Current priorities

1. Validate the MAVLink bridge against ArduPilot or PX4 SITL and record the
   result in `robotics/ros3_limassol/docs/VALIDATION.md`. Do not claim it before it has been run.
2. Multiple robot namespaces with controlled delay, jitter, loss and restarts
   (roadmap step 2).
3. Physical link evaluation: companion computer and marine telemetry link
   (roadmap step 4).

Prefer these over new LLM/VLM features. Ask the maintainer before starting work
outside this list, or before any change to licences, the telemetry schema
version or the recording format.
