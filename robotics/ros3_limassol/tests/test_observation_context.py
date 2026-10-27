"""Tests for explicitly bounded, receiver-side camera/status association."""

import json
import unittest

from ros3_limassol.observation_context import ReceiverObservationContext


SESSION = "a" * 32


def status(robot="usv01", state="HEALTHY", accepted=5):
    return {
        "robot_id": robot,
        "state": state,
        "age_s": 0.1 if state != "WAITING" else None,
        "accepted": accepted,
        "rejected": 2,
        "last_sequence": 4,
        "last_rejection": None,
    }


class ObservationContextTests(unittest.TestCase):
    def test_frame_without_status_does_not_infer_link_state(self):
        context = ReceiverObservationContext(
            max_status_age_s=1.0, session_id=SESSION,
        )
        sampled = context.sample_frame(now_s=10.0)
        self.assertEqual(sampled["status_association"], "unavailable")
        self.assertIsNone(sampled["status_at_frame_callback"])
        self.assertIsNone(sampled["status_delivery_age_at_frame_s"])
        self.assertEqual(sampled["sample_index"], 1)
        self.assertEqual(sampled["frame_callback_offset_s"], 0.0)
        self.assertFalse(sampled["sender_clock_alignment_verified"])
        self.assertFalse(sampled["camera_capture_time_verified"])
        self.assertFalse(sampled["same_physical_robot_verified"])
        self.assertFalse(sampled["vera_mot_track_alignment_verified"])

    def test_recent_status_is_same_process_receipt_not_sensor_freshness(self):
        context = ReceiverObservationContext(
            robot_id="usv01", max_status_age_s=1.0, session_id=SESSION,
        )
        self.assertTrue(context.receive_status(json.dumps(status()), now_s=5.0))
        observed = context.sample_frame(now_s=5.4)
        self.assertEqual(observed["status_association"], "recent_receiver_delivery")
        self.assertAlmostEqual(observed["status_delivery_age_at_frame_s"], 0.4)
        self.assertEqual(observed["status_at_frame_callback"]["state"], "HEALTHY")
        self.assertEqual(observed["status_at_frame_callback"]["accepted"], 5)
        self.assertEqual(observed["status_at_frame_callback"]["age_s_at_status_callback"], 0.1)
        self.assertEqual(observed["observer_session_id"], SESSION)
        self.assertEqual(observed["clock_basis"],
                         "one_observer_process_monotonic_callback_arrivals")
        self.assertNotIn("latitude_deg", json.dumps(observed))
        self.assertEqual(observed["frame_callback_offset_s"], 0.4)

    def test_missing_or_old_status_is_never_promoted_to_current(self):
        context = ReceiverObservationContext(
            max_status_age_s=1.0, session_id=SESSION,
        )
        self.assertTrue(context.receive_status(status(), now_s=10.0))
        self.assertEqual(context.sample_frame(now_s=11.0)["status_association"],
                         "recent_receiver_delivery")
        later = context.sample_frame(now_s=11.0001)
        self.assertEqual(later["status_association"], "unavailable")
        self.assertIsNone(later["status_at_frame_callback"])
        self.assertIsNone(later["status_delivery_age_at_frame_s"])

    def test_frame_context_is_immutable_after_subsequent_ros_callbacks(self):
        context = ReceiverObservationContext(session_id=SESSION)
        context.receive_status(status(state="HEALTHY"), now_s=0.0)
        first = context.sample_frame(now_s=0.2)
        context.receive_status(status(state="STALE", accepted=6), now_s=0.3)
        second = context.sample_frame(now_s=0.4)
        self.assertEqual(first["status_at_frame_callback"]["state"], "HEALTHY")
        self.assertEqual(second["status_at_frame_callback"]["state"], "STALE")
        self.assertEqual([first["sample_index"], second["sample_index"]], [1, 2])

    def test_wrong_robot_status_never_associates(self):
        context = ReceiverObservationContext(robot_id="usv01", session_id=SESSION)
        self.assertFalse(context.receive_status(status(robot="usv02"), now_s=1.0))
        self.assertFalse(context.has_status)
        self.assertIsNone(context.sample_frame(now_s=1.1)["status_at_frame_callback"])
        self.assertTrue(context.receive_status(status(robot="usv01"), now_s=1.2))

    def test_strict_validation_of_status_age_and_clock(self):
        context = ReceiverObservationContext(max_status_age_s=1.0, session_id=SESSION)
        with self.assertRaises(ValueError):
            context.receive_status('{"hello":"world"}', now_s=1.0)
        context.receive_status(status(), now_s=3.0)
        with self.assertRaisesRegex(ValueError, "moved backwards"):
            context.sample_frame(now_s=2.0)
        with self.assertRaises(ValueError):
            context.sample_frame(now_s=float("nan"))
        with self.assertRaises(ValueError):
            context.receive_status(status(), now_s=-1)

    def test_configuration_bounds_and_status_size(self):
        for age in (0, -1, 31, float("inf"), True):
            with self.subTest(age=age), self.assertRaises(ValueError):
                ReceiverObservationContext(max_status_age_s=age)
        with self.assertRaises(ValueError):
            ReceiverObservationContext(session_id="bad")
        context = ReceiverObservationContext(session_id=SESSION)
        with self.assertRaises(ValueError):
            context.receive_status(json.dumps(status()) + " " * 4097, now_s=0.0)


if __name__ == "__main__":
    unittest.main()
