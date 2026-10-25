import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.demo import main, run_demo
from ros3_limassol.simulator import UsvSimulator


class DemoTests(unittest.TestCase):
    def test_invalid_cli_options_do_not_reserve_recording_path(self):
        cases = [["--duration", "0"], ["--rate", "nan"],
                 ["--stale-after", "0"], ["--blackout-start", "-1"],
                 ["--blackout-duration", "-1"],
                 ["--duration", "3600", "--rate", "1000"]]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "retry.jsonl"
            for options in cases:
                with self.subTest(options=options):
                    with contextlib.redirect_stderr(io.StringIO()):
                        with self.assertRaises(SystemExit) as error:
                            main(["--record", str(path), *options])
                    self.assertEqual(error.exception.code, 2)
                    self.assertFalse(path.exists())
            # The same path is immediately usable after correcting the options.
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--record", str(path)])
            self.assertEqual(len(path.read_text().splitlines()), 81)

    def test_deterministic_blackout_and_recovery(self):
        events = list(run_demo())
        self.assertEqual(events, list(run_demo()))
        self.assertEqual([event["state"] for event in events[:-1]],
                         ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
        self.assertEqual(events[-2]["time_s"], 5.0)
        self.assertEqual(events[-1]["accepted"], 51)
        self.assertEqual(events[-1]["rejected"], 0)

    def test_no_blackout_and_no_recovery_cases(self):
        events = list(run_demo(blackout_duration_s=0))
        self.assertEqual([event["state"] for event in events[:-1]],
                         ["WAITING", "HEALTHY"])
        events = list(run_demo(blackout_start_s=0, blackout_duration_s=20))
        self.assertEqual(events[-1]["state"], "WAITING")
        self.assertEqual(events[-1]["accepted"], 0)
        events = list(run_demo(duration_s=4))
        self.assertEqual(events[-1]["state"], "STALE")

    def test_json_cli_output(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(["--json"])
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[-1]["event"], "summary")
        self.assertEqual(events[-1]["accepted"], 51)

    def test_invalid_demo_configuration(self):
        for options in ({"duration_s": 0}, {"rate_hz": 0}, {"rate_hz": True},
                        {"duration_s": 3601}, {"rate_hz": 1001},
                        {"duration_s": float("nan")},
                        {"duration_s": 3600, "rate_hz": 1000}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                list(run_demo(**options))

    def test_simulator_blackout_boundaries_and_sequence_gaps(self):
        sim = UsvSimulator(session_id="test")
        self.assertEqual(sim.sample(1.9, 1).sequence, 0)
        self.assertIsNone(sim.sample(2, 2))
        self.assertIsNone(sim.sample(4.99, 3))
        self.assertEqual(sim.sample(5, 4).sequence, 3)
        with self.assertRaises(ValueError):
            sim.sample(4, 5)

    def test_invalid_simulator_configuration(self):
        for options in ({"blackout_start_s": -1}, {"blackout_duration_s": -1},
                        {"blackout_start_s": float("inf")}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                UsvSimulator(**options)
