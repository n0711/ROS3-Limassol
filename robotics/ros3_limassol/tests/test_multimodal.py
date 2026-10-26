# SPDX-License-Identifier: Apache-2.0
"""Synthetic evidence-composition tests; not real synchronized robot validation."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.analysis import fit_baseline
from ros3_limassol.multimodal import combine_evidence, main


def telemetry(i):
    return {
        "report_version": 1, "recording_parsed_to_eof": True,
        "recording_sha256": f"{i:064x}", "robot_id": "usv01",
        "stale_after_s": 1.0, "observation_count": 20,
        "payload_observation_count": 20, "silence_tick_count": 0,
        "accepted": 20, "rejected": 0,
        "observed_stale_change_count": 0,
        "observed_state_change_count": 1,
        "max_between_observation_gap_s": 0.1,
        "latitude_deg": 34.7,
    }


def vision():
    return {
        "vision_report_version": 1, "source": "vera-mot",
        "parsed_to_eof": True, "sequence": "M0203",
        "mot_sha256": "a" * 64,
        "track_observation_rows": 8, "distinct_sequence_local_track_ids": 2,
        "frames_with_output": 4, "first_output_frame": 1,
        "last_output_frame": 4, "mean_rows_per_output_frame": 2,
        "raw_boxes": [[1, 2, 3, 4]],
    }


def vlm():
    return {
        "vlm_report_version": 1, "source": "declared-external-vlm-output",
        "sequence": "M0203", "manifest_sha256": "b" * 64,
        "prompt_sha256": "c" * 64, "model_id": "research/model",
        "model_revision": "local-v1", "annotated_frames": 3,
        "label_counts": {"water": 2, "vehicle": 3},
        "caption": "Excluded from summarized evidence",
    }


class MultimodalTests(unittest.TestCase):
    def test_combines_independent_sources_without_leaking_raw_data(self):
        result = combine_evidence(telemetry(10), vision(), vlm=vlm())
        self.assertFalse(result["alignment_verified"])
        self.assertFalse(result["navigation_authority"])
        self.assertEqual(result["vlm"]["label_counts"], {"vehicle": 3, "water": 2})
        encoded = json.dumps(result)
        self.assertNotIn("latitude_deg", encoded)
        self.assertNotIn("raw_boxes", encoded)
        self.assertNotIn("caption", encoded)

    def test_optional_model_produces_non_authoritative_score(self):
        model = fit_baseline([telemetry(i) for i in range(1, 6)])
        result = combine_evidence(telemetry(10), vision(), anomaly_model=model)
        self.assertEqual(result["anomaly_assessment"]["classification"],
                         "within_exploratory_baseline")
        self.assertIsNone(result["vlm"])

    def test_rejects_mismatched_vlm_sequence(self):
        other = vlm()
        other["sequence"] = "M9999"
        with self.assertRaisesRegex(ValueError, "mismatches"):
            combine_evidence(telemetry(10), vision(), vlm=other)

    def test_rejects_lying_vision_counters(self):
        other = vision()
        other["mean_rows_per_output_frame"] = 99
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            combine_evidence(telemetry(10), other)

    def test_cli_does_not_print_partial_output_on_error(self):
        with tempfile.TemporaryDirectory() as temp:
            a = Path(temp) / "telemetry.json"
            b = Path(temp) / "vision.json"
            a.write_text(json.dumps(telemetry(10)), encoding="utf-8")
            b.write_text(json.dumps(vision()), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main([str(a), str(b)])
            self.assertFalse(json.loads(out.getvalue())["alignment_verified"])
            b.write_text("bad JSON", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([str(a), str(b)])
            self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
