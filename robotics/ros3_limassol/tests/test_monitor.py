import unittest

from ros3_limassol.monitor import LinkMonitor
from test_telemetry import packet


class LinkMonitorTests(unittest.TestCase):
    def test_waiting_healthy_stale_and_recovery(self):
        monitor = LinkMonitor(stale_after_s=1.0)
        self.assertEqual(monitor.snapshot(0).state, "WAITING")
        self.assertIsNone(monitor.snapshot(0).age_s)
        self.assertTrue(monitor.ingest(packet().to_json(), 0))
        self.assertEqual(monitor.snapshot(0.999).state, "HEALTHY")
        self.assertEqual(monitor.snapshot(1.0).state, "STALE")
        self.assertTrue(monitor.ingest(packet(sequence=1).to_json(), 1.1))
        self.assertEqual(monitor.snapshot(1.1).state, "HEALTHY")

    def test_rejected_packets_do_not_refresh_liveness(self):
        monitor = LinkMonitor()
        monitor.ingest(packet(sequence=4).to_json(), 0)
        for raw in ("{}", packet(robot_id="other").to_json(),
                    packet(sequence=4).to_json(), packet(sequence=3).to_json()):
            self.assertFalse(monitor.ingest(raw, 0.8))
        status = monitor.snapshot(1)
        self.assertEqual(status.state, "STALE")
        self.assertEqual(status.accepted, 1)
        self.assertEqual(status.rejected, 4)
        self.assertEqual(status.last_sequence, 4)

    def test_restart_accepts_new_session_and_rejects_retired_session(self):
        monitor = LinkMonitor()
        monitor.ingest(packet(sequence=40).to_json(), 0)
        self.assertTrue(monitor.ingest(packet(session_id="boot_2").to_json(), 1))
        self.assertFalse(monitor.ingest(packet(sequence=41).to_json(), 1.5))
        self.assertEqual(monitor.last_rejection, "retired_session")
        self.assertEqual(monitor.snapshot(2).state, "STALE")

    def test_session_history_is_bounded_and_existing_session_continues(self):
        monitor = LinkMonitor(max_sessions=1)
        self.assertTrue(monitor.ingest(packet().to_json(), 0))
        self.assertFalse(monitor.ingest(packet(session_id="boot_2").to_json(), 0.5))
        self.assertEqual(monitor.last_rejection, "session_limit")
        self.assertTrue(monitor.ingest(packet(sequence=1).to_json(), 0.8))

    def test_source_timestamp_does_not_drive_arrival_liveness(self):
        monitor = LinkMonitor()
        monitor.ingest(packet(timestamp_ns=0).to_json(), 10)
        self.assertEqual(monitor.snapshot(10).state, "HEALTHY")
        monitor.ingest(packet(sequence=1, timestamp_ns=2**63 - 1).to_json(), 11)
        self.assertEqual(monitor.snapshot(12).state, "STALE")

    def test_receiver_clock_must_be_finite_and_monotonic(self):
        monitor = LinkMonitor()
        monitor.snapshot(2)
        for value in (1, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                monitor.snapshot(value)
        self.assertEqual(monitor.snapshot(3).state, "WAITING")

    def test_invalid_configuration(self):
        for value in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LinkMonitor(stale_after_s=value)
        for value in (0, 4097, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LinkMonitor(max_sessions=value)


class LateSampleLivenessTests(unittest.TestCase):
    def late(self, **kwargs):
        return LinkMonitor(stale_after_s=1.0, late_samples="liveness", **kwargs)

    def test_default_still_rejects_late_samples(self):
        monitor = LinkMonitor(stale_after_s=1.0)
        monitor.ingest(packet(sequence=5).to_json(), 0)
        self.assertFalse(monitor.ingest(packet(sequence=4).to_json(), 0.9))
        self.assertEqual(monitor.snapshot(1.0).state, "STALE")
        self.assertEqual((monitor.late_samples, monitor.late_accepted), ("reject", 0))

    def test_unseen_late_sample_refreshes_liveness_once(self):
        monitor = self.late()
        monitor.ingest(packet(sequence=5).to_json(), 0)
        self.assertTrue(monitor.ingest(packet(sequence=4).to_json(), 0.9))
        status = monitor.snapshot(1.5)
        self.assertEqual(status.state, "HEALTHY")
        self.assertEqual((status.accepted, status.rejected, status.last_sequence), (2, 0, 5))
        self.assertEqual(monitor.late_accepted, 1)
        for repeat in (4, 5):
            self.assertFalse(monitor.ingest(packet(sequence=repeat).to_json(), 1.6))
        self.assertEqual(monitor.last_rejection, "duplicate_or_out_of_order")
        self.assertEqual(monitor.snapshot(2.0).state, "STALE")

    def test_late_window_bounds_what_can_be_checked(self):
        monitor = self.late(late_window=10)
        monitor.ingest(packet(sequence=100).to_json(), 0)
        self.assertTrue(monitor.ingest(packet(sequence=91).to_json(), 0.1))
        self.assertFalse(monitor.ingest(packet(sequence=90).to_json(), 0.2))
        for sequence in range(101, 200):
            monitor.ingest(packet(sequence=sequence).to_json(), 0.3)
        self.assertLessEqual(len(monitor._recent), 20)
        for repeat in (195, 190):
            self.assertFalse(monitor.ingest(packet(sequence=repeat).to_json(), 0.4))

    def test_sessions_keep_their_rules(self):
        monitor = self.late()
        monitor.ingest(packet(sequence=5).to_json(), 0)
        monitor.ingest(packet(session_id="boot_2", sequence=0).to_json(), 0.1)
        self.assertFalse(monitor.ingest(packet(sequence=4).to_json(), 0.2))
        self.assertEqual(monitor.last_rejection, "retired_session")
        # The new session starts with an empty window: sequence 0 was seen.
        self.assertFalse(monitor.ingest(packet(session_id="boot_2", sequence=0).to_json(), 0.3))
        self.assertTrue(monitor.ingest(packet(session_id="boot_2", sequence=3).to_json(), 0.4))
        self.assertTrue(monitor.ingest(packet(session_id="boot_2", sequence=2).to_json(), 0.5))

    def test_rejects_invalid_configuration(self):
        for kwargs in ({"late_samples": "accept"}, {"late_window": 0},
                       {"late_window": 65537}, {"late_window": 2.0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LinkMonitor(**kwargs)
