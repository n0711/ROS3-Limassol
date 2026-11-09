"""Deterministic regression tests for conditional sensor-clock bounds."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ros3_limassol.clock_bounds import assess_capture_age, evaluate_report


CAL = {"offset_s": 0.2, "uncertainty_s": 0.01, "drift_ppm": 100, "elapsed_s": 10}


def report(calibration=None):
    return {"schema_version": 1, "freshness_limit_s": 0.3,
            "calibration": copy.deepcopy(CAL if calibration is None else calibration),
            "samples": [{"sample_id": "camera.1", "capture_time_s": 10.0,
                         "receive_time_s": 10.4}]}


class ClockBoundsTests(unittest.TestCase):
    def test_exact_zero_uncertainty_and_boundary(self):
        cal = dict(CAL, uncertainty_s=0, drift_ppm=0, elapsed_s=0)
        result = assess_capture_age(10, 10.5, 0.3, cal)
        self.assertEqual(result["classification"], "within_declared_bound")
        self.assertAlmostEqual(result["min_age_s"], 0.3)

    def test_uncertainty_and_drift_are_propagated(self):
        result = assess_capture_age(10, 10.4, 0.3, CAL)
        self.assertEqual(result["classification"], "within_declared_bound")
        self.assertAlmostEqual(result["min_age_s"], 0.189)
        self.assertAlmostEqual(result["max_age_s"], 0.211)
        self.assertAlmostEqual(result["offset_error_bound_s"], 0.011)

    def test_outside_threshold(self):
        self.assertEqual(assess_capture_age(10, 11, 0.3, CAL)["classification"],
                         "outside_declared_bound")

    def test_indeterminate_straddling_threshold(self):
        self.assertEqual(assess_capture_age(10, 10.5, 0.3, CAL)["classification"],
                         "indeterminate")

    def test_negative_possible_age_is_clamped_at_zero(self):
        result = assess_capture_age(10, 10.19, 0.3, CAL)
        self.assertEqual(result["min_age_s"], 0.0)
        self.assertGreater(result["max_age_s"], 0.0)

    def test_impossible_receipt_is_inconsistent(self):
        result = assess_capture_age(10, 10.0, 0.3, CAL)
        self.assertEqual(result["classification"], "inconsistent_clock_bound")
        self.assertIsNone(result["max_age_s"])

    def test_missing_calibration_never_guesses_freshness(self):
        no_cal = report()
        no_cal["calibration"] = None
        outcome = evaluate_report(no_cal)
        self.assertEqual(outcome["results"][0]["classification"], "calibration_unavailable")
        self.assertFalse(outcome["alignment_verified"])
        self.assertIsNone(outcome["results"][0]["min_age_s"])

    def test_safeguards_against_invalid_numbers_and_bool(self):
        for bad in (True, float("nan"), float("inf"), -1, 1e30, "0"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                assess_capture_age(10, 10.5, bad, CAL)
        for bad in (False, -1, float("nan"), 10001):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                assess_capture_age(10, 10.5, 0.3, dict(CAL, drift_ppm=bad))

    def test_input_version_and_unknown_fields(self):
        for change in (dict(schema_version=True), dict(schema_version=2),
                       dict(schema_version=1, unexpected=5)):
            invalid = report()
            invalid.update(change)
            with self.assertRaises(ValueError):
                evaluate_report(invalid)

    def test_batch_bound_duplicate_ids_and_order(self):
        value = report()
        for _ in range(128):
            value["samples"].append({"sample_id": "x", "capture_time_s": 2,
                                     "receive_time_s": 3})
        with self.assertRaisesRegex(ValueError, "1 to 128"):
            evaluate_report(value)
        value["samples"] = value["samples"][:2]
        value["samples"][1]["sample_id"] = "camera.1"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            evaluate_report(value)
        value["samples"][1] = {"sample_id": "camera.2", "capture_time_s": 9,
                                "receive_time_s": 1}
        with self.assertRaisesRegex(ValueError, "backwards"):
            evaluate_report(value)

    def test_deterministic_output_and_no_auth_claim(self):
        self.assertEqual(evaluate_report(report()), evaluate_report(report()))
        self.assertFalse(evaluate_report(report())["navigation_authority"])

    def test_cli_and_duplicate_json_key_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "sample.json"
            p.write_text(json.dumps(report()), encoding="utf-8")
            cmd = [sys.executable, "-m", "ros3_limassol.clock_bounds", str(p)]
            ok = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(json.loads(ok.stdout)["sample_count"], 1)
            p.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
            bad = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("duplicate JSON key", bad.stderr)

    def test_cli_rejects_oversized_input(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "large.json"
            p.write_text("x" * 65537, encoding="utf-8")
            cmd = [sys.executable, "-m", "ros3_limassol.clock_bounds", str(p)]
            bad = subprocess.run(cmd, capture_output=True, text=True, check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("exceeds", bad.stderr)


if __name__ == "__main__":
    unittest.main()
