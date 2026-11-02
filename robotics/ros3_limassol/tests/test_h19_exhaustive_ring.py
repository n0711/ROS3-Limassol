# SPDX-License-Identifier: Apache-2.0
"""H19 bounded exhaustive equivalence tests for the H18 ring experiment."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))
from exhaustive_ring_h19 import ALPHABET, explore  # noqa: E402


class H19ExhaustiveRingTests(unittest.TestCase):
    def test_all_four_step_event_words_match_for_three_windows(self):
        report = explore(depth=4, windows=(1, 2, 4))
        self.assertEqual(report["alphabet_size"], 10)
        self.assertEqual(report["traces_checked"], 3 * 10**4)
        self.assertEqual(report["state_step_checks"], 3 * 10**4 * 4)
        self.assertEqual(report["mismatches"], 0)
        self.assertFalse(report["claims"]["formal_equivalence_proven_for_all_inputs"])
        self.assertFalse(report["claims"]["production_monitor_changed"])
        self.assertFalse(report["claims"]["physical_link_validated"])

    def test_modulo_slots_are_unique_inside_each_window(self):
        # Mathematical injection property: W consecutive sequence integers
        # have W distinct remainders modulo W, for any starting sequence.
        for window in range(1, 65):
            for first in (0, 1, window - 1, 2**16, 2**63 - 1 - window):
                with self.subTest(window=window, first=first):
                    residues = {seq % window
                                for seq in range(first, first + window)}
                    self.assertEqual(len(residues), window)

    def test_shorter_depth_keeps_correct_trace_accounting(self):
        self.assertEqual(len(ALPHABET), 10)
        report = explore(depth=2, windows=(1, 3))
        self.assertEqual(report["traces_checked"], 200)
        self.assertEqual(report["state_step_checks"], 400)
        self.assertEqual(report["mismatches"], 0)

    def test_bounded_cli_json_and_invalid_args(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        tool = str(PACKAGE_ROOT / "tools" / "exhaustive_ring_h19.py")

        complete = subprocess.run(
            [sys.executable, tool, "--depth", "2", "--windows", "1", "2"],
            cwd=PACKAGE_ROOT, env=env, capture_output=True,
            text=True, timeout=30, check=True,
        )
        report = json.loads(complete.stdout)
        self.assertEqual(report["traces_checked"], 200)
        self.assertEqual(report["mismatches"], 0)
        self.assertFalse(report["claims"]["hard_realtime_guarantee"])

        for args in (
            ["--depth", "0"],
            ["--depth", "5"],
            ["--windows", "2", "1"],
            ["--windows", "1", "1"],
            ["--windows", "0"],
            ["--windows", "65"],
            ["--depth", "4", "--windows", "1", "2", "3", "4", "5", "6"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, tool, *args],
                    cwd=PACKAGE_ROOT, env=env, capture_output=True,
                    text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
