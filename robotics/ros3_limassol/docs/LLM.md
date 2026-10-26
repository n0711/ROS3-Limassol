# Local LLM diagnostics — experimental ROS3 module

This module is a **real local inference integration**, not a placeholder and not
a declared-VLM evidence parser. It uses the Ollama `POST /api/chat` API with
`stream: false` and a strict JSON response format. You must install and run
your own local model; **CI does not download model weights or run an actual model**.

ROS3-Limassol remains an experimental application built on ROS 2 Humble/Jazzy,
not an official ROS 3 distribution. The LLM module **observes** receiver-arrival
status; it cannot navigate, actuate, issue commands or override the monitor.
The Python liveness monitor runs independently when the model is unavailable.

## 1. Start a local model

Install [Ollama](https://ollama.com/) independently and make a suitable local
chat model available, for example:

```bash
ollama pull llama3.2
```

Ollama must be running locally on `127.0.0.1:11434`. ROS3 never starts
Ollama, pulls a model, or sends data to a hosted API. The client has a fixed
loopback URL, ignores proxy environment settings, enforces a timeout and
limits the request and response sizes.

## 2. Offline inference from existing ROS3 evidence

From `robotics/ros3_limassol/` with Python 3.10+:

```bash
python -m ros3_limassol.demo --record trial.jsonl
python -m ros3_limassol.evidence trial.jsonl > evidence.json
python -m ros3_limassol.llm_diagnostics --evidence evidence.json --model llama3.2 > explanation.json
```

Recording refuses to overwrite an existing file. The evidence exporter
validates input before summarizing receiver observations. The LLM receives
only the seven validated link-status fields and four aggregate observation
features. Raw telemetry, GPS coordinates, sensor payloads and recordings
are **not** transmitted to the model.

Alternatively, supply an existing `LinkStatus` JSON object via
`--status-file status.json`. Use `--timeout 8` to bound local inference.

## 3. ROS 2 topic integration

Install and source ROS 2 Humble (Ubuntu 22.04) or Jazzy (Ubuntu 24.04).
Build and source the package as in the [package guide](../README.md).
Then from the **repository root**, with the model server running:

Terminal 1 — synthetic publisher plus deterministic link observer:

```bash
ros2 launch ros3_limassol usv_demo.launch.py
```

Terminal 2 — optional **read-only** LLM observer:

```bash
ros2 launch ros3_limassol llm_diagnostics.launch.py model:=llama3.2
```

Terminal 3 — inspect diagnostics:

```bash
ros2 topic echo /limassol/usv01/llm_diagnostics std_msgs/msg/String
```

The adapter subscribes to `/limassol/usv01/link_status` and publishes
`/limassol/usv01/llm_diagnostics`. These are `std_msgs/msg/String`
topics containing bounded JSON. Its default namespace is robot `usv01`;
change `robot_id:=usv02` to observe a matching publisher/monitor.

The adapter queues at most the most recent state transition, uses a
single asynchronous inference worker and a minimum 3-second interval
(`min_interval_s`) so ROS subscription callbacks are not blocked by a
model request. A stale answer for a superseded state is suppressed.
When Ollama is unavailable or returns invalid JSON, a warning is logged,
not a fabricated report. This is **not** a real-time guarantee.

## Response contract

The model generates a short JSON object with `summary`,
`possible_causes` (at most three), and `uncertainties` (at most three).
Each field is bounded and validated. The ROS3 wrapper adds the model
name, observed state, `model_output_verified: false`,
`navigation_authority: false` and `actuation_authority: false`.
The application never accepts LLM tool calls or routes its text into
vehicle control.

**An LLM response is an unverified hypothesis, not sensor-grounded fact.**
`HEALTHY` means recent accepted receiver telemetry; it does not
establish robot health, capture freshness, delivery rate, network delay,
safety, scene understanding or GNSS-denied localization.

## Relation to VERA-MOT and VLMs

The existing `multimodal.py` bundles independent VERA-MOT tracking
summary and externally declared VLM annotations with provenance checks.
It **does not run a VLM** or establish synchronized time, shared identity,
or navigation correctness. This LLM module performs **text-only** local
inference over ROS3 state/evidence, not VLM or Vision-Language-Action
(VLA) control. They are separate research interfaces.

## What CI establishes

- Python tests exercise a mocked Ollama response, strict JSON validation,
  privacy/data-bounding, and inference failures.
- ROS Humble and Jazzy tests exercise status subscription to a fake LLM
  and an independent diagnostics topic. Package tests verify launch syntax.
- Installed package checks verify that `llm_diagnostics` is discoverable.

A passing CI run **does not establish real model accuracy, field timing,
real sensor reliability, or the availability of a local Ollama server**.
Before operational research claims, evaluate a real local model,
measure diagnostic latency against independent ground truth, and test
disconnect/reconnect behavior outside control loops.

Source for the API contract:
[Ollama chat API](https://docs.ollama.com/api).
