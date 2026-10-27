import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol import impairment
from ros3_limassol.evidence import build_evidence
from ros3_limassol.impairment import parse_scenario, run_scenario
from ros3_limassol.replay import run_replay


def scenario(robots, **top):
    return parse_scenario({"seed": 3, "duration_s": 30, "tick_s": 0.1,
                           "stale_after_s": 1.0, "robots": robots, **top})


def robot(report, robot_id):
    return next(r for r in report["robots"] if r["robot_id"] == robot_id)


class GroundTruthTests(unittest.TestCase):
    def test_clean_link_latencies_follow_the_stale_rule_exactly(self):
        report = run_scenario(scenario([{"robot_id": "usv01",
                                         "outages": [[5, 8], [15, 15.5]]}]))
        truth = robot(report, "usv01")["ground_truth"]
        long, short = truth["outages"]
        # Last sample 4.9 s + 1.0 s stale threshold; first sample after is 8.0 s.
        self.assertEqual((long["stale_at_s"], long["detection_latency_s"]), (5.9, 0.9))
        self.assertEqual((long["healthy_at_s"], long["recovery_latency_s"]), (8.0, 0.0))
        # A 0.5 s outage leaves a 0.6 s arrival gap, below the 1 s threshold.
        self.assertFalse(short["detected"])
        self.assertEqual((truth["detected_outages"], truth["missed_outages"]), (1, 1))
        self.assertEqual(truth["unexplained_stale_episodes"], [])

    def test_outage_starting_while_already_stale_is_not_a_miss(self):
        report = run_scenario(scenario([{"robot_id": "usv01",
                                         "outages": [[5, 8], [8, 10]]}]))
        truth = robot(report, "usv01")["ground_truth"]
        first, second = truth["outages"]
        self.assertEqual((first["already_stale"], first["detection_latency_s"]), (False, 0.9))
        self.assertTrue(second["detected"] and second["already_stale"])
        self.assertIsNone(second["detection_latency_s"])
        self.assertEqual(second["recovery_latency_s"], 0.0)
        self.assertEqual((truth["missed_outages"], truth["already_stale_outages"]), (0, 1))
        self.assertEqual(truth["max_detection_latency_s"], 0.9)

    def test_delay_shifts_recovery_but_not_detection(self):
        report = run_scenario(scenario([{"robot_id": "usv01", "delay_s": 0.25,
                                         "outages": [[5, 8]]}]))
        outage = robot(report, "usv01")["ground_truth"]["outages"][0]
        self.assertAlmostEqual(outage["detection_latency_s"], 1.2, places=6)
        self.assertAlmostEqual(outage["recovery_latency_s"], 0.25, places=6)

    def test_burst_loss_produces_stale_episodes_no_outage_explains(self):
        report = run_scenario(scenario([{"robot_id": "usv01",
                                         "burst_loss": {"enter": 0.05, "exit": 0.08}}]))
        result = robot(report, "usv01")
        self.assertGreater(result["link"]["dropped_burst"], 0)
        self.assertGreater(len(result["ground_truth"]["unexplained_stale_episodes"]), 0)

    def test_total_loss_stays_waiting_and_misses_outages(self):
        report = run_scenario(scenario([{"robot_id": "usv01", "loss": 1.0,
                                         "outages": [[5, 8]]}]))
        result = robot(report, "usv01")
        self.assertEqual(result["link"]["arrivals"], 0)
        self.assertEqual(result["monitor"]["final_state"], "WAITING")
        self.assertEqual(result["ground_truth"]["missed_outages"], 1)


