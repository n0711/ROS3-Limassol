# SPDX-License-Identifier: Apache-2.0
"""Observe arrival liveness with a receiver's monotonic clock."""

from dataclasses import asdict, dataclass
import json

from .telemetry import Telemetry, finite_number, validate_robot_id


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
    """

    def __init__(self, robot_id="usv01", stale_after_s=1.0, max_sessions=128):
        self.robot_id = validate_robot_id(robot_id)
        self.stale_after_s = finite_number(stale_after_s, "stale_after_s")
        if self.stale_after_s <= 0:
            raise ValueError("stale_after_s must be positive")
        if type(max_sessions) is not int or not 1 <= max_sessions <= 4096:
            raise ValueError("max_sessions must be an integer in [1, 4096]")
        self.max_sessions = max_sessions
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
                return self._reject("duplicate_or_out_of_order")
        else:
            if packet.session_id in self._seen_sessions:
                return self._reject("retired_session")
            if len(self._seen_sessions) >= self.max_sessions:
                return self._reject("session_limit")
            self._seen_sessions.add(packet.session_id)
            self._session = packet.session_id
        self._last_sequence = packet.sequence
        self._last_received = now_s
        self.accepted += 1
        return True

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
