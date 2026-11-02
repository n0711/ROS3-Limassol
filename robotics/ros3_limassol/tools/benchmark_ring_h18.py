#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H18: compare existing late-window heap with an experimental sequence ring.

Offline synthetic only; descriptive performance, not a real-time guarantee.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import platform
import statistics
import time
import tracemalloc

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

from experimental_ring_h18 import RingLinkMonitor

IMPLEMENTATIONS = {
    "heap_reference": LinkMonitor,
    "ring_experiment": RingLinkMonitor,
}
MAX_WORK = 200_000


def packet(sequence):
    return Telemetry(
        schema_version=1, robot_id="mega", session_id="boot_0",
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0,
        heading_deg=0.0, speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


def make_trace(window, samples):
    """Generate the same bounded arrival stream once for both algorithms."""
    frames = []
    highest = 0
    for index in range(window):
        frames.append((packet(index), float(index)))
        highest = index
    for tick in range(samples):
        if tick % 31 == 0:
            highest += window + 3   # single operation can expire W heap entries
            sequence = highest
        elif tick % 11 == 0 and highest > 1:
            sequence = highest - 1   # may be an unseen late arrival or duplicate
        else:
            highest += 1
            sequence = highest
        frames.append((packet(sequence), float(window + tick)))
    return frames


def workload(cls, frames, window):
    monitor = cls(robot_id="mega", late_samples="liveness",
                  late_window=window, stale_after_s=3.0)
    checksum = 0
    for index, (raw, now) in enumerate(frames):
        if monitor.ingest(raw, now):
            checksum = (checksum + index + 1) % (2**64)
    status = monitor.snapshot(frames[-1][1])
    return {
        "accepted": status.accepted,
        "rejected": status.rejected,
        "last_sequence": status.last_sequence,
        "last_rejection": status.last_rejection,
        "late_accepted": monitor.late_accepted,
        "accepted_index_checksum": checksum,
    }


def collect(windows, samples, repeats):
    measurements = []
    for window in windows:
        frames = make_trace(window, samples)
        summaries = {
            name: workload(cls, frames, window)
            for name, cls in IMPLEMENTATIONS.items()
        }
        if summaries["heap_reference"] != summaries["ring_experiment"]:
            raise AssertionError("ring prototype differs from reference monitor")
        for name, cls in IMPLEMENTATIONS.items():
            timings = []
            for _ in range(repeats):
                start = time.perf_counter_ns()
                summary = workload(cls, frames, window)
                elapsed = (time.perf_counter_ns() - start) / 1e9
                if summary != summaries[name]:
                    raise AssertionError("nondeterministic monitor summary")
                timings.append(elapsed)
            median = statistics.median(timings)
            tracemalloc.start()
            try:
                workload(cls, frames, window)
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            measurements.append({
                "implementation": name,
                "late_window": window,
                "observations": len(frames),
                "median_wall_seconds": median,
                "median_us_per_observation": 1e6 * median / len(frames),
                "peak_tracemalloc_bytes": peak,
                "equivalent_summary_to_reference": True,
                **summary,
            })
    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "experiment": "H18 experimental sequence ring versus current heap",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "parameters": {
            "windows": list(windows),
            "samples_after_prefill": samples,
            "repeats": repeats,
            "trace": "one prefilled session, periodic forward jumps and late samples",
        },
        "measurement_scope": (
            "identical prebuilt JSON frames in a standalone Python process; "
            "JSON decoding, LinkMonitor ingest and checksum in timed region; "
            "trace construction is excluded, memory traces exclude prebuilt inputs"
        ),
        "claims": {
            "production_monitor_changed": False,
            "big_o_proven_by_timing": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
            "raspberry_pi_measured_by_ci": False,
        },
        "measurements": measurements,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", nargs="+", type=int, default=[8, 32, 128, 512])
    parser.add_argument("--samples", type=int, default=1024)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args(argv)
    windows = args.windows
    if (not 1 <= len(windows) <= 8 or
            any(n < 1 or n > 2048 for n in windows) or
            any(a >= b for a, b in zip(windows, windows[1:]))):
        parser.error("windows must be strictly increasing values in [1,2048]")
    if not 1 <= args.samples <= 4096:
        parser.error("samples must be in [1,4096]")
    if not 1 <= args.repeats <= 5:
        parser.error("repeats must be in [1,5]")
    if (sum(windows) + len(windows) * args.samples) * (args.repeats + 1) * 2 > MAX_WORK:
        parser.error("synthetic workload exceeds 200000 observations")
    print(json.dumps(collect(windows, args.samples, args.repeats),
                     allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
