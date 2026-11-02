#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H14 reproducible structured scaling probe, entirely synthetic and offline.

Wall-clock ratios are observational diagnostics, never complexity proofs.
Timing and tracemalloc measurements are collected in separate executions.
No system-specific performance threshold is asserted.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import platform
import statistics
import sys
import time
import tracemalloc

from benchmark_h13 import workload


MODES = ("default", "late", "replay")
MAX_TOTAL_WORK = 2_000_000


def collect(sizes, repeats, window, modes):
    measurements = []
    for mode in modes:
        previous = None
        for count in sizes:
            workload(min(count, 32), mode, window)
            elapsed = []
            for _ in range(repeats):
                start_ns = time.perf_counter_ns()
                workload(count, mode, window)
                elapsed.append((time.perf_counter_ns() - start_ns) / 1e9)
            median = statistics.median(elapsed)

            # Memory probes are deliberately excluded from timing samples.
            tracemalloc.start()
            try:
                workload(count, mode, window)
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            if previous is None:
                ratio = None
                exponent = None
            else:
                previous_n, previous_t = previous
                ratio = median / previous_t
                # Finite-size diagnostic slope, NOT an asymptotic exponent.
                exponent = math.log(ratio) / math.log(count / previous_n)
            measurements.append({
                "mode": mode,
                "observations": count,
                "median_seconds": median,
                "seconds_per_observation": median / count,
                "comparison_ratio": ratio,
                "finite_size_log_slope": exponent,
                "peak_tracemalloc_bytes": peak,
            })
            previous = (count, median)

    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "sizes": list(sizes),
        "repeats": repeats,
        "late_window": window,
        "modes": list(modes),
        "measurement_scope": (
            "benchmark_h13.workload: synthetic payload creation, ingestion "
            "and optional streaming replay; not isolated monitor-call latency"
        ),
        "claims": {
            "big_o_proven_by_timing": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
        },
        "measurements": measurements,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+",
                        default=[1024, 2048, 4096, 8192])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--window", type=int, default=128)
    parser.add_argument("--modes", choices=MODES, nargs="+", default=MODES)
    options = parser.parse_args(argv)
    sizes = options.sizes
    if len(sizes) < 2 or any(n < 1 or n > 100000 for n in sizes):
        parser.error("provide at least two sizes in [1, 100000]")
    if any(a >= b for a, b in zip(sizes, sizes[1:])):
        parser.error("sizes must be strictly increasing")
    if not 1 <= options.repeats <= 10:
        parser.error("repeats must be in [1, 10]")
    if not 1 <= options.window <= 65536:
        parser.error("window must be in [1, 65536]")
    if len(set(options.modes)) != len(options.modes):
        parser.error("modes must be distinct")
    # Timed repeats + a separate memory pass, per mode and size.
    total_observations = sum(sizes) * (options.repeats + 1) * len(options.modes)
    if total_observations > MAX_TOTAL_WORK:
        parser.error(f"workload exceeds budget of {MAX_TOTAL_WORK} observations")

    result = collect(sizes, options.repeats, options.window, options.modes)
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
