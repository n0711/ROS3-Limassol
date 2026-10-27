# ROS3 local VLM camera observer (experimental)

This is **actual optional vision-language inference** over a ROS 2 camera image,
not a manifest of VLM outputs. The opt-in `vlm_observer` subscribes to
`sensor_msgs/msg/CompressedImage`, samples one frame at a controlled rate,
and sends only that image with a fixed analysis prompt to a separately running
**local Ollama vision model**.

It publishes a read-only JSON description on a distinct ROS 2 topic.
The VLM never sends commands, drives navigation, decides vehicle safety, or
changes telemetry monitoring. ROS3-Limassol is an independent research
application on ROS 2, not an official ROS 3 distribution.

## 1. Run real local inference

Install [Ollama](https://ollama.com/) independently and select a
**vision-capable** local model. For example, `gemma3:4b` supports image input;
the 1B variant is text-only. Download on your own machine:

```bash
ollama pull gemma3:4b
```

The local API must be running on `127.0.0.1:11434`. This repository does not
download models, start Ollama, or require any cloud inference. The VLM client
uses the same local-only HTTP adapter as the text LLM. Models may be large and
need adequate RAM/VRAM. See [Ollama vision API](https://docs.ollama.com/capabilities/vision).

For **one existing, authorized JPEG or PNG file**, from the
`robotics/ros3_limassol/` package directory:

```bash
python -m ros3_limassol.vlm_diagnostics --image frame.jpg --model gemma3:4b
```

The file is inspected in memory; only a bounded single image is passed to
the local model. The file is not copied into the output or written to disk
by this module. Treat the source camera and model process as privacy-sensitive.

## 2. Use a ROS 2 compressed camera topic

Install ROS 2 **Humble / Ubuntu 22.04** or **Jazzy / Ubuntu 24.04** and build
the Python package as shown in the [package guide](../README.md). After
sourcing your matching ROS distribution and colcon installation, run from
the repository root:

```bash
ros2 launch ros3_limassol vlm_observer.launch.py model:=gemma3:4b camera_topic:=/camera/image_raw/compressed
```

The `camera_topic` argument must be an existing topic of type
`sensor_msgs/msg/CompressedImage` containing JPEG or PNG payloads. The
default relative topic is
`/limassol/usv01/camera/image/compressed`. There is **no camera driver**
or image publisher bundled with this launch file.

See the resulting JSON descriptions with:

```bash
ros2 topic echo /limassol/usv01/vlm_diagnostics std_msgs/msg/String
```

The launch accepts `robot_id:=usv02` to select another namespace and
`min_interval_s:=10.0`, `timeout_s:=20.0`, and
`max_result_age_s:=30.0`, and `max_status_age_s:=1.0`. The observer is disabled until deliberately
launched. It subscribes best-effort with depth 1, performs inference in one
worker thread, and drops frames while busy or within the minimum interval.
Expired results are not published as current. There is no frame queue,
camera image recording, ROS command publisher or control integration.

## 3. Input and output boundaries

- Accepts JPEG or PNG compressed data, at most **512 KiB per frame**.
- Uses header-level checks for pixel dimensions (maximum 4096 x 4096 and
  16,777,216 pixels); it **does not** fully decode or authenticate an image.
- Uses base64 in a `POST /api/chat` request to `127.0.0.1:11434`, with
  `stream: false` and structured JSON output.
- Publishes `scene_summary`, up to four `visible_features`, and up to
  three `uncertainties`, plus image format/dimensions, SHA-256 image
  fingerprint, model name, robot namespace, and processing age.
- Does **not** publish raw image data, feature maps, bounding boxes,
  object tracks, camera pose, detection confidence, or actions.
- The SHA-256 fingerprint shows input-byte identity, **not** camera
  authenticity, timing alignment, or provenance.

An image description is an **unverified hypothesis**: the VLM may hallucinate
features or miss important objects. No depth, calibrated geometry, GNSS-denied
localization, autonomous behavior, reliability or physical-platform
validation is established.

## 4. How the research modules fit together

- `LinkMonitor`: authoritative **receiver-arrival observation only**.
- `llm_diagnostics`: local **text-model** interpretation of link status.
- `vlm_observer`: local **vision-model** interpretation of one sampled image.
- `analysis.py`: statistical comparison of offline telemetry evidence.
- `multimodal.py`: bundles *independent* telemetry, VERA-MOT, and declared
  VLM evidence, without synchronized fusion or vehicle control.

The VLM observer additionally subscribes to the matching
`/limassol/<robot_id>/link_status` topic (reliable, depth 1). On each
**accepted sampled frame callback**, it snapshots the most recently
delivered validated link status **only if it arrived at this process within
`max_status_age_s`**. If not available or too old, the associated status
is explicitly `null`. The status snapshot is frozen before model inference:
a later link recovery does not rewrite the context of an earlier frame.

The JSON `observation_context` contains `observer_session_id` and
`sample_index` for local sample identity, `frame_callback_offset_s`
relative to this observer's own first callback, and
`status_delivery_age_at_frame_s` measured from the **same process's
monotonic callback clock**. It includes the bounded
`status_at_frame_callback` state/counters when a recently delivered
status exists. It marks camera-capture time, sender clock alignment,
physical robot identity and VERA-MOT track alignment **unverified**.
This is receiver-side temporal co-observation, **not sensor-level
synchronization, causality or VLM ground truth**.

A future synchronized fusion interface still requires camera calibration,
independent clock-ground-truth data, provenance and held-out evaluations.
A matching ROS namespace is not proof of shared physical robot identity.

## 5. Verification

From `robotics/ros3_limassol/`:

```bash
python -m unittest discover -s tests -v
```

The standard-library tests mock Ollama and validate request construction,
image bounds, strict response parsing, and rejection behavior. Humble and
Jazzy CI build `sensor_msgs`, verify the launch and exercise a real DDS topic
roundtrip with a **fake** model response, now also checking latest-status
receipt at the camera callback. No real model weights or physical
camera are exercised in CI. Run model-specific and field tests before
claiming visual recognition accuracy or on-board real-time capability.

See also [local LLM status diagnostics](LLM.md),
[ROS architecture](ARCHITECTURE.md) and [validation record](VALIDATION.md).
