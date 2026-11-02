# SPDX-License-Identifier: Apache-2.0
"""H18: model-equivalence checks for an experimental ring late-sequence window.

The prototype is intentionally outside the production ROS3 package.
"""

import os
from pathlib import Path
import random
import subprocess
import sys
import unittest
from unittest.mock import patch

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "tools"))
from experimental_ring_h18 import RingLinkMonitor  # noqa: E402


def packet(robot, session, sequence):
    return Telemetry(
        schema_version=1,
        robot_id=robot, session_id=session,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


class H18RingEquivalenceTests(unittest.TestCase):
    def assert_same_state(self, reference, ring, now):
        self.assertEqual(reference.snapshot(now), ring.snapshot(now))
        self.assertEqual(reference.late_accepted, ring.late_accepted)
        self.assertLessEqual(ring.ring_storage_size(), ring.late_window)

    def test_seeded_equivalence_across_late_duplicates_restart_and_rejects(self):
        # Deterministic fuzzing; no wall-clock-based acceptance thresholds.
        for seed in (1, 7, 31, 97):
            for window in (1, 2, 8, 32):
                with self.subTest(seed=seed, window=window):
                    rng = random.Random(seed)
                    settings = dict(robot_id="mega", stale_after_s=0.75,
                                    late_samples="liveness", late_window=window,
                                    max_sessions=5)
                    reference = LinkMonitor(**settings)
                    ring = RingLinkMonitor(**settings)
                    highest_sent = {}
                    for tick in range(450):
                        now = tick * 0.125
                        session_index = tick // 75
                        session = f"boot_{session_index}"
                        decision = rng.random()
                        if decision < 0.14:
                            # Observed silence (no receiver packet).
                            self.assert_same_state(reference, ring, now)
                            continue
                        if decision < 0.22 and session_index > 0:
                            session = f"boot_{rng.randrange(session_index)}"
                        if session not in highest_sent:
                            highest_sent[session] = 0
                            sequence = 0
                        else:
                            high = highest_sent[session]
                            draw = rng.random()
                            if draw < 0.60:
                                sequence = high + rng.randint(1, 5)
                                highest_sent[session] = sequence
                            elif draw < 0.90:
                                sequence = max(0, high - rng.randint(0, window + 12))
                            else:
                                sequence = high
                        if decision > 0.98:
                            raw = "{"
                        elif decision > 0.93:
                            raw = packet("other", session, sequence)
                        else:
                            raw = packet("mega", session, sequence)
                        self.assertEqual(reference.ingest(raw, now),
                                         ring.ingest(raw, now))
                        self.assert_same_state(reference, ring, now)
                    self.assertEqual(ring.ring_storage_size(), window)

    def test_window_wrap_and_extreme_sequences(self):
        upper = 2**63 - 1
        for window in (1, 7, 64):
            with self.subTest(window=window):
                settings = dict(robot_id="mega", late_samples="liveness",
                                late_window=window)
                base = LinkMonitor(**settings)
                ring = RingLinkMonitor(**settings)
                sequence_values = [0, 1, 2, 3, 100000, 100000 - 1,
                                   100000 - 1, upper - 1, upper,
                                   upper - min(4, window - 1), upper]
                for index, sequence in enumerate(sequence_values):
                    raw = packet("mega", "boot_0", sequence)
                    self.assertEqual(base.ingest(raw, index),
                                     ring.ingest(raw, index))
                    self.assert_same_state(base, ring, index)

    def test_generation_reset_matches_retired_and_session_limit(self):
        base = LinkMonitor(robot_id="mega", late_samples="liveness",
                           late_window=8, max_sessions=2, stale_after_s=1)
        ring = RingLinkMonitor(robot_id="mega", late_samples="liveness",
                               late_window=8, max_sessions=2, stale_after_s=1)
        cases = [
            ("boot_0", 0), ("boot_0", 3), ("boot_0", 1),
            ("boot_1", 0), ("boot_1", 1), ("boot_0", 4),
            ("boot_2", 0), ("boot_1", 2),
        ]
        for index, (session, sequence) in enumerate(cases):
            now = index * 0.25
            raw = packet("mega", session, sequence)
            self.assertEqual(base.ingest(raw, now), ring.ingest(raw, now))
            self.assert_same_state(base, ring, now)
        self.assertEqual(base.last_rejection, "session_limit")
        self.assertEqual(ring.ring_storage_size(), 8)
        self.assertEqual(ring._ring_generation, 2)

    def test_ring_does_not_invoke_heap_operations(self):
        ring = RingLinkMonitor(robot_id="mega", late_samples="liveness",
                               late_window=16)
        with patch("ros3_limassol.monitor.heappush",
                   side_effect=AssertionError("heap push in ring")), \
             patch("ros3_limassol.monitor.heappop",
                   side_effect=AssertionError("heap pop in ring")):
            for i in range(512):
                self.assertTrue(ring.ingest(packet("mega", "boot_0", i),
                                            i * 0.01))
            self.assertTrue(ring.ingest(packet("mega", "boot_1", 0), 6))
        self.assertEqual(ring.accepted, 513)
        self.assertEqual(ring._recent, set())
        self.assertEqual(ring._recent_min_heap, [])
        self.assertEqual(ring.ring_storage_size(), 16)

    def test_default_reject_mode_is_behaviorally_unchanged(self):
        base = LinkMonitor(robot_id="mega", late_samples="reject")
        ring = RingLinkMonitor(robot_id="mega", late_samples="reject")
        self.assertEqual(ring.ring_storage_size(), 0)
        for seq in (0, 1, 1, 3, 2, 4):
            now = base._clock + 1 if base._clock is not None else 0
            raw = packet("mega", "boot_0", seq)
            self.assertEqual(base.ingest(raw, now), ring.ingest(raw, now))
            self.assert_same_state(base, ring, now)

    def test_benchmark_json_smoke_and_scope(self):
        import json
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        result = subprocess.run(
            [sys.executable, str(PACKAGE_ROOT / "tools" / "benchmark_ring_h18.py"),
             "--windows", "2", "8", "--samples", "24", "--repeats", "1"],
            cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True,
            timeout=35, check=True,
        )
        report = json.loads(result.stdout)
        self.assertEqual(report["source"], "synthetic_offline")
        self.assertEqual(len(report["measurements"]), 4)
        self.assertFalse(report["claims"]["production_monitor_changed"])
        self.assertFalse(report["claims"]["big_o_proven_by_timing"])
        self.assertFalse(report["claims"]["physical_link_validated"])
        for row in report["measurements"]:
            self.assertGreater(row["median_wall_seconds"], 0)
            self.assertGreaterEqual(row["peak_tracemalloc_bytes"], 0)

    def test_benchmark_rejects_unbounded_inputs(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        for args in (
            ["--windows", "16", "8"],
            ["--windows", "1", "1"],
            ["--windows", "0"],
            ["--windows", "2049"],
            ["--windows", "8", "--samples", "0"],
            ["--windows", "8", "--repeats", "100"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable,
                     str(PACKAGE_ROOT / "tools" / "benchmark_ring_h18.py"),
                     *args], cwd=PACKAGE_ROOT, env=env,
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