class LinkEffectTests(unittest.TestCase):
    def test_duplicates_are_rejected_as_out_of_order(self):
        report = run_scenario(scenario([{"robot_id": "usv01", "duplicate": 1.0}]))
        result = robot(report, "usv01")
        self.assertEqual(result["link"]["duplicated"], result["link"]["generated"])
        self.assertEqual(result["monitor"]["rejection_reasons"],
                         {"duplicate_or_out_of_order": result["monitor"]["rejected"]})
        self.assertEqual(result["monitor"]["accepted"], result["link"]["generated"])

    def test_jitter_beyond_sample_period_rejects_fresh_samples(self):
        report = run_scenario(scenario([{"robot_id": "usv01", "jitter_s": 0.3}]))
        monitor = robot(report, "usv01")["monitor"]
        self.assertGreater(monitor["rejection_reasons"]["duplicate_or_out_of_order"], 30)
        self.assertEqual(monitor["final_state"], "HEALTHY")

    def test_liveness_policy_accepts_reordered_fresh_samples(self):
        robots = [{"robot_id": "usv01", "jitter_s": 0.3}]
        strict = robot(run_scenario(scenario(robots)), "usv01")["monitor"]
        late_report = run_scenario(scenario(robots, late_samples="liveness"))
        late = robot(late_report, "usv01")["monitor"]
        self.assertGreater(strict["rejected"], 30)
        self.assertEqual((late["rejected"], late["rejection_reasons"]), (0, {}))
        self.assertEqual(late["accepted"], strict["accepted"] + strict["rejected"])
        self.assertEqual(late_report["late_samples"], "liveness")
        with self.assertRaises(ValueError):
            scenario(robots, late_samples="accept")

    def test_restart_starts_a_new_accepted_session(self):
        clean = robot(run_scenario(scenario(
            [{"robot_id": "usv01", "restarts": [10, 20]}])), "usv01")
        self.assertEqual(clean["monitor"]["rejected"], 0)
        self.assertEqual(clean["monitor"]["accepted"], clean["link"]["generated"])
        late = robot(run_scenario(scenario(
            [{"robot_id": "usv01", "jitter_s": 0.5, "restarts": [10]}])), "usv01")
        self.assertIn("retired_session", late["monitor"]["rejection_reasons"])

    def test_robots_are_independent_and_runs_are_reproducible(self):
        robots = [{"robot_id": "usv01", "jitter_s": 0.2, "loss": 0.2},
                  {"robot_id": "usv02", "jitter_s": 0.2, "loss": 0.2}]
        first, second = run_scenario(scenario(robots)), run_scenario(scenario(robots))
        self.assertEqual(first, second)
        # Per-robot streams differ (aggregate drop counts can coincide by chance).
        streams = [impairment._send_and_deliver(model, scenario(robots))[0]
                   for model in scenario(robots).robots]
        self.assertNotEqual([t for t, _, _ in streams[0]], [t for t, _, _ in streams[1]])
        alone = run_scenario(scenario(robots[:1]))
        self.assertEqual(robot(alone, "usv01"), robot(first, "usv01"))
        reseeded = run_scenario(scenario(robots, seed=4))
        self.assertNotEqual(robot(reseeded, "usv01")["link"], robot(first, "usv01")["link"])

    def test_outage_does_not_reshuffle_other_samples(self):
        base = {"robot_id": "usv01", "jitter_s": 0.05, "loss": 0.1}
        with tempfile.TemporaryDirectory() as directory:
            run_scenario(scenario([base]), Path(directory) / "a")
            run_scenario(scenario([{**base, "outages": [[10, 12]]}]), Path(directory) / "b")
            a, b = ([json.loads(line) for line in (Path(directory) / name / "usv01.jsonl")
                     .read_text(encoding="utf-8").splitlines() if '"payload":"' in line]
                    for name in ("a", "b"))
        outside = lambda rows: [(r["time_s"], r["payload"]) for r in rows
                                if not 10 <= json.loads(r["payload"])["timestamp_ns"] / 1e9 < 12]
        self.assertEqual(outside(a), outside(b))


