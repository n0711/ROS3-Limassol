# SPDX-License-Identifier: Apache-2.0
"""H15 benchmark comparison tests; synthetic JSON only, no performance limits."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOL = Path(__file__).resolve().parents[1] / "tools" / "compare_h15.py"


def fixture(multiplier=1.0):
    rows = []
    for mode in ("default", "late"):
        for n in (8, 16):
            median = n * 0.01 * multiplier
            rows.append({
                "mode": mode,
                "observations": n,
                "median_seconds": median,
                "seconds_per_observation": median / n,
                "comparison_ratio": None if n == 8 else 2.0,
                "finite_size_log_slope": None if n == 8 else 1.0,
                "peak_tracemalloc_bytes": 128 + n,
            })
    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "timestamp_utc": "2026-11-02T00:00:00+00:00",
        "environment": {
            "python": "3.10.0", "implementation": "CPython",
            "platform": "Linux-test",
        },
        "sizes": [8, 16],
        "repeats": 3,
        "late_window": 16,
        "modes": ["default", "late"],
        "measurement_scope": "synthetic payload creation, ingestion and replay",
        "claims": {
            "big_o_proven_by_timing": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
        },
        "measurements": rows,
    }


def invoke(baseline, candidate):
    with tempfile.TemporaryDirectory() as directory:
        base_file = Path(directory) / "baseline.json"
        cand_file = Path(directory) / "candidate.json"
        base_file.write_text(
            baseline if isinstance(baseline, str) else json.dumps(baseline),
            encoding="utf-8",
        )
        cand_file.write_text(
            candidate if isinstance(candidate, str) else json.dumps(candidate),
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, str(TOOL), str(base_file), str(cand_file)],
            capture_output=True, text=True, timeout=20, check=False,
        )


class H15ComparisonTests(unittest.TestCase):
    def test_matching_runs_produce_descriptive_ratios_only(self):
        completed = invoke(fixture(), fixture(1.25))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "descriptive_only")
        self.assertTrue(report["same_protocol"])
        self.assertTrue(report["same_environment_labels"])
        self.assertFalse(report["same_host_verified"])
        self.assertEqual(len(report["comparison"]), 4)
        for point in report["comparison"]:
            self.assertAlmostEqual(point["candidate_over_baseline_time_ratio"], 1.25)
            self.assertAlmostEqual(point["relative_wall_change_pct"], 25.0)
        self.assertFalse(report["claims"]["big_o_proven_by_timing"])
        self.assertFalse(report["claims"]["regression_proven_by_median"])
        self.assertFalse(report["claims"]["physical_link_validated"])
        self.assertEqual(len(report["baseline_sha256"]), 64)

    def test_mismatch_never_emits_numeric_comparison(self):
        for kind in ("platform", "window", "scope", "repeats"):
            candidate = fixture()
            if kind == "platform":
                candidate["environment"]["platform"] = "other-machine"
            elif kind == "window":
                candidate["late_window"] = 32
            elif kind == "scope":
                candidate["measurement_scope"] = "different-workload"
            else:
                candidate["repeats"] = 2
            with self.subTest(kind=kind):
                completed = invoke(fixture(), candidate)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertEqual(result["status"], "not_comparable")
                self.assertEqual(result["comparison"], [])

    def test_invalid_report_fails_without_traceback(self):
        cases = []
        missing = fixture()
        missing["measurements"].pop()
        cases.append(missing)

        duplicate = fixture()
        duplicate["measurements"][1] = dict(duplicate["measurements"][0])
        cases.append(duplicate)

        bad_claim = fixture()
        bad_claim["claims"]["physical_link_validated"] = True
        cases.append(bad_claim)

        bad_number = fixture()
        bad_number["measurements"][0]["median_seconds"] = float("nan")
        cases.append(bad_number)

        bad_boolean = fixture()
        bad_boolean["sizes"] = [True, 16]
        cases.append(bad_boolean)

        bad_json = json.dumps(fixture()).replace(
            '"schema_version": 1,',
            '"schema_version": 1, "schema_version": 1,', 1,
        )
        cases.append(bad_json)

        for number, candidate in enumerate(cases):
            with self.subTest(case=number):
                completed = invoke(fixture(), candidate)
                self.assertEqual(completed.returncode, 2)
                self.assertIn("error:", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)
                self.assertEqual(completed.stdout, "")

    def test_inconsistent_measurements_are_rejected(self):
        for field in ("seconds_per_observation",
                      "comparison_ratio", "finite_size_log_slope"):
            candidate = fixture()
            candidate["measurements"][1][field] = 7.0
            with self.subTest(field=field):
                result = invoke(fixture(), candidate)
                self.assertEqual(result.returncode, 2)
                self.assertIn("inconsistent", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_actual_h14_output_is_accepted_by_comparator(self):
        root = Path(__file__).resolve().parents[1]
        benchmark = root / "tools" / "benchmark_h14.py"
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        completed = subprocess.run(
            [sys.executable, str(benchmark), "--sizes", "8", "16",
             "--repeats", "1", "--modes", "default"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30,
            check=True,
        )
        report = json.loads(completed.stdout)
        compared = invoke(report, report)
        self.assertEqual(compared.returncode, 0, compared.stderr)
        result = json.loads(compared.stdout)
        self.assertEqual(result["status"], "descriptive_only")
        self.assertEqual(len(result["comparison"]), 2)
        for point in result["comparison"]:
            self.assertEqual(point["candidate_over_baseline_time_ratio"], 1.0)

    def test_report_size_limit(self):
        candidate = json.dumps(fixture()) + " " * 2_000_001
        completed = invoke(fixture(), candidate)
        self.assertEqual(completed.returncode, 2)
        self.assertIn("exceeds 2,000,000 bytes", completed.stderr)
        self.assertEqual(completed.stdout, "")


if __name__ == "__main__":
    unittest.main()
