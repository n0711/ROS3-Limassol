# SPDX-License-Identifier: Apache-2.0
"""Bounded receiver-side association of ROS3 link status with sampled frames.

Both callback arrival observations use one observer process's monotonic clock.
No camera exposure timestamp, ROS header stamp, sender clock or transmission
delay is inferred. This data is not a synchronization or identity proof.
"""

import time
import uuid

from .llm_diagnostics import validate_status
from .telemetry import finite_number, validate_robot_id


class ReceiverObservationContext:
    """Retain at most one recent status; snapshot it when a frame arrives."""

    def __init__(self, robot_id="usv01", max_status_age_s=1.0, *,
                 clock=time.monotonic, session_id=None):
        self.robot_id = validate_robot_id(robot_id)
        age = finite_number(max_status_age_s, "max_status_age_s")
        if not 0 < age <= 30:
            raise ValueError("max_status_age_s must be in (0, 30]")
        if not callable(clock):
            raise ValueError("clock must be callable")
        if session_id is None:
            session_id = uuid.uuid4().hex
        if not isinstance(session_id, str) or len(session_id) != 32 or any(
                char not in "0123456789abcdef" for char in session_id):
            raise ValueError("invalid observer session id")
        self.max_status_age_s = age
        self.session_id = session_id
        self._clock = clock
        self._last_clock_s = None
        self._session_start_s = None
        self._status = None
        self._status_received_at_s = None
        self._sample_index = 0

    @property
    def has_status(self):
        return self._status is not None

    def _now(self, now_s):
        n = finite_number(self._clock() if now_s is None else now_s, "receiver_now_s")
        if n < 0 or (self._last_clock_s is not None and n < self._last_clock_s):
            raise ValueError("receiver monotonic clock is negative or moved backwards")
        self._last_clock_s = n
        if self._session_start_s is None:
            self._session_start_s = n
        return n

    def receive_status(self, raw, *, now_s=None):
        """Observe a delivered LinkStatus, not its original publication time."""
        status = validate_status(raw)
        if status["robot_id"] != self.robot_id:
            return False
        now = self._now(now_s)
        self._status = status
        self._status_received_at_s = now
        return True

    def sample_frame(self, *, now_s=None):
        """Capture status *at frame callback receipt*, before VLM inference.

        Missing/old status is represented as null, never extrapolated.
        """
        now = self._now(now_s)
        self._sample_index += 1
        age = (None if self._status_received_at_s is None
               else now - self._status_received_at_s)
        recent = age is not None and 0 <= age <= self.max_status_age_s
        status = None if not recent else {
            "state": self._status["state"],
            "age_s_at_status_callback": self._status["age_s"],
            "accepted": self._status["accepted"],
            "rejected": self._status["rejected"],
            "last_sequence": self._status["last_sequence"],
        }
        return {
            "association_version": 1,
            "observer_session_id": self.session_id,
            "sample_index": self._sample_index,
            "frame_callback_offset_s": now - self._session_start_s,
            "status_delivery_age_at_frame_s": age if recent else None,
            "status_at_frame_callback": status,
            "status_association": "recent_receiver_delivery" if recent else "unavailable",
            "clock_basis": "one_observer_process_monotonic_callback_arrivals",
            "camera_capture_time_verified": False,
            "sender_clock_alignment_verified": False,
            "same_physical_robot_verified": False,
            "vera_mot_track_alignment_verified": False,
        }
