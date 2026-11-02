#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H13 bounded-state scaling probe (synthetic, offline, no timing assertions)."""

import argparse
import statistics
import time
import tracemalloc

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.recording import Observation
from ros3_limassol.replay import run_replay
from ros3_limassol.telemetry import Telemetry


def sample(sequence):
    # Schema fields are synthetic placeholders, not observed sensor readings.
    return Telemetry(
        schema_version=1, robot_id="mega", session_id="bench_0",
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


class GeneratedTrace:
    """Produce JSONL lazily to avoid O(N) input storage in the benchmark."""

    def __init__(self, n):
        self.n = n
        self.i = 0

    def readline(self, limit):
        if self.i == self.n:
            return ""
        i = self.i
        self.i += 1
        line = Observation(i * 0.01, sample(i)).to_json() + "\n"
        if len(line.encode("utf-8")) > limit:
            raise ValueError("generated recording line exceeds reader limit")
        return line


def workload(n, mode, late_window):
    if mode == "replay":
        summary = None
        for event in run_replay(GeneratedTrace(n), robot_id="mega", stale_after_s=3.0):
            if event.get("event") == "summary":
                summary = event
        if summary is None or summary["accepted"] != n or summary["rejected"]:
            raise AssertionError("replay contract failed")
        return
    monitor = LinkMonitor(
        robot_id="mega", stale_after_s=3.0,
        late_samples="liveness" if mode == "late" else "reject",
        late_window=late_window,
    )
    for i in range(n):
        if not monitor.ingest(sample(i), i * 0.01):
            raise AssertionError(monitor.last_rejection)
    if monitor.accepted != n or monitor.rejected:
        raise AssertionError("ingest contract failed")
    if mode == "late":
        if len(monitor._recent) > late_window or len(monitor._recent_min_heap) > late_window:
            raise AssertionError("late-window storage exceeded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[2000, 4000, 8000, 16000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--window", type=int, default=128)
    args = parser.parse_args()
    if not args.sizes or any(n < 1 for n in args.sizes) or args.repeats < 1:
        parser.error("sizes and repeats must be positive")
    if args.window < 1 or args.window > 65536:
        parser.error("window must be in [1, 65536]")

    print("H13 synthetic benchmark: observed ratios are NOT a Big-O proof")
    print("Timing excludes tracemalloc; memory runs are separately instrumented")
    for mode in ("default", "late", "replay"):
        print(f"\nmode={mode}  N  median_s  us_per_observation  ratio  peak_KiB")
        previous = None
        for n in args.sizes:
            workload(min(n, 100), mode, args.window)
            measurements = []
            for _ in range(args.repeats):
                start = time.perf_counter()
                workload(n, mode, args.window)
                measurements.append(time.perf_counter() - start)
            median = statistics.median(measurements)
            tracemalloc.start()
            try:
                workload(n, mode, args.window)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            ratio = "-" if previous is None else f"{median / previous:.3f}"
            print(f"{mode:7s} {n:7d} {median:9.5f} {median * 1e6 / n:18.2f} "
                  f"{ratio:>7s} {peak / 1024:10.1f}")
            previous = median


if __name__ == "__main__":
    main()
