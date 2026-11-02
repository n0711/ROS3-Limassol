# SPDX-License-Identifier: Apache-2.0
"""H16: synthetic multi-monitor isolation, state bounds, and benchmark smoke."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))
from benchmark_h16 import outage, run_workload, telemetry  # noqa: E402


class H16MultiRobotTests(unittest.TestCase):
    def test_blackout_does_not_stale_other_monitors(self):
        result = run_workload(8, 16)
        self.assertEqual(result["accepted_by_robot"], [16, 12] * 4)
        self.assertEqual(result["stale_transitions_by_robot"], [0, 1] * 4)
        self.assertEqual(result["final_states"], ["HEALTHY"] * 8)
        self.assertEqual(result["expected_state_checks"], 8 * 16)
        self.assertFalse(outage(0, 5))
        self.assertTrue(outage(1, 5))

    def test_repeated_outages_preserve_independence(self):
        result = run_workload(8, 24)
        self.assertEqual(result["accepted_by_robot"], [24, 16] * 4)
        self.assertEqual(result["stale_transitions_by_robot"], [0, 2] * 4)
        self.assertEqual(result["final_states"], ["HEALTHY", "STALE"] * 4)
        self.assertEqual(result["expected_state_checks"], 8 * 24)

    def test_memory_state_scales_with_monitors_not_ticks(self):
        for robots in (1, 4, 16):
            for mode in ("reject", "liveness"):
                with self.subTest(robots=robots, mode=mode):
                    result = run_workload(robots, 64, mode, 8)
                    self.assertLessEqual(result["session_ids_retained"], robots * 16)
                    self.assertLessEqual(result["late_sequences_retained"], robots * 8)
                    self.assertLessEqual(result["heap_entries_retained"], robots * 8)
                    if mode == "reject":
                        self.assertEqual(result["late_sequences_retained"], 0)
                        self.assertEqual(result["heap_entries_retained"], 0)
                    else:
                        self.assertGreater(result["late_sequences_retained"], 0)

    def test_wrong_robot_packet_cannot_refresh_another_robot(self):
        first = LinkMonitor(robot_id="robot_000", stale_after_s=2)
        second = LinkMonitor(robot_id="robot_001", stale_after_s=2)
        self.assertTrue(first.ingest(telemetry("robot_000", 0), 0.0))
        self.assertTrue(second.ingest(telemetry("robot_001", 0), 0.0))
        self.assertFalse(first.ingest(telemetry("robot_001", 1), 0.5))
        self.assertEqual(first.last_rejection, "unexpected_robot")
        self.assertTrue(second.ingest(telemetry("robot_001", 1), 1.5))
        self.assertEqual(first.snapshot(2.0).state, "STALE")
        self.assertEqual(second.snapshot(2.0).state, "HEALTHY")
        self.assertEqual(first.snapshot(2.0).accepted, 1)
        self.assertEqual(first.snapshot(2.0).rejected, 1)

    def test_benchmark_emits_bounded_synthetic_json(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "tools" / "benchmark_h16.py"),
             "--robots", "1", "2", "4", "--ticks", "8",
             "--repeats", "1", "--window", "8"],
            cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True,
            timeout=35, check=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "synthetic_offline")
        self.assertEqual(report["parameters"]["robot_counts"], [1, 2, 4])
        self.assertEqual(len(report["measurements"]), 6)
        self.assertFalse(report["claims"]["big_o_proven_by_timing"])
        self.assertFalse(report["claims"]["physical_link_validated"])
        self.assertFalse(report["claims"]["distributed_network_validated"])
        for point in report["measurements"]:
            self.assertEqual(point["expected_state_checks"],
                             point["robots"] * point["ticks_per_robot"])
            self.assertGreater(point["median_seconds"], 0)
            self.assertGreaterEqual(point["peak_tracemalloc_bytes"], 0)
            if point["robots"] == 1:
                self.assertIsNone(point["time_ratio_to_previous"])
            else:
                self.assertGreater(point["time_ratio_to_previous"], 0)

    def test_benchmark_rejects_unbounded_or_invalid_workloads(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        for arguments in (
            ["--robots", "2", "1"],
            ["--robots", "1", "1"],
            ["--robots", "1", "65"],
            ["--robots", "1", "2", "--ticks", "1024"],
            ["--robots", "1", "2", "--repeats", "100"],
            ["--robots", "1", "2", "--modes", "reject", "reject"],
        ):
            with self.subTest(arguments=arguments):
                completed = subprocess.run(
                    [sys.executable, str(PACKAGE_ROOT / "tools" / "benchmark_h16.py"),
                     *arguments],
                    cwd=PACKAGE_ROOT, env=env, capture_output=True,
                    text=True, timeout=15,
                )
                self.assertEqual(completed.returncode, 2)
                self.assertEqual(completed.stdout, "")
                self.assertIn("error:", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
