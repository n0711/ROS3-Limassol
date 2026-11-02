#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H18 experimental ring window for late-sequence liveness.

Not used by ROS3 production code or ROS 2 nodes. This subclass exists only
to compare late-window semantics against the existing LinkMonitor.
"""

from ros3_limassol.monitor import LinkMonitor


class RingLinkMonitor(LinkMonitor):
    """Experimental fixed-size sequence ring, O(1) index work per accepted packet.

    All other behavior remains inherited from LinkMonitor. In particular,
    JSON validation, robot/session filtering and session tracking use the
    existing logic and its expected hash complexity assumptions.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Allocate only when liveness mode is active. This deliberately
        # trades O(W) up-front memory for constant-cost sequence bookkeeping.
        self._ring = (
            [None] * self.late_window if self.late_samples == "liveness" else []
        )
        self._ring_session = None
        self._ring_generation = 0

    def _is_unseen_late(self, sequence):
        if self.late_samples != "liveness":
            return False
        if self._last_sequence - sequence >= self.late_window:
            return False
        index = sequence % self.late_window
        return self._ring[index] != (self._ring_generation, sequence)

    def _remember(self, sequence):
        if self.late_samples != "liveness":
            return
        # This is called after the base implementation chooses an accepted
        # session. Incrementing the generation logically invalidates every
        # previous slot without an O(W) clear on restart.
        if self._ring_session != self._session:
            self._ring_session = self._session
            self._ring_generation += 1
        self._ring[sequence % self.late_window] = (
            self._ring_generation, sequence
        )

    def ring_storage_size(self):
        """Number of fixed slots (not a count of currently live sequences)."""
        return len(self._ring)
