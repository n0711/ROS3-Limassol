#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H17: offline single-call latency under bounded late-window expiry.

Wall-clock observations are not worst-case execution-time guarantees.
This probe contains no ROS 2, USB, radio or physical vehicles.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import platform
import statistics
import time

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

MODES = ("reject", "liveness")
MAX_WORK = 300_000


def packet(sequence):
    # Non-ID telemetry fields are synthetic placeholders, not sensor readings.
    return Telemetry(
        schema_version=1, robot_id="mega", session_id="boot_0",
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


def percentile_nearest_rank(samples, quantile):
    if not samples or not 0 < quantile <= 1:
        raise ValueError("nonempty samples and quantile in (0,1] required")
    if any(type(value) not in (int, float) or
           not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("samples must be finite nonnegative times")
    ordered = sorted(samples)
    return ordered[math.ceil(len(ordered) * quantile) - 1]


def measure_trial(window, samples, mode):
    if not 1 <= window <= 2048 or not 1 <= samples <= 4096 or mode not in MODES:
        raise ValueError("invalid bounded synthetic latency workload")
    monitor = LinkMonitor(robot_id="mega", stale_after_s=3.0,
                          late_samples=mode, late_window=window)
    # Pre-fill in order, then time only the ingest call. JSON encoding is
    # outside measured intervals, while JSON decoding remains inside ingest.
    for seq in range(window):
        if not monitor.ingest(packet(seq), float(seq)):
            raise AssertionError("prefill rejected")
    baseline_ns = []
    for seq in range(window, window + samples):
        raw = packet(seq)
        start = time.perf_counter_ns()
        ok = monitor.ingest(raw, float(seq))
        elapsed = time.perf_counter_ns() - start
        if not ok:
            raise AssertionError("baseline ingestion rejected")
        baseline_ns.append(elapsed)
    old_max = window + samples - 1
    jump = old_max + window + 5
    jump_packet = packet(jump)
    start = time.perf_counter_ns()
    accepted = monitor.ingest(jump_packet, float(window + samples))
    jump_ns = time.perf_counter_ns() - start
    if not accepted:
        raise AssertionError("forward-jump ingestion rejected")
    if monitor.accepted != window + samples + 1 or monitor.rejected != 0:
        raise AssertionError("incorrect monitoring counters")
    if mode == "liveness":
        if monitor._recent != {jump} or monitor._recent_min_heap != [jump]:
            raise AssertionError("large jump did not expire old window")
    else:
        if monitor._recent or monitor._recent_min_heap:
            raise AssertionError("default mode unexpectedly retains late-window state")
    return {
        "baseline_p50_us": percentile_nearest_rank(baseline_ns, 0.5) / 1000,
        "baseline_p95_us": percentile_nearest_rank(baseline_ns, 0.95) / 1000,
        "baseline_p99_us": percentile_nearest_rank(baseline_ns, 0.99) / 1000,
        "baseline_max_us": max(baseline_ns) / 1000,
        "jump_ingest_us": jump_ns / 1000,
    }


def collect(windows, samples, repeats, modes):
    rows = []
    for mode in modes:
        for window in windows:
            trials = [measure_trial(window, samples, mode)
                      for _ in range(repeats)]
            row = {
                "mode": mode,
                "late_window": window,
                "samples_per_trial": samples,
                "repeats": repeats,
                "median_baseline_p50_us": statistics.median(
                    point["baseline_p50_us"] for point in trials),
                "median_baseline_p95_us": statistics.median(
                    point["baseline_p95_us"] for point in trials),
                "median_baseline_p99_us": statistics.median(
                    point["baseline_p99_us"] for point in trials),
                "median_baseline_max_us": statistics.median(
                    point["baseline_max_us"] for point in trials),
                "median_jump_ingest_us": statistics.median(
                    point["jump_ingest_us"] for point in trials),
                "expected_heap_entries_expired_on_jump": (
                    window if mode == "liveness" else 0
                ),
            }
            reference = row["median_baseline_p50_us"]
            row["descriptive_jump_over_p50_ratio"] = (
                row["median_jump_ingest_us"] / reference if reference > 0 else None)
            rows.append(row)
    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "experiment": "H17 per-ingest latency with sequence jump",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "parameters": {
            "windows": list(windows),
            "baseline_samples_per_trial": samples,
            "repeats": repeats,
            "modes": list(modes),
        },
        "measurement_scope": (
            "one Python LinkMonitor.ingest call per sample; payload JSON is "
            "pre-encoded; JSON parsing/set/heap work included; elapsed times "
            "are noisy and scheduler-dependent"
        ),
        "claims": {
            "worst_case_execution_time_established": False,
            "big_o_proven_by_timing": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
            "raspberry_pi_measured_by_ci": False,
        },
        "measurements": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", type=int, nargs="+", default=[8, 64, 256])
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    args = parser.parse_args(argv)
    windows = args.windows
    if (not 1 <= len(windows) <= 8 or any(w < 1 or w > 2048 for w in windows)
            or any(a >= b for a, b in zip(windows, windows[1:]))):
        parser.error("windows must be strictly increasing values in [1,2048]")
    if not 1 <= args.samples <= 4096:
        parser.error("samples must be in [1,4096]")
    if not 1 <= args.repeats <= 5:
        parser.error("repeats must be in [1,5]")
    if len(set(args.modes)) != len(args.modes):
        parser.error("modes must not repeat")
    total_work = (sum(windows) + len(windows) * (args.samples + 1)) * (
        args.repeats * len(args.modes))
    if total_work > MAX_WORK:
        parser.error("synthetic workload exceeds 300000 ingestions")
    print(json.dumps(collect(windows, args.samples, args.repeats, args.modes),
                     allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
