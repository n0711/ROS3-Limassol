# SPDX-License-Identifier: Apache-2.0
"""Read-only SimReady asset and ROS3 receiver-recording provenance bundle.

This module does not run Isaac Sim, load USD scenes, or synchronize cameras.
Asset and simulator metadata are caller declarations until independently checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

from .evidence import build_evidence
from .telemetry import validate_robot_id

MAX_MANIFEST_BYTES = 16_384
IDENT = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
DATASET = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
REVISION = re.compile(r"[a-f0-9]{40}\Z")
TOPIC = re.compile(r"/[A-Za-z0-9_/]{1,160}\Z")
LICENSE = re.compile(r"[A-Za-z0-9_.+() -]{1,80}\Z")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"invalid manifest number: {value}")


def validate_manifest(raw: bytes):
    """Validate syntax only: declared metadata are not independently attested."""
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest must be UTF-8 bytes up to 16384 bytes")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid manifest UTF-8/JSON") from exc
    required = {"experiment_version", "experiment_id", "simulator", "ros_distro",
                "robot_id", "asset_dataset", "asset_revision", "asset_path",
                "asset_license", "asset_sha256", "camera_topic", "telemetry_topic"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("manifest fields must exactly match experiment version 1")
    if type(data["experiment_version"]) is not int or data["experiment_version"] != 1:
        raise ValueError("experiment_version must be integer 1")
    if not isinstance(data["experiment_id"], str) or not IDENT.fullmatch(data["experiment_id"]):
        raise ValueError("invalid experiment_id")
    if data["simulator"] != "isaac-sim" or data["ros_distro"] not in ("humble", "jazzy"):
        raise ValueError("expected isaac-sim and ROS 2 humble or jazzy")
    validate_robot_id(data["robot_id"])
    if not isinstance(data["asset_dataset"], str) or not DATASET.fullmatch(data["asset_dataset"]):
        raise ValueError("invalid asset_dataset")
    if not isinstance(data["asset_revision"], str) or not REVISION.fullmatch(data["asset_revision"]):
        raise ValueError("asset_revision must be a 40-character commit hash")
    if not isinstance(data["asset_sha256"], str) or not SHA256.fullmatch(data["asset_sha256"]):
        raise ValueError("invalid asset_sha256")
    asset_path = data["asset_path"]
    if not isinstance(asset_path, str) or not 1 <= len(asset_path) <= 240 or "\\" in asset_path:
        raise ValueError("invalid asset_path")
    path = PurePosixPath(asset_path)
    if (path.is_absolute() or any(part in (".", "..") for part in asset_path.split("/"))
            or "//" in asset_path or path.suffix.lower() not in (".usd", ".usda", ".usdc", ".usdz")
            or any(ord(ch) < 32 for ch in asset_path)):
        raise ValueError("asset_path must be a relative USD asset path without traversal")
    if not isinstance(data["asset_license"], str) or not LICENSE.fullmatch(data["asset_license"]):
        raise ValueError("invalid declared asset_license")
    for field in ("camera_topic", "telemetry_topic"):
        topic = data[field]
        if not isinstance(topic, str) or not TOPIC.fullmatch(topic) or "//" in topic:
            raise ValueError(f"invalid {field}")
    if not data["camera_topic"].endswith("/compressed"):
        raise ValueError("camera_topic must identify an existing compressed-image topic")
    return data


def sha256_stream(stream):
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(1024 * 1024)
        if not isinstance(chunk, bytes):
            raise ValueError("asset stream must be binary")
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


MAX_CAMERA_REPORT_BYTES = 32768


def validate_camera_report(raw: bytes, *, expected_topic: str):
    """Check bounded format and topic agreement, not the real camera's origin."""
    if not isinstance(raw, bytes) or len(raw) > MAX_CAMERA_REPORT_BYTES:
        raise ValueError("camera report must be bytes no longer than 32768")
    try:
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("invalid camera report UTF-8/JSON") from exc
    if not isinstance(report, dict):
        raise ValueError("camera report must be an object")
    if (type(report.get("camera_receiver_report_version")) is not int
            or report["camera_receiver_report_version"] != 1
            or report.get("source") != "ros2-compressed-image-receiver"
            or report.get("topic") != expected_topic):
        raise ValueError("wrong camera report version, source, or topic")
    fields = ("max_frames", "received_frames", "compatible_jpeg_png_headers",
              "unsupported_h264_hevc_frames", "invalid_or_oversized_frames",
              "oversized_frames", "received_payload_bytes")
    counts = {}
    for name in fields:
        value = report.get(name)
        if type(value) is not int or value < 0:
            raise ValueError("invalid camera report counter: " + name)
        counts[name] = value
    limit, received = counts["max_frames"], counts["received_frames"]
    if not 1 <= limit <= 1000 or received > limit:
        raise ValueError("camera sample limit or count invalid")
    if (sum(counts[k] for k in ("compatible_jpeg_png_headers",
                               "unsupported_h264_hevc_frames",
                               "invalid_or_oversized_frames")) != received
            or counts["oversized_frames"] > counts["invalid_or_oversized_frames"]):
        raise ValueError("camera report counters do not reconcile")
    codec_counts = report.get("codec_declarations")
    keys = ("jpeg", "png", "h264", "hevc", "other")
    if (not isinstance(codec_counts, dict) or set(codec_counts) != set(keys)
            or any(type(codec_counts[k]) is not int or codec_counts[k] < 0 for k in keys)
            or sum(codec_counts.values()) != received
            or counts["compatible_jpeg_png_headers"] > codec_counts["jpeg"] + codec_counts["png"]
            or counts["unsupported_h264_hevc_frames"] > codec_counts["h264"] + codec_counts["hevc"]):
        raise ValueError("inconsistent camera codec declarations")
    reason = report.get("termination_reason")
    if reason not in ("max_frames", "timeout") or (reason == "max_frames" and received != limit):
        raise ValueError("invalid camera probe termination")
    flags = report.get("claims")
    expected_flags = {
        "camera_topic_messages_observed": received > 0,
        "jpeg_png_decoder_success_verified": False,
        "vlm_model_inference_verified": False,
        "image_capture_timestamps_verified": False,
        "isaac_sim_origin_verified": False,
        "simready_asset_loaded_verified": False,
        "time_alignment_verified": False,
        "actuation_authority": False,
    }
    if not isinstance(flags, dict) or flags != expected_flags:
        raise ValueError("unverified camera claims cannot be elevated")
    first = report.get("first_receiver_monotonic_s")
    last = report.get("last_receiver_monotonic_s")
    span = report.get("observed_receiver_span_s")
    if received == 0:
        if any(x is not None for x in (first, last, span)):
            raise ValueError("no-frame camera report must have null time values")
    else:
        if (any(type(x) not in (float, int) or not math.isfinite(x) for x in (first, last, span))
                or first < 0 or last < first or span < 0
                or not math.isclose(last - first, span, rel_tol=1e-8, abs_tol=1e-6)):
            raise ValueError("invalid receiver-monotonic observation interval")
    return {
        "source": "declared-camera-probe-report",
        "report_sha256": hashlib.sha256(raw).hexdigest(),
        "topic": expected_topic,
        "received_frames": received,
        "compatible_jpeg_png_headers": counts["compatible_jpeg_png_headers"],
        "unsupported_h264_hevc_frames": counts["unsupported_h264_hevc_frames"],
        "invalid_or_oversized_frames": counts["invalid_or_oversized_frames"],
        "observations_self_consistent": True,
        "ros2_delivery_independently_verified": False,
        "simulator_origin_verified": False,
    }


