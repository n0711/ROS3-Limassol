# SPDX-License-Identifier: Apache-2.0
"""Offline, read-only statistical anomaly baseline for ROS3 evidence-v1 reports.

No ROS, vehicle commands, raw telemetry or external machine-learning packages.
Run `python -m ros3_limassol.analysis --help` for CLI usage.
"""
import argparse
import json
import math
from pathlib import Path
from statistics import median

FEATURE_VERSION = 1
MODEL_VERSION = 1
MIN_TRAINING_REPORTS = 5
MAX_TRAINING_REPORTS = 128
MAX_JSON_BYTES = 1_000_000
SCORE_THRESHOLD = 3.5
FEATURE_FLOORS = {
    "rejected_payload_fraction": 0.025,
    "silence_tick_fraction": 0.025,
    "observed_stale_changes_per_tick": 0.025,
    "max_tick_gap_over_timeout": 0.25,
}
INTERPRETATION = (
    "Exploratory receiver-observation outlier analysis, not GNSS integrity, "
    "packet loss, network delay, sensor freshness, reliability, or robot safety."
)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key: " + key)
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError("non-finite JSON number: " + value)


def load_json(path):
    """Load a bounded UTF-8 JSON object with duplicate-key rejection."""
    p = Path(path)
    with p.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("analysis JSON input exceeds 1 MB")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                       parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("analysis JSON input must be an object")
    return value


def _count(value, key):
    v = value.get(key)
    if type(v) is not int or v < 0:
        raise ValueError(key + " must be a nonnegative integer")
    return v


def _finite(value, key, positive=False):
    v = value.get(key)
    if type(v) not in (int, float) or not math.isfinite(v) or (
            v <= 0 if positive else v < 0):
        raise ValueError(key + " must be a finite " +
                         ("positive" if positive else "nonnegative") + " number")
    return float(v)