class RecordingAndCliTests(unittest.TestCase):
    def test_recordings_replay_to_the_reported_counts_and_never_overwrite(self):
        sc = scenario([{"robot_id": "usv01", "jitter_s": 0.2, "duplicate": 0.1},
                       {"robot_id": "usv02", "outages": [[3, 6]]}])
        with tempfile.TemporaryDirectory() as directory:
            report = run_scenario(sc, directory)
            for result in report["robots"]:
                with (Path(directory) / result["recording"]).open("rb") as stream:
                    evidence = build_evidence(stream, result["robot_id"], 1.0)
                self.assertEqual((evidence["accepted"], evidence["rejected"]),
                                 (result["monitor"]["accepted"], result["monitor"]["rejected"]))
            with self.assertRaises(ValueError):
                run_scenario(sc, directory)

    def test_rejects_invalid_scenarios(self):
        bad = [
            {"robots": [{"robot_id": "usv01", "typo": 1}]},
            {"robots": [{"robot_id": "usv01", "outages": [[5, 8], [7, 9]]}]},
            {"robots": [{"robot_id": "usv01"}, {"robot_id": "usv01"}]},
            {"robots": [{"robot_id": "usv01", "burst_loss": {"enter": 0.1, "exit": 0}}]},
            {"robots": [{"robot_id": "usv01", "restarts": [5, 5]}]},
            {"robots": [{"robot_id": "usv01", "loss": 1.5}]},
            {"robots": [{"robot_id": "usv01", "outages": [[5, 99]]}], "duration_s": 30},
            {"robots": []},
            {"robots": [{"robot_id": "usv01"}], "seed": -1},
            {"robots": [{"robot_id": "usv01", "rate_hz": True}]},
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_scenario(data)

    def test_documented_example_scenario_runs(self):
        path = Path(__file__).resolve().parents[1] / "docs" / "impairment-example.json"
        report = run_scenario(parse_scenario(json.loads(path.read_text(encoding="utf-8"))))
        self.assertEqual([r["robot_id"] for r in report["robots"]], ["usv01", "usv02"])
        self.assertEqual(robot(report, "usv01")["ground_truth"]["detected_outages"], 1)

    def test_cli_prints_report_and_rejects_nan(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "s.json"
            path.write_text('{"duration_s": 5, "robots": [{"robot_id": "usv01"}]}',
                            encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                impairment.main([str(path)])
            self.assertEqual(json.loads(out.getvalue())["robots"][0]["monitor"]["accepted"], 51)
            path.write_text('{"duration_s": NaN, "robots": [{"robot_id": "usv01"}]}',
                            encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                impairment.main([str(path)])


class LiveAlignmentTests(unittest.TestCase):
    """Public helpers that let live traffic share the model's randomness and scoring."""

    def test_link_fates_reproduce_the_reported_link_counts(self):
        sc = scenario([{"robot_id": "usv01", "delay_s": 0.1, "jitter_s": 0.3, "loss": 0.1,
                        "burst_loss": {"enter": 0.05, "exit": 0.3}, "duplicate": 0.05}])
        link = robot(run_scenario(sc), "usv01")["link"]
        fates = impairment.link_fates(sc.robots[0], sc.seed)
        drawn = [next(fates) for _ in range(link["generated"])]
        delivered = [f for f in drawn if not f.burst and not f.lost]
        self.assertEqual(sum(f.burst for f in drawn), link["dropped_burst"])
        self.assertEqual(sum(not f.burst and f.lost for f in drawn), link["dropped_loss"])
        self.assertEqual(sum(f.copies == 2 for f in delivered), link["duplicated"])
        self.assertTrue(all(0.1 <= d <= 0.4 for f in drawn for d in f.delays))

    def test_link_fates_are_reproducible_and_independent_per_robot(self):
        sc = scenario([{"robot_id": "usv01", "loss": 0.5}, {"robot_id": "usv02", "loss": 0.5}])

        def first_losses(model):
            fates = impairment.link_fates(model, sc.seed)
            return [next(fates).lost for _ in range(200)]

        self.assertEqual(first_losses(sc.robots[0]), first_losses(sc.robots[0]))
        self.assertNotEqual(first_losses(sc.robots[0]), first_losses(sc.robots[1]))

    def test_match_outages_scores_a_replayed_recording_like_the_report(self):
        sc = scenario([{"robot_id": "usv01", "loss": 0.2,
                        "outages": [[5, 8], [15, 15.5], [20, 23]]}])
        with tempfile.TemporaryDirectory() as directory:
            report = robot(run_scenario(sc, directory), "usv01")
            with (Path(directory) / report["recording"]).open(encoding="utf-8") as stream:
                events = list(run_replay(stream, "usv01", sc.stale_after_s))
        matched, unexplained = impairment.match_outages(sc.robots[0], sc, events)
        self.assertEqual(matched, report["ground_truth"]["outages"])
        self.assertEqual(unexplained, report["ground_truth"]["unexplained_stale_episodes"])


if __name__ == "__main__":
    unittest.main()
