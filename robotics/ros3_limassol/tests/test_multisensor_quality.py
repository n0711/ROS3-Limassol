# SPDX-License-Identifier: Apache-2.0
import unittest

from ros3_limassol.multisensor_quality import summarize


class MultisensorQualityTest(unittest.TestCase):
    def setUp(self):
        self.batch = {
            "schema_version": 1, "freshness_limit_s": 0.5,
            "calibration": None, "samples": [
                {"sample_id": "1", "receive_time_s": 8, "capture_time_s": 7}
            ],
        }
        self.manifest = {"version": 1, "expected": ["imu", "camera"], "reports": {}}

    def test_missing_inventory(self):
        sensors = summarize(self.manifest)["sensors"]
        self.assertEqual(set(sensors), {"imu", "camera"})
        self.assertTrue(all(row["status"] == "missing_observations" for row in sensors.values()))

    def test_independent_calibrations_and_shared_sample_id(self):
        calibration = {"offset_s": 1, "uncertainty_s": 0.25, "drift_ppm": 0, "elapsed_s": 0}
        self.manifest["reports"] = {"camera": self.batch, "imu": dict(self.batch, calibration=calibration)}
        report = summarize(self.manifest)
        imu = report["sensors"]["imu"]["samples"][0]
        camera = report["sensors"]["camera"]["samples"][0]
        self.assertEqual((imu["min_age_s"], imu["max_age_s"]), (0, 0.25))
        self.assertEqual(imu["receive_time_s"], 8)
        self.assertEqual(camera["classification"], "calibration_unavailable")
        self.assertIsNone(camera["max_age_s"])
        self.assertFalse(report["alignment_verified"])

    def test_reject_invalid_inventories(self):
        for expected in ([], ["x"] * 2, ["a/b"], list(map(str, range(17)))):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                summarize(dict(self.manifest, expected=expected))

    def test_reject_unknown_or_invalid_reports(self):
        for reports in ({"other": self.batch}, {"imu": None}, {"imu": dict(self.batch, samples=[])}):
            with self.subTest(reports=reports), self.assertRaises(ValueError):
                summarize(dict(self.manifest, reports=reports))
