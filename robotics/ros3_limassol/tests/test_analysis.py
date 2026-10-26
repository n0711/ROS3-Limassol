# SPDX-License-Identifier: Apache-2.0
"""Read-only, deterministic tests for the offline aggregate anomaly baseline."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.analysis import (
    evidence_features, fit_baseline, load_json, main, score_report,
)


def report(index, *, stale=0, rejected=0, silence=0, gap=0.1,
           robot="usv01", timeout=1.0):
    payload = 20
    return {
        "report_version": 1,
        "recording_parsed_to_eof": True,
        "recording_sha256": f"{index:064x}",
        "robot_id": robot,
        "stale_after_s": timeout,
        "observation_count": payload + silence,
        "payload_observation_count": payload,
        "silence_tick_count": silence,
        "accepted": payload - rejected,
        "rejected": rejected,
        "observed_stale_change_count": stale,
        "observed_state_change_count": stale + 1,
        "max_between_observation_gap_s": gap,
        "latitude_deg": 34.0,  # Ignore any unexpected sensitive fields.
    }


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.baseline = [report(i + 1) for i in range(5)]

    def test_features_exclude_raw_position_and_are_observation_based(self):
        result = evidence_features(report(8, rejected=2, silence=10, stale=1, gap=1.5))
        self.assertNotIn("latitude_deg", json.dumps(result))
        self.assertEqual(result["features"]["rejected_payload_fraction"], 0.1)
        self.assertEqual(result["features"]["silence_tick_fraction"], 10 / 30)
        self.assertEqual(result["features"]["observed_stale_changes_per_tick"], 1 / 30)
        self.assertEqual(result["features"]["max_tick_gap_over_timeout"], 1.5)

    def test_fit_and_score_held_out(self):
        model = fit_baseline(self.baseline)
        normal = score_report(model, report(99))
        outlier = score_report(model, report(100, rejected=10, silence=15, stale=3, gap=3))
        self.assertEqual(model["training_report_count"], 5)
        self.assertEqual(normal["classification"], "within_exploratory_baseline")
        self.assertEqual(outlier["classification"], "statistical_outlier")
        self.assertTrue(outlier["feature_scores"]["rejected_payload_fraction"]["outlier"])

    def test_duplicate_or_incompatible_training_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            fit_baseline(self.baseline[:4] + [self.baseline[0]])
        with self.assertRaisesRegex(ValueError, "robot_id"):
            fit_baseline(self.baseline[:4] + [report(6, robot="rover01")])
        with self.assertRaisesRegex(ValueError, "5 to 128"):
            fit_baseline(self.baseline[:4])

    def test_holdout_is_required(self):
        model = fit_baseline(self.baseline)
        with self.assertRaisesRegex(ValueError, "holdout"):
            score_report(model, self.baseline[0])

    def test_fails_closed_on_inconsistent_counter_or_missing_payload(self):
        corrupt = report(10)
        corrupt["accepted"] = 99
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            evidence_features(corrupt)
        corrupt = report(10)
        corrupt["payload_observation_count"] = 0
        with self.assertRaises(ValueError):
            evidence_features(corrupt)

    def test_rejects_nonfinite_or_duplicate_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "bad.json"
            f.write_text('{"report_version":1,"report_version":1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_json(f)
            f.write_text('{"x":NaN}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-finite"):
                load_json(f)

    def test_cli_never_prints_partial_json_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.json"
            path.write_text(json.dumps(report(10)), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["features", str(path)])
            self.assertEqual(json.loads(out.getvalue())["feature_version"], 1)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(["fit", str(path)])
            self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
