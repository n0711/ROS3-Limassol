# SPDX-License-Identifier: Apache-2.0
"""Read-only multimodal research bundle: ROS3 telemetry + VERA-MOT evidence.

Evidence is bundled, not time-synchronized or fused into navigation/actuation.
Optional declared external-VLM annotations are not verified model inference.
"""
import argparse
import json
import math
import re

from .analysis import evidence_features, load_json, score_report

SHA = re.compile(r"[0-9a-f]{64}\Z")
SEQ = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
VERSION = 1


def _natural(obj, key, minimum=0):
    val = obj.get(key)
    if type(val) is not int or val < minimum:
        raise ValueError(f"{key} must be integer >= {minimum}")
    return val


def _hash(obj, key):
    value = obj.get(key)
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError(f"invalid {key}")
    return value


def combine_evidence(telemetry, vision, *, vlm=None, anomaly_model=None):
    """Compose independent, provenance-linked reports without clock assumptions."""
    tel = evidence_features(telemetry)
    if type(vision.get("vision_report_version")) is not int or vision["vision_report_version"] != 1:
        raise ValueError("expected VERA-MOT vision_report_version 1")
    if vision.get("source") != "vera-mot" or vision.get("parsed_to_eof") is not True:
        raise ValueError("expected complete VERA-MOT track evidence")
    seq = vision.get("sequence")
    if not isinstance(seq, str) or not SEQ.fullmatch(seq):
        raise ValueError("invalid vision sequence")
    mot_digest = _hash(vision, "mot_sha256")
    rows = _natural(vision, "track_observation_rows", 1)
    ids = _natural(vision, "distinct_sequence_local_track_ids", 1)
    frames = _natural(vision, "frames_with_output", 1)
    first = _natural(vision, "first_output_frame", 1)
    last = _natural(vision, "last_output_frame", 1)
    if ids > rows or frames > rows or first > last or frames > last - first + 1:
        raise ValueError("inconsistent MOT counters")
    mean = vision.get("mean_rows_per_output_frame")
    if type(mean) not in (int, float) or not math.isfinite(mean) or (
            not math.isclose(mean, rows / frames, rel_tol=1e-9)):
        raise ValueError("inconsistent mean_rows_per_output_frame")
    output = {
        "multimodal_report_version": VERSION,
        "telemetry": {
            "robot_id": tel["robot_id"],
            "recording_sha256": tel["recording_sha256"],
            "features": tel["features"],
        },
        "vision": {
            "source": "vera-mot",
            "sequence": seq,
            "mot_sha256": mot_digest,
            "track_observation_rows": rows,
            "distinct_sequence_local_track_ids": ids,
            "frames_with_output": frames,
        },
        "anomaly_assessment": (
            score_report(anomaly_model, telemetry) if anomaly_model is not None else None),
        "vlm": None,
        "alignment_verified": False,
        "robot_to_sequence_mapping_verified": False,
        "navigation_authority": False,
        "interpretation": (
            "Independent offline receiver and tracking-output summaries only. "
            "No common clock, GNSS-denied localization, identity correctness, "
            "VLM accuracy, causal agreement, vehicle health or safety proven."
        ),
    }
    if vlm is not None:
        if type(vlm.get("vlm_report_version")) is not int or vlm["vlm_report_version"] != 1:
            raise ValueError("expected VLM annotation summary version 1")
        if vlm.get("source") != "declared-external-vlm-output" or vlm.get("sequence") != seq:
            raise ValueError("VLM annotation source or sequence mismatches VERA")
        manifest = _hash(vlm, "manifest_sha256")
        _hash(vlm, "prompt_sha256")
        annotations = _natural(vlm, "annotated_frames", 1)
        model_id = vlm.get("model_id")
        revision = vlm.get("model_revision")
        if not all(isinstance(v, str) and 0 < len(v) <= 128 for v in (model_id, revision)):
            raise ValueError("VLM model provenance missing")
        tags = vlm.get("label_counts")
        if not isinstance(tags, dict) or len(tags) > 256 or any(
                not isinstance(tag, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", tag)
                or type(count) is not int or count < 0 or count > annotations
                for tag, count in tags.items()):
            raise ValueError("invalid VLM label histogram")
        output["vlm"] = {
            "source": "declared-external-vlm-output",
            "manifest_sha256": manifest,
            "model_id": model_id,
            "model_revision": revision,
            "annotated_frames": annotations,
            "label_counts": dict(sorted(tags.items())),
            "inference_verified": False,
        }
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("telemetry_report", help="ROS3 report-version-1 evidence JSON")
    parser.add_argument("vision_report", help="VERA-MOT vision-report-version-1 JSON")
    parser.add_argument("--vlm", help="optional declared VLM annotation summary")
    parser.add_argument("--anomaly-model", help="optional trained anomaly baseline JSON")
    args = parser.parse_args(argv)
    try:
        result = combine_evidence(
            load_json(args.telemetry_report), load_json(args.vision_report),
            vlm=load_json(args.vlm) if args.vlm else None,
            anomaly_model=load_json(args.anomaly_model) if args.anomaly_model else None,
        )
        print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
