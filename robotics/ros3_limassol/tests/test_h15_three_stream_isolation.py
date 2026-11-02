# SPDX-License-Identifier: Apache-2.0
"""H15 metamorphic tests for three synthetic receiver streams.

Not three-vehicle SITL, physical transport, ROS graph or field validation.
"""

import io
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.impairment import parse_scenario, run_scenario
from ros3_limassol.replay import run_replay


def models():
    return [
        {"robot_id": "nano", "rate_hz": 5, "delay_s": 0.04,
         "jitter_s": 0.2, "loss": 0.05, "duplicate": 0.15},
        {"robot_id": "mega", "rate_hz": 5, "delay_s": 0.02,
         "jitter_s": 0.1, "duplicate": 0.05},
        {"robot_id": "rover", "rate_hz": 5, "jitter_s": 0.1,
         "loss": 0.1, "duplicate": 0.2, "restarts": [5]},
    ]


def scenario(robots, seed=11, policy="reject", duration=10):
    return parse_scenario({
        "seed": seed, "duration_s": duration, "tick_s": 0.1,
        "stale_after_s": 0.8, "late_samples": policy, "robots": robots,
    })


def by_robot(report):
    return {entry["robot_id"]: entry for entry in report["robots"]}


class H15ThreeStreamIsolationTests(unittest.TestCase):
    def test_fault_on_mega_never_changes_nano_or_rover_reports(self):
        # Metamorphic property: changing only one robot's outage schedule
        # must not perturb the other robots' deterministic outputs.
        for seed in (5, 11, 23):
            for policy in ("reject", "liveness"):
                with self.subTest(seed=seed, policy=policy):
                    original = models()
                    changed = models()
                    changed[1]["outages"] = [[3, 6]]
                    before = by_robot(run_scenario(scenario(
                        original, seed=seed, policy=policy
                    )))
                    after = by_robot(run_scenario(scenario(
                        changed, seed=seed, policy=policy
                    )))
                    self.assertEqual(before["nano"], after["nano"])
                    self.assertEqual(before["rover"], after["rover"])
                    self.assertGreater(before["mega"]["link"]["arrivals"],
                                       after["mega"]["link"]["arrivals"])
                    self.assertEqual(after["mega"]["link_model"]["outages"],
                                     [[3.0, 6.0]])

    def test_reordering_robots_does_not_change_individual_evidence(self):
        for seed in (5, 23):
            baseline = models()
            for policy in ("reject", "liveness"):
                with self.subTest(seed=seed, policy=policy):
                    first = by_robot(run_scenario(scenario(
                        baseline, seed=seed, policy=policy
                    )))
                    reordered = by_robot(run_scenario(scenario(
                        list(reversed(baseline)), seed=seed, policy=policy
                    )))
                    self.assertEqual(first, reordered)

    def test_three_stream_recordings_replay_to_reported_outcomes(self):
        changed = models()
        changed[1]["outages"] = [[3, 6]]
        for policy in ("reject", "liveness"):
            with self.subTest(policy=policy):
                config = scenario(changed, seed=17, policy=policy)
                with tempfile.TemporaryDirectory() as directory:
                    first = Path(directory) / "first"
                    second = Path(directory) / "second"
                    result = by_robot(run_scenario(config, first))
                    repeated = by_robot(run_scenario(config, second))
                    self.assertEqual(result, repeated)
                    for robot_id in ("nano", "mega", "rover"):
                        recorded = (first / f"{robot_id}.jsonl").read_bytes()
                        self.assertEqual(recorded,
                            (second / f"{robot_id}.jsonl").read_bytes())
                        events = list(run_replay(
                            io.StringIO(recorded.decode("utf-8")),
                            robot_id=robot_id, stale_after_s=config.stale_after_s,
                            late_samples=config.late_samples,
                        ))
                        final = events[-1]
                        observed = result[robot_id]["monitor"]
                        self.assertEqual(final["accepted"], observed["accepted"])
                        self.assertEqual(final["rejected"], observed["rejected"])
                        self.assertEqual(final["state"], observed["final_state"])

    def test_clean_three_robot_outage_does_not_stale_neighbors(self):
        robots = [
            {"robot_id": "nano", "rate_hz": 10},
            {"robot_id": "mega", "rate_hz": 10, "outages": [[3, 6]]},
            {"robot_id": "rover", "rate_hz": 10},
        ]
        result = by_robot(run_scenario(scenario(
            robots, seed=0, duration=10
        )))
        self.assertEqual(result["mega"]["ground_truth"]["detected_outages"], 1)
        self.assertEqual(result["mega"]["ground_truth"]["missed_outages"], 0)
        for robot_id in ("nano", "rover"):
            self.assertEqual(result[robot_id]["monitor"]["final_state"],
                             "HEALTHY")
            self.assertEqual(
                result[robot_id]["ground_truth"]["unexplained_stale_episodes"],
                []
            )


if __name__ == "__main__":
    unittest.main()
