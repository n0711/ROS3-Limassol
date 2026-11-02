# SPDX-License-Identifier: Apache-2.0
"""H13: bounded-state and multi-source regression tests; entirely synthetic."""

import unittest
import os
from pathlib import Path
import subprocess
import sys

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.recording import MAX_RECORD_BYTES, Observation
from ros3_limassol.replay import run_replay
from ros3_limassol.telemetry import Telemetry


def sample(robot, session, sequence):
    # Values other than identity/sequence are schema placeholders, not sensor data.
    return Telemetry(
        schema_version=1, robot_id=robot, session_id=session,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


class SyntheticRecording:
    """Create observations lazily, without allocating an N-record trace."""

    def __init__(self, count):
        self.count = count
        self.position = 0
        self.calls = 0

    def readline(self, limit):
        if limit != MAX_RECORD_BYTES + 1:
            raise AssertionError("reader must request bounded lines")
        self.calls += 1
        if self.position >= self.count:
            return ""
        i = self.position
        self.position += 1
        return Observation(i * 0.01, sample("mega", "session_0", i)).to_json() + "\n"


class H13MonitorBoundsTests(unittest.TestCase):
    def test_two_monitors_stay_independent_across_repeated_outages(self):
        nano = LinkMonitor(robot_id="nano", stale_after_s=3.0)
        mega = LinkMonitor(robot_id="mega", stale_after_s=3.0)
        for cycle in range(12):
            t = cycle * 10.0
            self.assertTrue(nano.ingest(sample("nano", "continuous", cycle * 3), t))
            self.assertTrue(mega.ingest(sample("mega", f"boot_{cycle}", 0), t))
            self.assertTrue(nano.ingest(sample("nano", "continuous", cycle * 3 + 1), t + 2.0))
            self.assertEqual(nano.snapshot(t + 3.1).state, "HEALTHY")
            self.assertEqual(mega.snapshot(t + 3.1).state, "STALE")
            self.assertTrue(nano.ingest(sample("nano", "continuous", cycle * 3 + 2), t + 4.0))
            self.assertTrue(mega.ingest(sample("mega", f"boot_{cycle}_resume", 0), t + 4.0))
            self.assertEqual(mega.snapshot(t + 4.0).state, "HEALTHY")
            self.assertEqual(nano.snapshot(t + 4.0).state, "HEALTHY")
        self.assertEqual(nano.accepted, 36)
        self.assertEqual(mega.accepted, 24)
        self.assertEqual(nano.rejected, 0)
        self.assertEqual(mega.rejected, 0)

    def test_late_window_memory_is_bounded_after_large_sequence_jumps(self):
        window = 16
        monitor = LinkMonitor(robot_id="mega", late_samples="liveness", late_window=window)
        for i in range(2000):
            sequence = i * 1000
            self.assertTrue(monitor.ingest(sample("mega", "boot_0", sequence), i * 0.01))
            self.assertLessEqual(len(monitor._recent), window)
            self.assertEqual(len(monitor._recent_min_heap), len(monitor._recent))
            self.assertTrue(all(sequence - s < window for s in monitor._recent))
        self.assertEqual(monitor.accepted, 2000)
        self.assertFalse(monitor.ingest(sample("mega", "boot_0", 0), 20.1))
        self.assertEqual(monitor.last_rejection, "duplicate_or_out_of_order")
        self.assertTrue(monitor.ingest(sample("mega", "boot_1", 0), 20.2))
        self.assertEqual(monitor._recent, {0})
        self.assertEqual(len(monitor._recent_min_heap), 1)

    def test_session_limit_rejects_new_identity_without_refresh(self):
        monitor = LinkMonitor(robot_id="mega", stale_after_s=1.0, max_sessions=8)
        for i in range(8):
            self.assertTrue(monitor.ingest(sample("mega", f"boot_{i}", 0), i * 0.1))
        self.assertEqual(len(monitor._seen_sessions), 8)
        self.assertFalse(monitor.ingest(sample("mega", "boot_8", 0), 1.6))
        self.assertEqual(monitor.last_rejection, "session_limit")
        self.assertEqual(monitor.snapshot(1.75).state, "STALE")
        self.assertTrue(monitor.ingest(sample("mega", "boot_7", 1), 1.8))
        self.assertEqual(len(monitor._seen_sessions), 8)
        self.assertEqual(monitor.snapshot(1.8).state, "HEALTHY")

    def test_replay_reads_bounded_lines_and_does_not_require_trace_list(self):
        count = 4000
        stream = SyntheticRecording(count)
        events = list(run_replay(stream, robot_id="mega", stale_after_s=3.0))
        self.assertEqual(stream.position, count)
        self.assertEqual(stream.calls, count + 1)
        self.assertEqual([event["state"] for event in events],
                         ["WAITING", "HEALTHY", "HEALTHY"])
        self.assertEqual(events[-1]["event"], "summary")
        self.assertEqual(events[-1]["accepted"], count)
        self.assertEqual(events[-1]["rejected"], 0)


    def test_benchmark_command_smoke(self):
        package_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(package_root) + os.pathsep + env.get("PYTHONPATH", "")
        process = subprocess.run(
            [sys.executable, str(package_root / "tools" / "benchmark_h13.py"),
             "--sizes", "8", "16", "--repeats", "1"],
            cwd=package_root, env=env, capture_output=True, text=True,
            timeout=30, check=True,
        )
        for mode in ("mode=default", "mode=late", "mode=replay"):
            self.assertIn(mode, process.stdout)


if __name__ == "__main__":
    unittest.main()