def build_simready_evidence(manifest_bytes, recording_stream, asset_stream=None, *, camera_report_bytes=None):
    """Bind hashes to receiver arrival evidence; never infer simulator execution."""
    manifest = validate_manifest(manifest_bytes)
    observed_asset_hash = sha256_stream(asset_stream) if asset_stream is not None else None
    if observed_asset_hash is not None and observed_asset_hash != manifest["asset_sha256"]:
        raise ValueError("local USD asset SHA-256 does not match declared asset_sha256")
    telemetry = build_evidence(recording_stream, robot_id=manifest["robot_id"])
    camera = (validate_camera_report(camera_report_bytes, expected_topic=manifest["camera_topic"])
              if camera_report_bytes is not None else None)
    return {
        "simready_experiment_report_version": 1,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "experiment_id": manifest["experiment_id"],
        "simulator_declared": manifest["simulator"],
        "ros_distro_declared": manifest["ros_distro"],
        "camera_topic_declared": manifest["camera_topic"],
        "telemetry_topic_declared": manifest["telemetry_topic"],
        "asset": {
            "dataset_declared": manifest["asset_dataset"],
            "revision_declared": manifest["asset_revision"],
            "relative_path_declared": manifest["asset_path"],
            "license_declared": manifest["asset_license"],
            "sha256_declared": manifest["asset_sha256"],
            "local_bytes_sha256_verified": observed_asset_hash is not None,
        },
        "receiver_evidence": telemetry,
        "camera_receiver_evidence": camera,
        "claims": {
            "simulator_executed_verified": False,
            "usd_asset_loaded_in_scene_verified": False,
            "asset_license_verified": False,
            "camera_frame_capture_alignment_verified": False,
            "camera_or_vlm_accuracy_verified": False,
            "physical_robot_validation": False,
            "actuation_authority": False,
        },
        "interpretation": (
            "Provenance bundle for a declared Isaac Sim experiment and an independently "
            "parsed ROS3 receiver recording. Local file hashing checks bytes only; "
            "the manifest cannot prove those bytes were loaded by the simulator, "
            "nor that a camera, ROS bridge, VLM, or robot ran. Receiver reports do "
            "not measure end-to-end latency, capture freshness, or robot safety."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="experiment manifest v1 JSON")
    parser.add_argument("recording", help="existing ROS3 receiver JSONL recording")
    parser.add_argument("--asset-file", help="optional locally obtained USD file to verify SHA-256")
    parser.add_argument("--camera-report", help="optional bounded ROS2 camera probe report JSON")
    args = parser.parse_args(argv)
    try:
        with Path(args.manifest).open("rb") as manifest_file:
            manifest_bytes = manifest_file.read(MAX_MANIFEST_BYTES + 1)
        camera_bytes = None
        if args.camera_report:
            with Path(args.camera_report).open("rb") as camera_file:
                camera_bytes = camera_file.read(MAX_CAMERA_REPORT_BYTES + 1)
        with Path(args.recording).open("rb") as recording_file:
            if args.asset_file:
                with Path(args.asset_file).open("rb") as asset_file:
                    output = build_simready_evidence(
                        manifest_bytes, recording_file, asset_file,
                        camera_report_bytes=camera_bytes,
                    )
            else:
                output = build_simready_evidence(
                    manifest_bytes, recording_file, camera_report_bytes=camera_bytes,
                )
        print(json.dumps(output, indent=2, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