def evidence_features(report):
    """Validate evidence-v1 and extract only aggregate observation features."""
    if type(report.get("report_version")) is not int or report["report_version"] != 1:
        raise ValueError("expected evidence report_version 1")
    if report.get("recording_parsed_to_eof") is not True:
        raise ValueError("evidence was not fully parsed")
    digest = report.get("recording_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(
            c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid recording SHA-256")
    robot = report.get("robot_id")
    if not isinstance(robot, str) or not robot or len(robot) > 32:
        raise ValueError("missing or invalid robot_id")
    timeout = _finite(report, "stale_after_s", positive=True)
    total = _count(report, "observation_count")
    payload = _count(report, "payload_observation_count")
    silence = _count(report, "silence_tick_count")
    accepted = _count(report, "accepted")
    rejected = _count(report, "rejected")
    stale = _count(report, "observed_stale_change_count")
    changes = _count(report, "observed_state_change_count")
    if total != payload + silence or payload != accepted + rejected or stale > changes:
        raise ValueError("inconsistent evidence counters")
    if total == 0 or payload == 0:
        raise ValueError("cannot analyse a recording without observed payloads")
    gap = report.get("max_between_observation_gap_s")
    if gap is None and total == 1:
        gap = 0.0
    if gap is None:
        raise ValueError("missing observation gap")
    gap = _finite({"gap": gap}, "gap")
    features = {
        "rejected_payload_fraction": rejected / payload,
        "silence_tick_fraction": silence / total,
        "observed_stale_changes_per_tick": stale / total,
        "max_tick_gap_over_timeout": gap / timeout,
    }
    if any(not math.isfinite(v) for v in features.values()):
        raise ValueError("feature overflow")
    return {
        "feature_version": FEATURE_VERSION,
        "recording_sha256": digest,
        "robot_id": robot,
        "stale_after_s": timeout,
        "features": features,
        "interpretation": INTERPRETATION,
    }


def fit_baseline(reports):
    """Learn per-feature median/MAD from distinct, comparable evidence runs."""
    if not MIN_TRAINING_REPORTS <= len(reports) <= MAX_TRAINING_REPORTS:
        raise ValueError("baseline requires 5 to 128 evidence reports")
    rows = [evidence_features(r) for r in reports]
    first = rows[0]
    hashes = [r["recording_sha256"] for r in rows]
    if len(set(hashes)) != len(hashes):
        raise ValueError("training evidence contains duplicate recording hashes")
    if any(r["robot_id"] != first["robot_id"] or
           r["stale_after_s"] != first["stale_after_s"] for r in rows):
        raise ValueError("training evidence must share robot_id and stale_after_s")
    stats = {}
    for name in FEATURE_FLOORS:
        values = [r["features"][name] for r in rows]
        centre = median(values)
        spread = median([abs(v - centre) for v in values])
        stats[name] = {"median": centre, "mad": spread}
    return {
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "robot_id": first["robot_id"],
        "stale_after_s": first["stale_after_s"],
        "training_report_count": len(rows),
        "training_recording_sha256": sorted(hashes),
        "score_threshold": SCORE_THRESHOLD,
        "feature_stats": stats,
        "interpretation": INTERPRETATION,
    }


def score_report(model, evidence):
    """Score a held-out evidence report against an independent trained baseline."""
    row = evidence_features(evidence)
    if type(model.get("model_version")) is not int or model["model_version"] != MODEL_VERSION:
        raise ValueError("unsupported anomaly model_version")
    if type(model.get("feature_version")) is not int or model["feature_version"] != FEATURE_VERSION:
        raise ValueError("incompatible feature_version")
    if model.get("robot_id") != row["robot_id"] or (
            _finite(model, "stale_after_s", positive=True) != row["stale_after_s"]):
        raise ValueError("baseline robot_id or timeout differs from evidence")
    n = _count(model, "training_report_count")
    hashes = model.get("training_recording_sha256")
    if not MIN_TRAINING_REPORTS <= n <= MAX_TRAINING_REPORTS or (
            not isinstance(hashes, list) or len(hashes) != n or
            len(set(map(str, hashes))) != n or
            any(not isinstance(h, str) or len(h) != 64 or
                any(c not in "0123456789abcdef" for c in h) for h in hashes)):
        raise ValueError("invalid model training provenance")
    if row["recording_sha256"] in hashes:
        raise ValueError("holdout evidence must differ from training recordings")
    threshold = _finite(model, "score_threshold", positive=True)
    stats = model.get("feature_stats")
    if not isinstance(stats, dict) or set(stats) != set(FEATURE_FLOORS):
        raise ValueError("invalid baseline feature statistics")
    scores = {}
    for name, floor in FEATURE_FLOORS.items():
        v = stats[name]
        if not isinstance(v, dict) or set(v) != {"median", "mad"}:
            raise ValueError("invalid statistics for " + name)
        centre = _finite(v, "median")
        spread = _finite(v, "mad")
        z = abs(row["features"][name] - centre) / max(1.4826 * spread, floor)
        scores[name] = {"value": row["features"][name],
                        "robust_deviation": z, "outlier": z > threshold}
    return {
        "model_version": MODEL_VERSION,
        "recording_sha256": row["recording_sha256"],
        "robot_id": row["robot_id"],
        "classification": ("statistical_outlier" if any(
            s["outlier"] for s in scores.values()) else "within_exploratory_baseline"),
        "feature_scores": scores,
        "interpretation": INTERPRETATION,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    features = commands.add_parser("features", help="extract aggregate features")
    features.add_argument("evidence")
    fit = commands.add_parser("fit", help="train baseline from >=5 distinct reports")
    fit.add_argument("reports", nargs="+")
    score = commands.add_parser("score", help="score held-out evidence")
    score.add_argument("model")
    score.add_argument("evidence")
    args = parser.parse_args(argv)
    try:
        if args.command == "features":
            result = evidence_features(load_json(args.evidence))
        elif args.command == "fit":
            result = fit_baseline([load_json(p) for p in args.reports])
        else:
            result = score_report(load_json(args.model), load_json(args.evidence))
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
