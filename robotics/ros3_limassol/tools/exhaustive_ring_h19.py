#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H19 bounded exhaustive conformance of H18 experimental ring to LinkMonitor.

"Exhaustive" is ONLY over the declared finite input alphabet and depth.
It does not formally verify all possible session/sequence/timing inputs.
"""

import argparse
from datetime import datetime, timezone
from itertools import product
import json

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

from experimental_ring_h18 import RingLinkMonitor

MAX_TRANSITIONS = 200_000


def packet(robot, session, sequence):
    return Telemetry(
        schema_version=1, robot_id=robot, session_id=session,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


# Exactly ten possible receiver inputs at each step, including silence.
ALPHABET = (
    ("silence", None),
    ("invalid_json", "{"),
    ("wrong_robot", packet("other", "b0", 0)),
    ("boot0_seq0", packet("mega", "b0", 0)),
    ("boot0_seq1", packet("mega", "b0", 1)),
    ("boot0_seq3", packet("mega", "b0", 3)),
    ("boot0_seq10", packet("mega", "b0", 10)),
    ("boot1_seq0", packet("mega", "b1", 0)),
    ("boot1_seq1", packet("mega", "b1", 1)),
    ("boot2_seq0", packet("mega", "b2", 0)),
)


def explore(depth=4, windows=(1, 2, 4)):
    if type(depth) is not int or not 1 <= depth <= 4:
        raise ValueError("depth must be integer 1..4")
    if not windows or len(windows) > 8 or any(
        type(n) is not int or n < 1 or n > 64 for n in windows
    ) or any(a >= b for a, b in zip(windows, windows[1:])):
        raise ValueError("windows must be strictly increasing integers 1..64")
    traces_per_window = len(ALPHABET) ** depth
    work = traces_per_window * len(windows) * depth
    if work > MAX_TRANSITIONS:
        raise ValueError("exhaustive test exceeds 200000 state transitions")

    checked = 0
    observations = 0
    for window in windows:
        settings = {
            "robot_id": "mega",
            "late_samples": "liveness",
            "late_window": window,
            "stale_after_s": 0.75,
            "max_sessions": 2,
        }
        for events in product(range(len(ALPHABET)), repeat=depth):
            reference = LinkMonitor(**settings)
            candidate = RingLinkMonitor(**settings)
            for step, event_index in enumerate(events):
                label, raw = ALPHABET[event_index]
                now = step * 0.5
                if raw is not None:
                    expected_accepted = reference.ingest(raw, now)
                    actual_accepted = candidate.ingest(raw, now)
                    observations += 1
                    if expected_accepted != actual_accepted:
                        raise AssertionError(
                            f"ingestion mismatch window={window} trace={events}"
                            f" step={step} event={label}"
                        )
                if (reference.snapshot(now) != candidate.snapshot(now)
                        or reference.late_accepted != candidate.late_accepted):
                    raise AssertionError(
                        f"snapshot mismatch window={window} trace={events}"
                        f" step={step} event={label}"
                    )
            after = depth * 0.5
            if reference.snapshot(after) != candidate.snapshot(after):
                raise AssertionError(
                    f"final-tick mismatch window={window} trace={events}"
                )
            if candidate.ring_storage_size() != window:
                raise AssertionError("ring storage size differs from window")
            checked += 1

    return {
        "schema_version": 1,
        "source": "synthetic_exhaustive_bounded",
        "experiment": "H19 bounded exhaustive ring/reference equivalence",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "alphabet_labels": [label for label, _ in ALPHABET],
        "alphabet_size": len(ALPHABET),
        "depth": depth,
        "window_sizes": list(windows),
        "traces_checked": checked,
        "state_step_checks": work,
        "payload_ingestions_checked": observations,
        "mismatches": 0,
        "scope": (
            "all words of specified depth over ten named synthetic events, "
            "with fixed monotonic receiver ticks and max_sessions=2"
        ),
        "claims": {
            "formal_equivalence_proven_for_all_inputs": False,
            "production_monitor_changed": False,
            "physical_link_validated": False,
            "hard_realtime_guarantee": False,
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--windows", nargs="+", type=int, default=[1, 2, 4])
    options = parser.parse_args(argv)
    try:
        report = explore(options.depth, tuple(options.windows))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
