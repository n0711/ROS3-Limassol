# SimReady and ROS3-Limassol: reproducible receiver-evidence experiment

**Status: provenance/validation scaffold only.** This change did not download an NVIDIA asset, run Isaac Sim, load a camera frame, execute a VLM, or validate a physical robot.

## What is connected

NVIDIA [SimReady Central](https://huggingface.co/datasets/nvidia/simready-assets) hosts simulation assets in OpenUSD. Isaac Sim can consume USD environments and publish ROS 2 camera topics using its ROS 2 Bridge. ROS3-Limassol currently offers: a synthetic USV telemetry publisher, a receive-only JSON telemetry recorder, and an optional independent CompressedImage/local-VLM observer. Installing an OpenUSD asset connects none of these automatically. The synthetic publisher is **not** an Isaac Sim adapter.

VERA-MOT produces separate tracking and VLM-manifest evidence; this repository does not establish cross-repository time synchronization or correct VLM predictions.

## First controlled experiment

1. Choose **one** publicly available, non-sensitive object asset from the linked collection. Inspect the **asset-specific** license, target simulation profile, and dependency files. Record the actual publisher dataset ID, immutable 40-character Hugging Face revision, the relative USD asset path and exact SHA-256. Do not download the entire 472 GB collection. An index's license does not automatically apply to all listed packages.
2. Using a separately installed Isaac Sim, make a local USD stage with a floor, the selected object, lighting and a simulated camera. Enable its ROS 2 Bridge and publish a suitable sensor_msgs/msg/CompressedImage topic, e.g. /camera/image_raw/compressed. Verify the type and QoS with ROS 2 tooling; preserve simulator version, camera calibration, stage files and run logs separately. No scene builder or Isaac runtime code is included here.
3. As an independent ROS3 **synthetic receiver-path baseline**, run ROS3's usv_demo.launch.py and record_telemetry.launch.py to produce run.jsonl. The original synthetic publisher generates std_msgs/msg/String JSON on /limassol/usv01/telemetry; Isaac Sim does **not** automatically publish that contract.
4. Optional: with locally installed Ollama/vision weights, run the existing ROS3 vlm_observer.launch.py using camera_topic:=/camera/image_raw/compressed. This is read-only sampling, not verified scene understanding or sensor time alignment.
5. After recording, validate the manifest and combine its asset metadata with a separate ROS3 receiver report as described below.

## Experiment manifest v1

Save the following as simready-manifest.json and replace ALL placeholders with the actual asset metadata before claiming a reproducible run. The zero commit/hash, object path and license are **illustrative placeholders**.

~~~json
{
  "experiment_version": 1,
  "experiment_id": "camera_scene_01",
  "simulator": "isaac-sim",
  "ros_distro": "humble",
  "robot_id": "usv01",
  "asset_dataset": "nvidia/simready-assets",
  "asset_revision": "0000000000000000000000000000000000000000",
  "asset_path": "REPLACE_WITH_REAL_RELATIVE_PATH.usd",
  "asset_license": "REVIEW_REQUIRED",
  "asset_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "camera_topic": "/camera/image_raw/compressed",
  "telemetry_topic": "/limassol/usv01/telemetry"
}
~~~

Compute the SHA-256 of the **individual USD file** (e.g. using sha256sum), and document texture/dependency revisions separately. A local file checksum alone cannot prove what asset the simulator loaded. A declared license is not independently verified.

From robotics/ros3_limassol/, once run.jsonl exists:

~~~sh
python -m ros3_limassol.evidence run.jsonl --robot-id usv01 > receiver-evidence.json
python -m ros3_limassol.simready_evidence simready-manifest.json run.jsonl \
    --asset-file /local/path/to/selected.usd > simready-report.json
~~~

The --asset-file parameter is optional. Without it, local_bytes_sha256_verified is false; with it, the tool hashes the file in chunks and rejects mismatches before printing JSON. **Shell output redirection can overwrite an old report even on CLI errors**; create a new output filename each time and preserve raw input files.

The generated report retains the manifest SHA-256, the selected asset's declared revision/path/license/topic, and ROS3's existing fully parsed receiver evidence and recording SHA-256. It explicitly marks simulation execution, asset loading, sensor synchronization, image/VLM accuracy, physical testing, and actuation authority as **unverified**.

## Acceptance matrix

| Criterion | Evidence needed | Status in this change |
| --- | --- | --- |
| Pinned revision, safe USD path, strict JSON keys | Local Python tests | Implemented; CI pending |
| Optional actual file SHA-256 | Streamed digest equality | Implemented; CI pending |
| ROS3 recording to EOF | Existing receiver evidence parser | Implemented; CI pending |
| Isaac Sim scene loads chosen asset | Runtime stage/log and independent observation | NOT DONE |
| ROS 2 compressed camera topic produces frames | Actual ROS topic observation, QoS | NOT DONE |
| Camera and receiver clocks aligned | Measured offset and uncertainty | NOT DONE |
| VERA-MOT or VLM accuracy | Annotated ground truth and held-out evaluation | NOT DONE |
| Physical field validity | Independently instrumented robot | NOT DONE |

## Next measured controls (future)

Keep the chosen USD revision and camera configuration fixed across (A) standalone ROS3 virtual-time baseline, (B) Isaac Sim scene with camera bridge and independent ROS3 synthetic telemetry, (C) temporary interruption of the **synthetic telemetry source**, and (D) synthetic source recovery. Use separate cameras, clocks, timestamps and test annotations before claiming image/fusion performance. ROS3 receiver transitions never alone establish packet-loss rates, one-way latency, camera freshness, or vehicle safety.

## References

- [NVIDIA collection](https://huggingface.co/datasets/nvidia/simready-assets)
- [NVIDIA SimReady Central documentation](https://docs.omniverse.nvidia.com/simready/latest/simready-central.html)
- [Isaac Sim](https://developer.nvidia.com/isaac/sim)

The ROS3 package code is Apache-2.0. No external USD asset, scene, or model weights are distributed in this repository; check each external asset's actual license before use.
