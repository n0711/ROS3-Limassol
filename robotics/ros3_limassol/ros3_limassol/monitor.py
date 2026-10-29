# SPDX-License-Identifier: Apache-2.0
"""Observe arrival liveness with a receiver's monotonic clock."""

import json
from dataclasses import asdict, dataclass
from heapq import heappop, heappush

from .telemetry import Telemetry, finite_number, validate_robot_id

LATE_SAMPLE_POLICIES = ("reject", "liveness")


@dataclass(frozen=True)
class LinkStatus:
    robot_id: str
    state: str
    age_s: float | None
    accepted: int
    rejected: int
    last_sequence: int | None
    last_rejection: str | None

    def to_json(self):
        return json.dumps(asdict(self), allow_nan=False, separators=(",", ":"))


class LinkMonitor:
    """One expected robot, one active publisher session, bounded session history.

    `now_s` must come from the same monotonic clock for every call. Sender
    timestamps are recording metadata; they do not drive liveness decisions.

    ``late_samples`` decides what happens to a sample of the current session
    whose sequence is not above the highest seen so far:

    - ``"reject"`` (default): rejected as ``duplicate_or_out_of_order``.
    - ``"liveness"``: if its sequence is within ``late_window`` of the highest
      and has not been seen before, it is accepted and refreshes arrival
      recency (it did arrive), counted in ``accepted`` and ``late_accepted``.
      ``last_sequence`` stays the highest. Repeats, and samples too far
      behind to check for repeats, are still rejected.
    """

    def __init__(self, robot_id="usv01", stale_after_s=1.0, max_sessions=128,
                 late_samples="reject", late_window=256):
        self.robot_id = validate_robot_id(robot_id)
        self.stale_after_s = finite_number(stale_after_s, "stale_after_s")
        if self.stale_after_s <= 0:
            raise ValueError("stale_after_s must be positive")
        if type(max_sessions) is not int or not 1 <= max_sessions <= 4096:
            raise ValueError("max_sessions must be an integer in [1, 4096]")
        self.max_sessions = max_sessions
        if late_samples not in LATE_SAMPLE_POLICIES:
            raise ValueError(f"late_samples must be one of {LATE_SAMPLE_POLICIES}")
        if type(late_window) is not int or not 1 <= late_window <= 65536:
            raise ValueError("late_window must be an integer in [1, 65536]")
        self.late_samples = late_samples
        self.late_window = late_window
        self._recent = set()  # sequences in the active late-sample window
        self._recent_min_heap = []  # expire lowest sequences in O(log window)
        self.late_accepted = 0
        self._clock = None
        self._last_received = None
        self._session = None
        self._seen_sessions = set()
        self._last_sequence = None
        self.accepted = 0
        self.rejected = 0
        self.last_rejection = None

    def _advance(self, now_s):
        now_s = finite_number(now_s, "now_s")
        if self._clock is not None and now_s < self._clock:
            raise ValueError("receiver monotonic clock moved backwards")
        self._clock = now_s
        return now_s

    def _reject(self, reason):
        self.rejected += 1
        self.last_rejection = reason
        return False

    def ingest(self, raw, now_s):
        now_s = self._advance(now_s)
        try:
            packet = Telemetry.from_json(raw)
        except ValueError:
            return self._reject("invalid_payload")
        if packet.robot_id != self.robot_id:
            return self._reject("unexpected_robot")
        if packet.session_id == self._session:
            if packet.sequence <= self._last_sequence:
                if self._is_unseen_late(packet.sequence):
                    self._remember(packet.sequence)
                    self._last_received = now_s
                    self.accepted += 1
                    self.late_accepted += 1
                    return True
                return self._reject("duplicate_or_out_of_order")
        else:
            if packet.session_id in self._seen_sessions:
                return self._reject("retired_session")
            if len(self._seen_sessions) >= self.max_sessions:
                return self._reject("session_limit")
            self._seen_sessions.add(packet.session_id)
            self._session = packet.session_id
            self._recent.clear()
            self._recent_min_heap.clear()
        self._last_sequence = packet.sequence
        self._remember(packet.sequence)
        self._last_received = now_s
        self.accepted += 1
        return True

    def _is_unseen_late(self, sequence):
        return (self.late_samples == "liveness"
                and self._last_sequence - sequence < self.late_window
                and sequence not in self._recent)

    def _remember(self, sequence):
        if self.late_samples != "liveness":
            return
        # _remember only sees newly accepted sequences, so heap entries are unique.
        self._recent.add(sequence)
        heappush(self._recent_min_heap, sequence)
        floor = self._last_sequence - self.late_window
        while self._recent_min_heap and self._recent_min_heap[0] <= floor:
            self._recent.remove(heappop(self._recent_min_heap))

    def snapshot(self, now_s):
        now_s = self._advance(now_s)
        age = None if self._last_received is None else now_s - self._last_received
        state = "WAITING" if age is None else (
            "STALE" if age >= self.stale_after_s else "HEALTHY"
        )
        return LinkStatus(
            robot_id=self.robot_id, state=state, age_s=age,
            accepted=self.accepted, rejected=self.rejected,
            last_sequence=self._last_sequence,
            last_rejection=self.last_rejection,
        )
