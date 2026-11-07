# SPDX-License-Identifier: Apache-2.0
"""Offline, conditional source/receiver clock-offset bounds; never a synchronizer.

The caller supplies an independently established offset interval. The helper
only propagates its declared uncertainty to possible capture-to-receipt age.
It does not measure clock offset, validate hardware timestamps or authorize
navigation, actuation, identity matching or safety decisions.
"""

import argparse
import json
import math
from pathlib import Path
import re

MAX_INPUT_BYTES = 65536
MAX_SAMPLES = 128
SAMPLE_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
REQUIRED = {"schema_version", "freshness_limit_s", "calibration", "samples"}
CALIBRATION_KEYS = {"offset_s", "uncertainty_s", "drift_ppm", "elapsed_s"}
SAMPLE_KEYS = {"sample_id", "capture_time_s", "receive_time_s"}


def _finite(value, field, *, lower=None, upper=None):
    if type(value) not in (float, int):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    if (lower is not None and number < lower) or (upper is not None and number > upper):
        raise ValueError(f"{field} is outside the permitted range")
    return number


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"non-finite JSON constant: {value}")


def _strict(obj, names, label):
    if type(obj) is not dict or set(obj) != names:
        raise ValueError(f"{label} requires exactly {sorted(names)}")


def assess_capture_age(capture_time_s, receive_time_s, freshness_limit_s, calibration=None):
    """Classify physical age using a declared receiver-minus-source offset.

    Offset theta is defined as receiver_clock_time - source_clock_time.
    If calibration's error is bounded by epsilon, then true delivery age lies
    in [receive - capture - theta - epsilon,
        receive - capture - theta + epsilon], intersected with age >= 0.
    The result is conditional on all declared clock assumptions being true.
    """
    capture = _finite(capture_time_s, "capture_time_s", lower=0, upper=1e12)
    receive = _finite(receive_time_s, "receive_time_s", lower=0, upper=1e12)
    limit = _finite(freshness_limit_s, "freshness_limit_s", lower=0, upper=86400)
    if calibration is None:
        return {"classification": "calibration_unavailable", "min_age_s": None,
                "max_age_s": None, "offset_error_bound_s": None}
    _strict(calibration, CALIBRATION_KEYS, "calibration")
    offset = _finite(calibration["offset_s"], "offset_s", lower=-1e9, upper=1e9)
    initial = _finite(calibration["uncertainty_s"], "uncertainty_s", lower=0, upper=1e6)
    drift = _finite(calibration["drift_ppm"], "drift_ppm", lower=0, upper=10000)
    elapsed = _finite(calibration["elapsed_s"], "elapsed_s", lower=0, upper=604800)
    uncertainty = initial + drift * elapsed / 1e6
    minimum = receive - capture - offset - uncertainty
    maximum = receive - capture - offset + uncertainty
    if maximum < 0:
        classification = "inconsistent_clock_bound"
        lo = hi = None
    else:
        lo, hi = max(0.0, minimum), max(0.0, maximum)
        if hi <= limit:
            classification = "within_declared_bound"
        elif lo > limit:
            classification = "outside_declared_bound"
        else:
            classification = "indeterminate"
    return {"classification": classification, "min_age_s": lo,
            "max_age_s": hi, "offset_error_bound_s": uncertainty}


def evaluate_report(report):
    """Check a small versioned batch; no cross-session/time-origin inference."""
    _strict(report, REQUIRED, "report")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    limit = _finite(report["freshness_limit_s"], "freshness_limit_s", lower=0, upper=86400)
    calibration = report["calibration"]
    if calibration is not None:
        _strict(calibration, CALIBRATION_KEYS, "calibration")
    samples = report["samples"]
    if type(samples) is not list or not 1 <= len(samples) <= MAX_SAMPLES:
        raise ValueError("samples must contain 1 to 128 observations")
    output = []
    ids = set()
    last_receive = None
    for item in samples:
        _strict(item, SAMPLE_KEYS, "sample")
        sample_id = item["sample_id"]
        if type(sample_id) is not str or not SAMPLE_ID.fullmatch(sample_id):
            raise ValueError("invalid sample_id")
        if sample_id in ids:
            raise ValueError("duplicate sample_id")
        ids.add(sample_id)
        received = _finite(item["receive_time_s"], "receive_time_s", lower=0, upper=1e12)
        if last_receive is not None and received < last_receive:
            raise ValueError("receive timestamps moved backwards")
        last_receive = received
        bound = assess_capture_age(item["capture_time_s"], received, limit, calibration)
        output.append({"sample_id": sample_id, **bound})
    return {
        "alignment_report_version": 1,
        "sample_count": len(output),
        "calibration_supplied_not_verified": calibration is not None,
        "offset_sign": "receiver_clock_minus_source_clock",
        "results": output,
        "alignment_verified": False,
        "navigation_authority": False,
        "interpretation": (
            "Conditional bounds under externally supplied clock offset, uncertainty, "
            "drift and compatible monotonic time origins. No hardware "
            "synchronization, capture provenance, identity or safety validation."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_json", help="bounded schema-v1 clock report JSON")
    args = parser.parse_args(argv)
    try:
        path = Path(args.input_json)
        if path.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("input exceeds 65536 bytes")
        raw = path.read_bytes()
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("input exceeds 65536 bytes")
        report = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                            parse_constant=_constant)
        print(json.dumps(evaluate_report(report), allow_nan=False, sort_keys=True, indent=2))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
