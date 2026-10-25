import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ros3_limassol.demo import main as demo_main, run_demo
from ros3_limassol.recording import (
    MAX_RECORD_BYTES, Observation, read_observations,
)
from ros3_limassol.replay import main as replay_main, run_replay
from test_telemetry import packet


def trace(*observations):
    return io.StringIO("".join(item.to_json() + "\n" for item in observations))


class ReplayTests(unittest.TestCase):
    def test_cli_invalid_utf8_reports_actual_record_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "damaged.jsonl"
            for prefix, expected_line in ((b"", 1),
                    ((Observation(0, None).to_json() + "\n").encode(), 2)):
                with self.subTest(expected_line=expected_line):
                    path.write_bytes(prefix + b"\xff\n")
                    errors = io.StringIO()
                    with contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(errors):
                        with self.assertRaises(SystemExit) as error:
                            replay_main([str(path)])
                    self.assertEqual(error.exception.code, 2)
                    self.assertIn(f"line {expected_line}: recording must be UTF-8",
                                  errors.getvalue())
                    self.assertNotIn("Traceback", errors.getvalue())

    def test_recorded_blackout_reproduces_every_demo_event(self):
        stream = io.StringIO()
        expected = list(run_demo(record_to=stream))
        records = stream.getvalue().splitlines()
        self.assertEqual(len(records), 81)
        self.assertEqual(sum(json.loads(line)["payload"] is None for line in records), 30)
        self.assertEqual(list(run_replay(io.StringIO(stream.getvalue()))), expected)
        self.assertEqual(expected[-1]["accepted"], 51)

    def test_same_trace_can_evaluate_a_different_timeout(self):
        stream = io.StringIO()
        list(run_demo(record_to=stream))
        events = list(run_replay(io.StringIO(stream.getvalue()), stale_after_s=2.0))
        self.assertEqual([item["state"] for item in events[:-1]],
                         ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
        self.assertEqual(events[2]["time_s"], 3.9)
        self.assertEqual(events[3]["time_s"], 5.0)

    def test_silence_at_end_of_trace_is_observed(self):
        events = list(run_replay(trace(
            Observation(0, packet().to_json()), Observation(1, None),
            Observation(2, None),
        )))
        self.assertEqual(events[-1]["state"], "STALE")
        self.assertEqual(events[-1]["age_s"], 2)
        self.assertEqual(events[-1]["accepted"], 1)

    def test_invalid_duplicate_and_wrong_robot_do_not_refresh_arrival(self):
        events = list(run_replay(trace(
            Observation(0, packet().to_json()),
            Observation(0.4, packet().to_json()),
            Observation(0.5, packet(robot_id="other").to_json()),
            Observation(0.8, "{"), Observation(1, None),
        )))
        self.assertEqual(events[-1]["state"], "STALE")
        self.assertEqual(events[-1]["accepted"], 1)
        self.assertEqual(events[-1]["rejected"], 3)
        self.assertEqual(events[-1]["last_rejection"], "invalid_payload")

    def test_restart_and_retired_session_survive_replay(self):
        events = list(run_replay(trace(
            Observation(0, packet(sequence=40).to_json()),
            Observation(1, packet(session_id="boot_2").to_json()),
            Observation(1.5, packet(sequence=41).to_json()),
            Observation(2, None),
        )))
        self.assertEqual(events[-1]["accepted"], 2)
        self.assertEqual(events[-1]["rejected"], 1)
        self.assertEqual(events[-1]["last_rejection"], "retired_session")
        self.assertEqual(events[-1]["state"], "STALE")

    def test_equal_receiver_times_are_valid(self):
        events = list(run_replay(trace(
            Observation(0, packet().to_json()),
            Observation(0, packet(sequence=1).to_json()),
        )))
        self.assertEqual(events[-1]["accepted"], 2)

    def test_empty_trace_stays_waiting(self):
        events = list(run_replay(io.StringIO("")))
        self.assertEqual(events[-1]["state"], "WAITING")
        self.assertEqual(events[-1]["accepted"], 0)

    def test_backwards_receiver_time_reports_line(self):
        with self.assertRaisesRegex(ValueError, "line 2:.*backwards"):
            list(run_replay(trace(Observation(2, None), Observation(1, None))))

    def test_invalid_envelopes_are_distinct_from_rejected_telemetry(self):
        raw = Observation(0, None).to_json()
        cases = ["{}", "[]", "null", "{", raw.replace('"time_s":0', '"time_s":-1'),
                 raw.replace('"time_s":0', '"time_s":true'),
                 raw.replace('"time_s":0', '"time_s":NaN'),
                 raw.replace('"time_s":0', '"time_s":Infinity'),
                 raw.replace('"record_version":1', '"record_version":true'),
                 raw.replace('"record_version":1', '"record_version":2'),
                 raw.replace('"payload":null', '"payload":false'),
                 raw.replace('"payload":null', '"payload":null,"payload":null'),
                 raw[:-1] + ',"extra":0}']
        for item in cases:
            with self.subTest(raw=item), self.assertRaisesRegex(ValueError, "line 1:"):
                list(run_replay(io.StringIO(item + "\n")))

    def test_record_lines_payloads_and_total_count_are_bounded(self):
        for raw in (" " * (MAX_RECORD_BYTES + 1), "é" * 20000,
                    "[" * 2000 + "]" * 2000, "\ud800"):
            with self.subTest(raw=repr(raw[:30])), self.assertRaises(ValueError):
                Observation.from_json(raw)
        with self.assertRaises(ValueError):
            Observation(0, "x" * 4097)
        with self.assertRaises(ValueError):
            Observation(0, "é" * 2500)
        with patch("ros3_limassol.recording.MAX_RECORDS", 2):
            with self.assertRaisesRegex(ValueError, "exceeds 2 observations"):
                list(read_observations(trace(*[Observation(0, None)] * 3)))

    def test_cli_record_then_replay_and_existing_file_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                demo_main(["--record", str(path), "--json"])
            recorded = path.read_bytes()
            replayed = io.StringIO()
            with contextlib.redirect_stdout(replayed):
                replay_main([str(path), "--json"])
            self.assertEqual(replayed.getvalue(), output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                demo_main(["--record", str(path)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(path.read_bytes(), recorded)

    def test_replay_cli_reports_missing_and_malformed_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.jsonl"
            for contents in (None, "not json\n", '{"time_s": 0}\n'):
                if contents is not None:
                    path.write_text(contents, encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
                        io.StringIO()), self.assertRaises(SystemExit) as error:
                    replay_main([str(path)])
                self.assertEqual(error.exception.code, 2)

    def test_demo_sample_limit_includes_final_endpoint(self):
        with self.assertRaisesRegex(ValueError, "one million"):
            next(run_demo(duration_s=1000, rate_hz=1000))
