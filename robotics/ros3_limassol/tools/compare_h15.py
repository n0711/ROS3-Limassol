#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H15: fail-closed comparison of two synthetic H14 benchmark JSON reports.

Compares medians descriptively. Does NOT prove asymptotic complexity,
performance regressions, host identity, or physical-link capability.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

MAX_REPORT_BYTES = 2_000_000
MODES = ("default", "late", "replay")
PROTOCOL_FIELDS = ("sizes", "modes", "late_window", "repeats",
                   "measurement_scope", "source", "schema_version")


def _unique_pairs(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate JSON key: {name}")
        result[name] = value
    return result


def _invalid_constant(value):
    raise ValueError(f"nonfinite JSON numeric constant: {value}")


def _finite_positive(value, field):
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be numeric, not boolean")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite positive number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return number


def validate_report(report):
    if not isinstance(report, dict):
        raise ValueError("benchmark report must be an object")
    if (type(report.get("schema_version")) is not int or
            report["schema_version"] != 1 or
            report.get("source") != "synthetic_offline"):
        raise ValueError("unsupported benchmark schema or source")
    claims = report.get("claims")
    if not isinstance(claims, dict) or any(
            claims.get(key) is not False for key in
            ("big_o_proven_by_timing", "hard_realtime_guarantee",
             "physical_link_validated")):
        raise ValueError("report must retain all explicit negative claims")
    sizes = report.get("sizes")
    modes = report.get("modes")
    repeats = report.get("repeats")
    window = report.get("late_window")
    if (not isinstance(sizes, list) or not 2 <= len(sizes) <= 100 or
            any(type(n) is not int or not 1 <= n <= 100000 for n in sizes) or
            any(a >= b for a, b in zip(sizes, sizes[1:]))):
        raise ValueError("sizes must be strictly increasing bounded integers")
    if (not isinstance(modes, list) or not modes or
            len(modes) > len(MODES) or len(set(map(str, modes))) != len(modes) or
            any(type(mode) is not str or mode not in MODES for mode in modes)):
        raise ValueError("invalid modes")
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("invalid repeat count")
    if type(window) is not int or not 1 <= window <= 65536:
        raise ValueError("invalid late window")
    if (not isinstance(report.get("measurement_scope"), str) or
            not report["measurement_scope"] or
            len(report["measurement_scope"]) > 1024):
        raise ValueError("missing or oversized measurement scope")
    environment = report.get("environment")
    if not isinstance(environment, dict) or any(
            not isinstance(environment.get(key), str) or
            not 1 <= len(environment[key]) <= 512 for key in
            ("python", "implementation", "platform")):
        raise ValueError("invalid platform labels")
    rows = report.get("measurements")
    if not isinstance(rows, list) or len(rows) != len(sizes) * len(modes):
        raise ValueError("missing or unexpected measurement rows")
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("measurement must be an object")
        mode, count = row.get("mode"), row.get("observations")
        if (type(mode) is not str or mode not in modes or
                type(count) is not int or count not in sizes):
            raise ValueError("measurement mode/count outside declared grid")
        key = (mode, count)
        if key in indexed:
            raise ValueError("duplicate mode/count measurement")
        median = _finite_positive(row.get("median_seconds"), "median_seconds")
        per_observation = _finite_positive(
            row.get("seconds_per_observation"), "seconds_per_observation")
        if not math.isclose(per_observation, median / count, rel_tol=1e-9):
            raise ValueError("inconsistent seconds_per_observation")
        peak = row.get("peak_tracemalloc_bytes")
        if type(peak) is not int or peak < 0:
            raise ValueError("invalid peak_tracemalloc_bytes")
        ratio = row.get("comparison_ratio")
        slope = row.get("finite_size_log_slope")
        if ratio is not None:
            _finite_positive(ratio, "comparison_ratio")
        if slope is not None:
            if type(slope) not in (float, int):
                raise ValueError("invalid finite-size logarithmic slope")
            try:
                if not math.isfinite(slope):
                    raise ValueError("nonfinite finite-size logarithmic slope")
            except OverflowError as exc:
                raise ValueError("invalid finite-size logarithmic slope") from exc
        indexed[key] = row
    for mode in modes:
        previous = None
        for count in sizes:
            if (mode, count) not in indexed:
                raise ValueError("incomplete measurement grid")
            row = indexed[(mode, count)]
            if previous is None:
                if (row.get("comparison_ratio") is not None or
                        row.get("finite_size_log_slope") is not None):
                    raise ValueError("initial point must not declare a ratio/slope")
            else:
                previous_n, previous_t = previous
                expected_ratio = row["median_seconds"] / previous_t
                if not math.isfinite(expected_ratio) or expected_ratio <= 0:
                    raise ValueError("nonfinite or underflowed ratio")
                expected_slope = math.log(expected_ratio) / math.log(
                    count / previous_n)
                if (not math.isfinite(expected_slope) or
                        row.get("comparison_ratio") is None or
                        row.get("finite_size_log_slope") is None or
                        not math.isclose(row["comparison_ratio"], expected_ratio,
                                         rel_tol=1e-9) or
                        not math.isclose(row["finite_size_log_slope"],
                                         expected_slope, rel_tol=1e-9,
                                         abs_tol=1e-12)):
                    raise ValueError("inconsistent comparison ratio/slope")
            previous = (count, row["median_seconds"])
    return indexed


def load(path):
    # Read only bounded raw bytes and reject duplicate/nonfinite JSON.
    with Path(path).open("rb") as stream:
        blob = stream.read(MAX_REPORT_BYTES + 1)
    if len(blob) > MAX_REPORT_BYTES:
        raise ValueError("benchmark report exceeds 2,000,000 bytes")
    try:
        report = json.loads(
            blob.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=_invalid_constant,
        )
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("invalid UTF-8 benchmark JSON") from exc
    indexed = validate_report(report)
    return report, indexed, hashlib.sha256(blob).hexdigest()


def compare(base, candidate, base_rows, candidate_rows, base_digest, candidate_digest):
    same_protocol = all(base.get(key) == candidate.get(key)
                        for key in PROTOCOL_FIELDS)
    same_platform_labels = base["environment"] == candidate["environment"]
    compatible = same_protocol and same_platform_labels
    results = []
    if compatible:
        for mode in base["modes"]:
            for n in base["sizes"]:
                old = base_rows[(mode, n)]
                new = candidate_rows[(mode, n)]
                ratio = new["median_seconds"] / old["median_seconds"]
                relative_change_pct = (ratio - 1.0) * 100.0
                if not math.isfinite(ratio) or not math.isfinite(relative_change_pct):
                    raise ValueError("comparison exceeds finite numeric range")
                results.append({
                    "mode": mode,
                    "observations": n,
                    "baseline_median_seconds": old["median_seconds"],
                    "candidate_median_seconds": new["median_seconds"],
                    "candidate_over_baseline_time_ratio": ratio,
                    "relative_wall_change_pct": relative_change_pct,
                    "baseline_peak_tracemalloc_bytes": old["peak_tracemalloc_bytes"],
                    "candidate_peak_tracemalloc_bytes": new["peak_tracemalloc_bytes"],
                })
    return {
        "schema_version": 1,
        "experiment": "H15 offline H14 benchmark comparison",
        "status": "descriptive_only" if compatible else "not_comparable",
        "same_protocol": same_protocol,
        "same_environment_labels": same_platform_labels,
        "same_host_verified": False,
        "baseline_sha256": base_digest,
        "candidate_sha256": candidate_digest,
        "comparison": results,
        "claims": {
            "big_o_proven_by_timing": False,
            "regression_proven_by_median": False,
            "physical_link_validated": False,
            "hardware_identity_verified": False,
        },
        "interpretation": (
            "Ratios are descriptive end-to-end synthetic measurements; "
            "matching platform strings do not establish identical machines, "
            "load conditions or CPU frequency. Only protocol+environment-label "
            "matches receive ratios. No automated performance verdict."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    options = parser.parse_args(argv)
    try:
        base, b_rows, b_hash = load(options.baseline)
        candidate, c_rows, c_hash = load(options.candidate)
        result = compare(base, candidate, b_rows, c_rows, b_hash, c_hash)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
