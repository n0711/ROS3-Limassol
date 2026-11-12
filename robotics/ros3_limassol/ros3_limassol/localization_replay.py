# SPDX-License-Identifier: Apache-2.0
"""Validate normalized synthetic localization streams and score odometry offline."""

import argparse
import hashlib
import json
import math
from pathlib import Path

from .clock_bounds import _constant, _finite, _object, _strict

FIELDS = {
    "gnss": ("antenna_enu_m",),
    "imu": ("specific_force_flu_m_s2", "angular_rate_flu_rad_s"),
    "odometry": ("base_enu_m",),
    "reference": ("base_enu_m",),
}


def evaluate(dataset):
    _strict(dataset, {"version", "source", "calibration", "streams"}, "dataset")
    if type(dataset["version"]) is not int or dataset["version"] != 1:
        raise ValueError("expected version 1")
    if dataset["source"] != "synthetic":
        raise ValueError("version 1 accepts synthetic fixtures only")
    calibration = dataset["calibration"]
    _strict(calibration, {"gnss_lever_arm_flu_m", "imu_alignment"}, "calibration")
    if calibration["imu_alignment"] != "axes_aligned_with_base":
        raise ValueError("normalize IMU axes to the base frame first")
    vector(calibration["gnss_lever_arm_flu_m"])
    streams = dataset["streams"]
    _strict(streams, set(FIELDS), "streams")
    for name, fields in FIELDS.items():
        rows = streams[name]
        if type(rows) is not list or len(rows) > 4096:
            raise ValueError(f"invalid {name} stream size")
        last = -1
        for row in rows:
            _strict(row, {"t_ms", *fields}, name)
            stamp = row["t_ms"]
            if type(stamp) is not int or not last < stamp <= 2**53 - 1:
                raise ValueError(f"invalid or non-increasing {name} timestamp")
            last = stamp
            for field in fields:
                vector(row[field])

    reference = streams["reference"]
    if not reference:
        raise ValueError("reference timeline is empty")
    odometry = {row["t_ms"]: row["base_enu_m"] for row in streams["odometry"]}
    errors = []
    gaps = []
    missing_since = None
    for row in reference:
        stamp = row["t_ms"]
        if stamp in odometry:
            errors.append(math.dist(row["base_enu_m"], odometry[stamp]))
            if missing_since is not None:
                gaps.append({"first_missing_ms": missing_since, "resumed_ms": stamp})
                missing_since = None
        elif missing_since is None:
            missing_since = stamp
    if missing_since is not None:
        gaps.append({"first_missing_ms": missing_since, "resumed_ms": None})
    return {
        "source": "synthetic", "reference_count": len(reference), "matched": len(errors),
        "missing": len(reference) - len(errors), "unmatched_odometry": len(odometry) - len(errors),
        "position_rmse_m": math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
        "missing_intervals": gaps,
    }


def vector(values):
    if type(values) is not list or len(values) != 3:
        raise ValueError("expected a three-component vector")
    for component in values:
        _finite(component, "vector component", lower=-1e9, upper=1e9)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.dataset.open("rb") as stream:
            raw = stream.read(1048577)
        if len(raw) > 1048576:
            raise ValueError("dataset exceeds 1 MiB")
        result = evaluate(json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                                     parse_constant=_constant))
        result["input_sha256"] = hashlib.sha256(raw).hexdigest()
        print(json.dumps(result, allow_nan=False, indent=2))
    except (OSError, ValueError, RecursionError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
