# SPDX-License-Identifier: Apache-2.0
import json
import math
from pathlib import Path
import unittest

from ros3_limassol.localization_replay import evaluate

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "h24_synthetic.json"


class LocalizationReplayTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(FIXTURE.read_text())

    def test_documented_example(self):
        report = evaluate(self.dataset)
        self.assertEqual((report["matched"], report["missing"]), (2, 1))
        self.assertAlmostEqual(report["position_rmse_m"], math.sqrt(0.5))
        self.assertEqual(report["missing_intervals"], [{"first_missing_ms": 1000, "resumed_ms": 2000}])

    def test_no_matching_estimates(self):
        self.dataset["streams"]["odometry"][0]["t_ms"] = 1
        self.dataset["streams"]["odometry"].pop()
        report = evaluate(self.dataset)
        self.assertIsNone(report["position_rmse_m"])
        self.assertEqual(report["unmatched_odometry"], 1)
        self.assertEqual(report["missing"], 3)
        self.assertEqual(report["missing_intervals"], [{"first_missing_ms": 0, "resumed_ms": None}])

    def test_reject_repeated_stamp(self):
        self.dataset["streams"]["reference"][1]["t_ms"] = 0
        with self.assertRaises(ValueError):
            evaluate(self.dataset)

    def test_reject_nonfinite_sensor_value(self):
        self.dataset["streams"]["imu"][0]["angular_rate_flu_rad_s"][1] = float("nan")
        with self.assertRaises(ValueError):
            evaluate(self.dataset)

    def test_reject_unregistered_axes(self):
        self.dataset["calibration"]["imu_alignment"] = "unknown"
        with self.assertRaises(ValueError):
            evaluate(self.dataset)

    def test_reject_measured_label(self):
        self.dataset["source"] = "measured"
        with self.assertRaises(ValueError):
            evaluate(self.dataset)
