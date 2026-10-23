# SPDX-License-Identifier: Apache-2.0
"""Synthetic USV telemetry for repeatable software experiments."""

import math
import uuid

from .telemetry import Telemetry, finite_number, validate_robot_id


class UsvSimulator:
    def __init__(self, robot_id="usv01", blackout_start_s=2.0,
                 blackout_duration_s=3.0, session_id=None):
        self.robot_id = validate_robot_id(robot_id)
        self.blackout_start_s = finite_number(blackout_start_s, "blackout_start_s")
        self.blackout_duration_s = finite_number(
            blackout_duration_s, "blackout_duration_s"
        )
        if self.blackout_start_s < 0 or self.blackout_duration_s < 0:
            raise ValueError("blackout times must be nonnegative")
        self.session_id = str(uuid.uuid4()) if session_id is None else session_id
        self.sequence = 0
        self._last_elapsed = None

    def sample(self, elapsed_s, timestamp_ns):
        elapsed_s = finite_number(elapsed_s, "elapsed_s")
        if elapsed_s < 0:
            raise ValueError("elapsed_s must be nonnegative")
        if self._last_elapsed is not None and elapsed_s < self._last_elapsed:
            raise ValueError("simulator time moved backwards")
        self._last_elapsed = elapsed_s
        # Count generated samples, including those dropped by the link model.
        sequence = self.sequence
        self.sequence += 1
        if (self.blackout_start_s <= elapsed_s <
                self.blackout_start_s + self.blackout_duration_s):
            return None
        angle = elapsed_s / 20.0
        return Telemetry(
            schema_version=1, robot_id=self.robot_id,
            session_id=self.session_id, sequence=sequence,
            timestamp_ns=timestamp_ns,
            latitude_deg=34.67 + 0.0001 * math.sin(angle),
            longitude_deg=33.04 + 0.0001 * math.cos(angle),
            heading_deg=(elapsed_s * 3.0) % 360,
            speed_m_s=0.6, battery_pct=max(0.0, 100 - elapsed_s * 0.01),
        )
