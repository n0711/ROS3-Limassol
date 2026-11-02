#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H16 offline multi-monitor scaling probe, with synthetic telemetry only.

Each monitor models an independent receiver. This does NOT emulate radio
transports, ROS 2 graph scaling, USB reconnection or physical vehicles.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
import platform
import statistics
import time
import tracemalloc

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

MODES = ("reject", "liveness")
STALE_AFTER_S = 2.0
MAX_SESSIONS = 16
MAX_WORK_UNITS = 250_000


def telemetry(robot_id, epoch):
    """All measurement fields are placeholders, not observed sensor data."""
    return Telemetry(
        schema_version=1,
        robot_id=robot_id,
        session_id=f"boot_{epoch // 16}",
        sequence=epoch,
        timestamp_ns=epoch,
        latitude_deg=0.0,
        longitude_deg=0.0,
        heading_deg=0.0,
        speed_m_s=0.0,
        battery_pct=0.0,
    ).to_json()


def outage(index, epoch):
    """Deterministic blackout on odd-indexed robots, four ticks per 16."""
    return index % 2 == 1 and epoch % 16 in (4, 5, 6, 7)


def run_workload(robots, ticks, mode="reject", window=32):
    """Validate every simulated receiver snapshot using its own arrival time.

    No trace is collected. Working memory grows with the monitor count, not
    with the number of observation ticks.
    """
    if not 1 <= robots <= 64 or not 8 <= ticks <= 128:
        raise ValueError("robots must be 1..64 and ticks must be 8..128")
    if mode not in MODES or not 1 <= window <= 65536:
        raise ValueError("invalid late mode/window")
    ids = [f"robot_{index:03d}" for index in range(robots)]
    monitors = [
        LinkMonitor(robot_id=robot_id, stale_after_s=STALE_AFTER_S,
                    max_sessions=MAX_SESSIONS, late_samples=mode,
                    late_window=window)
        for robot_id in ids
    ]
    last_arrival = [None] * robots
    previous_state = ["WAITING"] * robots
    stale_transitions = [0] * robots
    accepted = [0] * robots
    for epoch in range(ticks):
        now = float(epoch)
        for index, monitor in enumerate(monitors):
            if outage(index, epoch):
                continue
            if not monitor.ingest(telemetry(ids[index], epoch), now):
                raise AssertionError(f"{ids[index]} rejected its own heartbeat")
            last_arrival[index] = now
            accepted[index] += 1

        for index, monitor in enumerate(monitors):
            status = monitor.snapshot(now)
            age = now - last_arrival[index]
            expected = "STALE" if age >= STALE_AFTER_S else "HEALTHY"
            if status.state != expected or status.robot_id != ids[index]:
                raise AssertionError(f"incorrect independent state for {ids[index]}")
            if status.accepted != accepted[index] or status.rejected != 0:
                raise AssertionError(f"incorrect counters for {ids[index]}")
            if status.state == "STALE" and previous_state[index] != "STALE":
                stale_transitions[index] += 1
            previous_state[index] = status.state

    seen = sum(len(monitor._seen_sessions) for monitor in monitors)
    retained = sum(len(monitor._recent) for monitor in monitors)
    heaps = sum(len(monitor._recent_min_heap) for monitor in monitors)
    if (seen > robots * MAX_SESSIONS or retained > robots * window or
            heaps > robots * window):
        raise AssertionError("monitor state exceeds declared limits")
    return {
        "robots": robots,
        "ticks_per_robot": ticks,
        "accepted_by_robot": accepted,
        "stale_transitions_by_robot": stale_transitions,
        "final_states": previous_state,
        "session_ids_retained": seen,
        "late_sequences_retained": retained,
        "heap_entries_retained": heaps,
        "expected_state_checks": robots * ticks,
    }


def measure(robots, ticks, mode, window, repeats):
    run_workload(robots, 8, mode, window)  # warm-up, outside timed interval
    samples = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        run_workload(robots, ticks, mode, window)
        elapsed = (time.perf_counter_ns() - start) / 1e9
        samples.append(elapsed)
    median = statistics.median(samples)

    # tracemalloc changes running time, so measure memory separately.
    tracemalloc.start()
    try:
        summary = run_workload(robots, ticks, mode, window)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {
        "mode": mode,
        "robots": robots,
        "ticks_per_robot": ticks,
        "median_seconds": median,
        "seconds_per_robot_tick": median / (robots * ticks),
        "peak_tracemalloc_bytes": peak,
        "stale_transitions_total": sum(summary["stale_transitions_by_robot"]),
        "accepted_total": sum(summary["accepted_by_robot"]),
        "expected_state_checks": summary["expected_state_checks"],
        "session_ids_retained": summary["session_ids_retained"],
        "late_sequences_retained": summary["late_sequences_retained"],
        "heap_entries_retained": summary["heap_entries_retained"],
    }


def collect(robot_counts, ticks, repeats, window, modes):
    points = []
    for mode in modes:
        previous = None
        for robots in robot_counts:
            row = measure(robots, ticks, mode, window, repeats)
            if previous is None:
                row["time_ratio_to_previous"] = None
                row["finite_size_log_slope"] = None
            else:
                ratio = row["median_seconds"] / previous["median_seconds"]
                row["time_ratio_to_previous"] = ratio
                row["finite_size_log_slope"] = (
                    math.log(ratio) / math.log(robots / previous["robots"]))
            points.append(row)
            previous = row
    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "experiment": "H16 multi-robot independent receiver scaling",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "cpu_count_reported": os.cpu_count(),
        },
        "parameters": {
            "robot_counts": list(robot_counts),
            "ticks_per_robot": ticks,
            "repeats": repeats,
            "late_window": window,
            "modes": list(modes),
            "stale_after_s": STALE_AFTER_S,
            "max_sessions_per_robot": MAX_SESSIONS,
            "outage": "odd robot indices, epoch modulo 16 in [4,5,6,7]",
        },
        "measurement_scope": (
            "single-process sequential dispatch, synthetic JSON construction, "
            "monitor ingest and snapshot; NOT ROS/DDS or concurrent fleet throughput"
        ),
        "claims": {
            "big_o_proven_by_timing": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
            "distributed_network_validated": False,
            "raspberry_pi_measured_by_ci": False,
        },
        "measurements": points,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robots", type=int, nargs="+",
                        default=[1, 2, 4, 8, 16])
    parser.add_argument("--ticks", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--window", type=int, default=32)
    parser.add_argument("--modes", nargs="+", choices=MODES,
                        default=list(MODES))
    options = parser.parse_args(argv)
    robots = options.robots
    if (not 2 <= len(robots) <= 8 or
            any(type(n) is not int or n < 1 or n > 64 for n in robots) or
            any(a >= b for a, b in zip(robots, robots[1:]))):
        parser.error("robots must be 2..8 strictly increasing values in [1,64]")
    if not 8 <= options.ticks <= 128:
        parser.error("ticks must be in [8,128]")
    if not 1 <= options.repeats <= 5:
        parser.error("repeats must be in [1,5]")
    if not 1 <= options.window <= 65536:
        parser.error("window must be in [1,65536]")
    if len(set(options.modes)) != len(options.modes):
        parser.error("modes must not repeat")
    total_work = sum(robots) * options.ticks * (
        options.repeats + 1) * len(options.modes)
    if total_work > MAX_WORK_UNITS:
        parser.error("synthetic work exceeds 250000 robot-tick operations")
    result = collect(robots, options.ticks, options.repeats,
                     options.window, options.modes)
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
