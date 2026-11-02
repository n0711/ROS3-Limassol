# SPDX-License-Identifier: Apache-2.0
"""H14 deterministic heap-operation accounting, independent of wall-clock time.

These white-box tests intentionally couple to LinkMonitor's current heap
implementation; a future data-structure change must revise the proof as well.
No radio, USB, physical Arduino or ROS process is used.
"""

import heapq
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry


def packet(sequence, session_id="boot_0"):
    return Telemetry(
        schema_version=1, robot_id="mega", session_id=session_id,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


class HeapCounter:
    """Count heap insertions/removals; keep real heap semantics."""

    def __init__(self):
        self.pushes = 0
        self.pops = 0

    def push(self, heap, value):
        self.pushes += 1
        return heapq.heappush(heap, value)

    def pop(self, heap):
        self.pops += 1
        return heapq.heappop(heap)


class H14OperationBoundTests(unittest.TestCase):
    def test_monotone_stream_has_at_most_two_heap_ops_per_sample(self):
        # Every accepted sequence is inserted once and removed at most once.
        # This is a deterministic amortized work bound, not a time benchmark.
        n = 2048
        for window in (1, 2, 16, 64, 256):
            with self.subTest(window=window):
                monitor = LinkMonitor(
                    robot_id="mega", stale_after_s=3,
                    late_samples="liveness", late_window=window,
                )
                counts = HeapCounter()
                with patch("ros3_limassol.monitor.heappush", side_effect=counts.push), \
                     patch("ros3_limassol.monitor.heappop", side_effect=counts.pop):
                    for sequence in range(n):
                        self.assertTrue(monitor.ingest(
                            packet(sequence), sequence * 0.01
                        ))
                        self.assertLessEqual(
                            len(monitor._recent_min_heap), window
                        )
                        self.assertEqual(len(monitor._recent_min_heap),
                                         len(monitor._recent))
                self.assertEqual(counts.pushes, n)
                self.assertEqual(counts.pops, max(0, n - window))
                self.assertLessEqual(counts.pushes + counts.pops, 2 * n)
                self.assertEqual(monitor.accepted, n)
                self.assertEqual(monitor.rejected, 0)

    def test_large_gap_exposes_nonconstant_single_ingest(self):
        # A large forward sequence jump expires all W old heap entries in
        # one call; O(W log W) is a safe worst-case upper bound for that call.
        window = 64
        monitor = LinkMonitor(robot_id="mega", late_samples="liveness",
                              late_window=window)
        counts = HeapCounter()
        with patch("ros3_limassol.monitor.heappush", side_effect=counts.push), \
             patch("ros3_limassol.monitor.heappop", side_effect=counts.pop):
            for sequence in range(window):
                self.assertTrue(monitor.ingest(packet(sequence), sequence * 0.01))
            self.assertEqual(counts.pops, 0)
            self.assertTrue(monitor.ingest(packet(10000), 1.0))
            self.assertEqual(counts.pops, window)
            self.assertEqual(counts.pushes, window + 1)
            self.assertEqual(monitor._recent, {10000})
            self.assertEqual(len(monitor._recent_min_heap), 1)

    def test_session_changes_clear_sequence_memory(self):
        monitor = LinkMonitor(robot_id="mega", late_samples="liveness",
                              late_window=32, max_sessions=10)
        for i in range(32):
            self.assertTrue(monitor.ingest(packet(i), i / 100))
        self.assertEqual(len(monitor._recent), 32)
        self.assertTrue(monitor.ingest(packet(0, "boot_1"), 1.0))
        self.assertEqual(len(monitor._recent), 1)
        self.assertEqual(monitor._recent, {0})
        self.assertEqual(len(monitor._seen_sessions), 2)
        self.assertFalse(monitor.ingest(packet(33, "boot_0"), 1.1))
        self.assertEqual(monitor.last_rejection, "retired_session")
        self.assertEqual(len(monitor._recent), 1)

    def test_h14_json_benchmark_smoke(self):
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "tools" / "benchmark_h14.py"),
             "--sizes", "8", "16", "--repeats", "1"],
            cwd=root, capture_output=True, text=True, check=True, timeout=30,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "synthetic_offline")
        self.assertEqual(report["sizes"], [8, 16])
        self.assertEqual(report["repeats"], 1)
        self.assertEqual(len(report["measurements"]), 6)
        for row in report["measurements"]:
            self.assertIn(row["mode"], ("default", "late", "replay"))
            self.assertIn(row["observations"], (8, 16))
            self.assertGreater(row["median_seconds"], 0)
            self.assertGreaterEqual(row["peak_tracemalloc_bytes"], 0)
            self.assertEqual(row["comparison_ratio"], None if row["observations"] == 8
                             else row["comparison_ratio"])
        self.assertFalse(report["claims"]["big_o_proven_by_timing"])
        self.assertFalse(report["claims"]["physical_link_validated"])


if __name__ == "__main__":
    unittest.main()
