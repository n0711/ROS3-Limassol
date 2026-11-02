# SPDX-License-Identifier: Apache-2.0
"""H17: offline latency-probe contract and deterministic jump accounting."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from ros3_limassol.monitor import LinkMonitor

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))
from benchmark_h17 import measure_trial, packet, percentile_nearest_rank  # noqa: E402


class H17SingleCallTests(unittest.TestCase):
    def test_nearest_rank_percentiles_exact(self):
        samples = [10, 1, 9, 2, 8, 3, 7, 4, 6, 5]
        self.assertEqual(percentile_nearest_rank(samples, 0.5), 5)
        self.assertEqual(percentile_nearest_rank(samples, 0.95), 10)
        self.assertEqual(percentile_nearest_rank(samples, 0.99), 10)
        with self.assertRaises(ValueError):
            percentile_nearest_rank([], 0.5)
        with self.assertRaises(ValueError):
            percentile_nearest_rank([1, -2], 0.5)
        with self.assertRaises(ValueError):
            percentile_nearest_rank([1, 2], 0)

    def test_jump_expires_entire_window_in_single_ingest(self):
        """Count actual heap removals, independent of wall-clock noise."""
        for window in (1, 2, 8, 32, 64):
            with self.subTest(window=window):
                import heapq
                monitor = LinkMonitor(
                    robot_id="mega", late_samples="liveness",
                    late_window=window,
                )
                for sequence in range(window):
                    self.assertTrue(monitor.ingest(packet(sequence), sequence))
                self.assertEqual(len(monitor._recent_min_heap), window)
                actual_pops = []
                def recording_pop(heap):
                    result = heapq.heappop(heap)
                    actual_pops.append(result)
                    return result
                with patch("ros3_limassol.monitor.heappop", side_effect=recording_pop):
                    self.assertTrue(monitor.ingest(packet(window + 100), window))
                self.assertEqual(len(actual_pops), window)
                self.assertEqual(monitor._recent_min_heap, [window + 100])
                self.assertEqual(monitor._recent, {window + 100})

    def test_default_rejection_policy_never_uses_heap(self):
        monitor = LinkMonitor(robot_id="mega", late_samples="reject")
        with patch("ros3_limassol.monitor.heappush",
                   side_effect=AssertionError("unexpected heap insertion")), \
             patch("ros3_limassol.monitor.heappop",
                   side_effect=AssertionError("unexpected heap removal")):
            for sequence in list(range(32)) + [1000]:
                self.assertTrue(monitor.ingest(packet(sequence), sequence))
        self.assertEqual(monitor._recent, set())
        self.assertEqual(monitor._recent_min_heap, [])
        self.assertEqual(monitor.accepted, 33)

    def test_latency_probe_preserves_state_and_finite_results(self):
        for mode in ("reject", "liveness"):
            row = measure_trial(window=16, samples=24, mode=mode)
            for key in (
                "baseline_p50_us", "baseline_p95_us", "baseline_p99_us",
                "baseline_max_us", "jump_ingest_us",
            ):
                self.assertGreaterEqual(row[key], 0)
            self.assertLessEqual(row["baseline_p50_us"], row["baseline_p95_us"])
            self.assertLessEqual(row["baseline_p95_us"], row["baseline_p99_us"])
            self.assertLessEqual(row["baseline_p99_us"], row["baseline_max_us"])

    def test_benchmark_json_smoke_and_negative_claims(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "tools" / "benchmark_h17.py"),
             "--windows", "2", "8", "--samples", "16", "--repeats", "1"],
            cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True,
            timeout=35, check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "synthetic_offline")
        self.assertEqual(len(report["measurements"]), 4)
        for point in report["measurements"]:
            self.assertGreaterEqual(point["median_jump_ingest_us"], 0)
            self.assertEqual(
                point["expected_heap_entries_expired_on_jump"],
                point["late_window"] if point["mode"] == "liveness" else 0,
            )
        self.assertFalse(report["claims"]["hard_realtime_guarantee"])
        self.assertFalse(report["claims"]["big_o_proven_by_timing"])
        self.assertFalse(report["claims"]["physical_link_validated"])

    def test_benchmark_fails_closed_on_invalid_sizes(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        for arguments in (
            ["--windows", "8", "2"],
            ["--windows", "8", "8"],
            ["--windows", "0"],
            ["--windows", "2049"],
            ["--windows", "8", "--samples", "0"],
            ["--windows", "8", "--samples", "4097"],
            ["--windows", "8", "--repeats", "6"],
            ["--windows", "8", "--modes", "reject", "reject"],
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(PACKAGE_ROOT / "tools" / "benchmark_h17.py"),
                     *arguments],
                    cwd=PACKAGE_ROOT, env=env, capture_output=True,
                    text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
