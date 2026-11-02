# SPDX-License-Identifier: Apache-2.0
"""H20: synthetic multi-robot JSONL recording/replay round-trip regressions."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ros3_limassol.recording import Observation, read_observations

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_replay_h20 import (  # noqa: E402
    audit, check_replay, one_robot,
)


class H20MultiRobotReplayTests(unittest.TestCase):
    def test_multiple_robots_have_exact_transition_and_summary_replay(self):
        for robots in (1, 4, 8):
            for policy in ("reject", "liveness"):
                with self.subTest(robots=robots, policy=policy):
                    report, traces = audit(
                        robots=robots, ticks=96, seed=2026, policies=(policy,))
                    self.assertEqual(len(traces), robots)
                    self.assertEqual(len(report["results"]), robots)
                    for result in report["results"]:
                        self.assertTrue(result["replay_exact_match"])
                        self.assertEqual(result["observations"], 96)
                        self.assertEqual(
                            result["accepted"] + result["rejected"]
                            + result["silence_ticks"], 96)
                        self.assertEqual(
                            [state["state"] for state in
                             result["observed_transitions"]][:1], ["WAITING"])
                        self.assertIn(
                            "STALE", [state["state"] for state in
                                      result["observed_transitions"]])
                        name = result["robot_id"] + "_" + policy + ".jsonl"
                        raw = traces[name]
                        self.assertEqual(
                            hashlib.sha256(raw.encode()).hexdigest(),
                            result["recording_sha256"],
                        )
                        records = list(read_observations(io.StringIO(raw)))
                        self.assertEqual(len(records), 96)
                        self.assertEqual(
                            [record.time_s for record in records],
                            [i * 0.25 for i in range(96)])
                    self.assertFalse(report["claims"]["physical_link_validated"])

    def test_same_seed_is_reproducible_across_robots(self):
        a, trace_a = audit(robots=4, ticks=72, seed=21)
        b, trace_b = audit(robots=4, ticks=72, seed=21)
        c, _ = audit(robots=4, ticks=72, seed=22)
        self.assertEqual(a, b)
        self.assertEqual(trace_a, trace_b)
        self.assertNotEqual(
            [row["recording_sha256"] for row in a["results"]],
            [row["recording_sha256"] for row in c["results"]],
        )

    def test_modified_recording_no_longer_matches_expected_trace(self):
        result, raw = one_robot(0, 2, 72, 17, "reject")
        self.assertTrue(result["replay_exact_match"])
        # A new silent observation changes the recorded final timestamp
        # and therefore the summary even if no other state changes occur.
        corrupt = raw + Observation(1000.0, None).to_json() + "\n"
        # Build the expected original events from the unmodified trace.
        from ros3_limassol.replay import run_replay
        expected = list(run_replay(
            io.StringIO(raw), robot_id="robot_000",
            stale_after_s=1.0, late_samples="reject",
        ))
        with self.assertRaisesRegex(AssertionError, "divergence"):
            check_replay(corrupt, expected, "robot_000", "reject")

    def test_cli_creates_exclusive_recordings_with_matching_hashes(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        with tempfile.TemporaryDirectory() as parent:
            destination = Path(parent) / "h20-synthetic"
            command = [
                sys.executable, str(ROOT / "tools" / "audit_replay_h20.py"),
                "--robots", "3", "--ticks", "48", "--seed", "11",
                "--output-dir", str(destination),
            ]
            done = subprocess.run(
                command, cwd=ROOT, env=env, capture_output=True, text=True,
                check=True, timeout=30,
            )
            report = json.loads(done.stdout)
            self.assertEqual(report["recordings_directory"], str(destination))
            self.assertEqual(report["source"], "synthetic_offline")
            self.assertEqual(len(report["results"]), 6)
            self.assertEqual(len(list(destination.glob("*.jsonl"))), 6)
            for row in report["results"]:
                name = row["robot_id"] + "_" + row["policy"] + ".jsonl"
                content = (destination / name).read_bytes()
                self.assertEqual(
                    hashlib.sha256(content).hexdigest(),
                    row["recording_sha256"],
                )
                self.assertEqual(len(list(read_observations(
                    io.StringIO(content.decode("utf-8"))))), 48)
            self.assertTrue(all(claim is False for claim in
                                report["claims"].values()))
            repeated = subprocess.run(
                command, cwd=ROOT, env=env, capture_output=True, text=True,
                timeout=30, check=False,
            )
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("error:", repeated.stderr)
            self.assertEqual(repeated.stdout, "")

    def test_cli_rejects_oversized_runs_without_output(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        cases = [
            ["--robots", "0"], ["--robots", "17"],
            ["--ticks", "15"], ["--ticks", "257"],
            ["--seed", "-1"],
            ["--policies", "reject", "reject"],
        ]
        for args in cases:
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "audit_replay_h20.py"),
                     *args], cwd=ROOT, env=env, capture_output=True,
                    text=True, timeout=20, check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
