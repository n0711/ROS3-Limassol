# SPDX-License-Identifier: Apache-2.0
"""H19 independent reference-oracle checks for synthetic receiver events."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from ros3_limassol.monitor import LinkMonitor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_h19 import (  # noqa: E402
    MAX_SESSIONS, LATE_WINDOW, Reference, make_packet, simulate,
)


class H19OracleTests(unittest.TestCase):
    def test_seeded_interleavings_match_independent_reference(self):
        for policy in ("reject", "liveness"):
            for robots in (1, 4, 12):
                for seed in (0, 17, 2026):
                    with self.subTest(policy=policy, robots=robots, seed=seed):
                        result = simulate(robots, 192, seed, policy)
                        self.assertEqual(result["snapshots_checked"], robots * 192)
                        self.assertEqual(
                            result["injected_observations"],
                            result["accepted_total"] + result["rejected_total"],
                        )
                        self.assertLessEqual(
                            result["session_ids_retained"],
                            robots * MAX_SESSIONS,
                        )
                        self.assertLessEqual(
                            result["late_entries_retained"],
                            robots * LATE_WINDOW,
                        )
                        self.assertEqual(len(result["trace_sha256"]), 64)
                        if policy == "reject":
                            self.assertEqual(result["late_entries_retained"], 0)

    def test_seeded_traces_are_reproducible_and_distinct(self):
        first = simulate(6, 144, 1234, "liveness")
        second = simulate(6, 144, 1234, "liveness")
        third = simulate(6, 144, 5678, "liveness")
        self.assertEqual(first, second)
        self.assertNotEqual(first["trace_sha256"], third["trace_sha256"])
        self.assertGreater(first["rejected_total"], 0)
        self.assertGreater(first["accepted_total"], 0)

    def test_session_window_boundary_and_retired_session(self):
        for policy in ("reject", "liveness"):
            with self.subTest(policy=policy):
                monitor = LinkMonitor(
                    robot_id="robot_000", stale_after_s=1.0,
                    late_samples=policy, late_window=16, max_sessions=4,
                )
                oracle = Reference("robot_000", policy)
                events = [
                    (0.00, "robot_000", "boot_0", 100, False),
                    (0.25, "robot_000", "boot_0", 85, False),
                    (0.50, "robot_000", "boot_0", 84, False),
                    (0.75, "robot_000", "boot_0", 85, False),
                    (1.00, "robot_000", "boot_1", 0, False),
                    (1.25, "robot_000", "boot_0", 101, False),
                    (1.50, "robot_001", "boot_1", 1, False),
                    (1.75, "robot_000", "boot_1", 1, True),
                ]
                for now, robot, session, sequence, invalid in events:
                    payload = "{}" if invalid else make_packet(robot, session, sequence)
                    actual = monitor.ingest(payload, now)
                    expected = oracle.accept(
                        robot, session, sequence, now, invalid=invalid)
                    self.assertEqual(actual, expected)
                    state = monitor.snapshot(now)
                    for field, value in oracle.snapshot(now).items():
                        self.assertEqual(getattr(state, field), value)
                self.assertEqual(monitor.last_rejection, "invalid_payload")
                self.assertEqual(monitor.rejected, 6 if policy == "reject" else 5)
                self.assertEqual(monitor.accepted, 2 if policy == "reject" else 3)

    def test_cli_produces_explicitly_synthetic_report(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        done = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "audit_h19.py"),
             "--robots", "4", "--ticks", "32", "--seed", "17"],
            cwd=ROOT, env=env, capture_output=True, text=True,
            timeout=30, check=True,
        )
        report = json.loads(done.stdout)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["source"], "synthetic_offline")
        self.assertEqual(len(report["results"]), 2)
        self.assertEqual(report["parameters"]["modes"], ["reject", "liveness"])
        for result in report["results"]:
            self.assertEqual(result["snapshots_checked"], 128)
            self.assertEqual(result["robots"], 4)
        for verified in report["claims"].values():
            self.assertIs(verified, False)

    def test_cli_rejects_invalid_or_unbounded_runs(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        cases = [
            ["--robots", "0"], ["--robots", "33"], ["--ticks", "7"],
            ["--ticks", "385"], ["--seed", "-1"],
            ["--modes", "reject", "reject"],
            ["--robots", "32", "--ticks", "384"],  # 2 modes exceed budget
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                done = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "audit_h19.py"),
                     *arguments], cwd=ROOT, env=env, capture_output=True,
                    text=True, timeout=15, check=False,
                )
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertIn("error:", done.stderr)
                self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
