"""Tests for bounded, read-only evidence summaries on receiver recordings."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.demo import run_demo
from ros3_limassol.evidence import (
    MAX_REPORTED_TRANSITIONS, build_evidence, main as evidence_main,
)
from ros3_limassol.recording import Observation
from test_telemetry import packet


def encoded_trace(*observations):
    return b"".join((item.to_json() + "\n").encode("utf-8") for item in observations)


class EvidenceTests(unittest.TestCase):
    def test_demo_blackout_report_matches_replay_experiment(self):
        text = io.StringIO()
        list(run_demo(record_to=text))
        raw = text.getvalue().encode("utf-8")
        report = build_evidence(io.BytesIO(raw))
        self.assertTrue(report["recording_parsed_to_eof"])
        self.assertEqual(report["recording_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["observation_count"], 81)
        self.assertEqual(report["payload_observation_count"], 51)
        self.assertEqual(report["silence_tick_count"], 30)
        self.assertEqual((report["accepted"], report["rejected"]), (51, 0))
        self.assertEqual(report["final_state"], "HEALTHY")
        self.assertEqual(report["observed_stale_to_healthy_recoveries"], 1)
        self.assertEqual(
            [(event["to"], round(event["observed_at_s"], 1))
             for event in report["recent_state_changes"]],
            [("HEALTHY", 0.0), ("STALE", 2.9), ("HEALTHY", 5.0)],
        )
        self.assertFalse(report["state_changes_truncated"])

    def test_empty_recording_is_waiting_and_has_null_times(self):
        raw = b""
        report = build_evidence(io.BytesIO(raw))
        self.assertEqual(report["recording_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["observation_count"], 0)
        self.assertEqual(report["final_state"], "WAITING")
        self.assertIsNone(report["first_observation_s"])
        self.assertIsNone(report["last_observation_s"])
        self.assertIsNone(report["max_between_observation_gap_s"])
        self.assertEqual(report["recent_state_changes"], [])

    def test_rejections_and_silence_do_not_refresh_liveness(self):
        raw = encoded_trace(
            Observation(0, packet().to_json()),
            Observation(0.25, packet().to_json()),
            Observation(0.50, "{"),
            Observation(1.0, None),
        )
        report = build_evidence(io.BytesIO(raw))
        self.assertEqual(report["final_state"], "STALE")
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["rejected"], 2)
        self.assertEqual(report["rejection_reasons"], {
            "duplicate_or_out_of_order": 1,
            "invalid_payload": 1,
        })
        self.assertEqual(report["last_accepted_arrival_s"], 0)
        self.assertEqual(report["max_between_observation_gap_s"], 0.5)
        self.assertEqual(report["observed_stale_change_count"], 1)

    def test_same_trace_supports_alternative_timeout(self):
        text = io.StringIO()
        list(run_demo(record_to=text))
        report = build_evidence(io.BytesIO(text.getvalue().encode()), stale_after_s=2.0)
        self.assertEqual(report["stale_after_s"], 2.0)
        self.assertEqual(round(report["recent_state_changes"][1]["observed_at_s"], 1), 3.9)

    def test_transitions_keep_only_recent_bounded_tail(self):
        rows = []
        for index in range(MAX_REPORTED_TRANSITIONS + 10):
            now = float(index * 2)
            rows.append(Observation(now, packet(sequence=index).to_json()))
            rows.append(Observation(now + 1, None))
        report = build_evidence(io.BytesIO(encoded_trace(*rows)))
        self.assertGreater(report["observed_state_change_count"], MAX_REPORTED_TRANSITIONS)
        self.assertEqual(len(report["recent_state_changes"]), MAX_REPORTED_TRANSITIONS)
        self.assertTrue(report["state_changes_truncated"])
        self.assertEqual(report["final_state"], "STALE")

    def test_invalid_recording_does_not_output_partial_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.jsonl"
            path.write_bytes(encoded_trace(Observation(0, None)) + b"\xff\n")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as exc:
                    evidence_main([str(path)])
            self.assertEqual(exc.exception.code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertIn("line 2: recording must be UTF-8", stderr.getvalue())

    def test_cli_stdout_report_is_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            raw = encoded_trace(Observation(0, packet().to_json()), Observation(1, None))
            path.write_bytes(raw)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                evidence_main([str(path)])
            report = json.loads(stdout.getvalue())
            self.assertEqual(report["recording_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(report["observed_stale_change_count"], 1)


if __name__ == "__main__":
    unittest.main()
