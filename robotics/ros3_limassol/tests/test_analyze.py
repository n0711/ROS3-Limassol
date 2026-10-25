import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.analyze import analyze_recording, main
from ros3_limassol.demo import run_demo
from ros3_limassol.recording import Observation
from test_telemetry import packet


def trace(*items):
    return io.StringIO("".join(item.to_json() + "\n" for item in items))


class AnalysisTests(unittest.TestCase):
    def test_default_blackout_report(self):
        stream = io.StringIO()
        list(run_demo(record_to=stream))
        report = analyze_recording(io.StringIO(stream.getvalue()))
        self.assertEqual(report["observations"], 81)
        self.assertEqual(report["silence_ticks"], 30)
        self.assertEqual((report["accepted"], report["rejected"]), (51, 0))
        self.assertEqual((report["stale_entries"], report["recoveries"]), (1, 1))
        self.assertAlmostEqual(report["state_hold_duration_s"]["STALE"], 2.1)
        self.assertAlmostEqual(sum(report["state_hold_duration_s"].values()), 8)
        self.assertAlmostEqual(report["max_observation_gap_s"], .1)

    def test_sparse_ticks_do_not_invent_timeout_evaluations(self):
        report = analyze_recording(trace(Observation(10, packet().to_json()),
                                         Observation(20, None)))
        self.assertEqual(report["observed_span_s"], 10)
        self.assertEqual(report["state_hold_duration_s"]["HEALTHY"], 10)
        self.assertEqual(report["state_hold_duration_s"]["STALE"], 0)
        self.assertTrue(report["final_stale_unresolved"])
        self.assertEqual(report["recoveries"], 0)

    def test_rejected_payloads_do_not_count_as_recovery(self):
        report = analyze_recording(trace(
            Observation(0, packet().to_json()), Observation(1, None),
            Observation(2, packet().to_json()), Observation(3, "{"),
            Observation(4, packet(sequence=1).to_json())))
        self.assertEqual((report["accepted"], report["rejected"]), (2, 2))
        self.assertEqual(report["recoveries"], 1)
        self.assertEqual(report["state_hold_duration_s"]["STALE"], 3)

    def test_empty_silent_and_equal_time_recordings(self):
        empty = analyze_recording(io.StringIO())
        self.assertIsNone(empty["first_time_s"])
        self.assertEqual(empty["observed_span_s"], 0)
        silent = analyze_recording(trace(Observation(7, None), Observation(9, None)))
        self.assertEqual(silent["state_hold_duration_s"]["WAITING"], 2)
        equal = analyze_recording(trace(Observation(0, packet().to_json()),
                                        Observation(0, None)))
        self.assertEqual(sum(equal["state_hold_duration_s"].values()), 0)

    def test_timeout_changes_analysis(self):
        items = (Observation(0, packet().to_json()), Observation(1, None))
        self.assertEqual(analyze_recording(trace(*items))["final_state"], "STALE")
        self.assertEqual(analyze_recording(trace(*items), stale_after_s=2)["final_state"],
                         "HEALTHY")

    def test_cli_invalid_input_emits_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            good = (Observation(0, None).to_json() + "\n").encode()
            for bad in (b"\xff\n", b"{}\n", (Observation(2, None).to_json() +
                        "\n" + Observation(1, None).to_json() + "\n").encode()):
                path.write_bytes(good + bad)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), \
                        contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main([str(path)])
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(output.getvalue(), "")
            path.write_bytes(good)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                main([str(path)])
            self.assertEqual(json.loads(output.getvalue())["observations"], 1)
