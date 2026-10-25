# SPDX-License-Identifier: Apache-2.0
"""Summarize a recorded receiver-observation trace without ROS or telemetry export.

Usage:
    python -m ros3_limassol.evidence run.jsonl --robot-id usv01 --stale-after 1.0

The output is an offline, observation-based summary; it is not a measurement
of packet loss, latency, sensor freshness or a physical communication link.
"""

import argparse
from collections import deque
import hashlib
import json
import sys

from .monitor import LinkMonitor
from .recording import read_observations

MAX_REPORTED_TRANSITIONS = 256
REPORT_VERSION = 1


class _HashedUtf8Lines:
    """Bounded binary-line reader with an exact recording-byte SHA-256 digest."""

    def __init__(self, binary_stream):
        self._stream = binary_stream
        self.digest = hashlib.sha256()

    def readline(self, limit):
        raw = self._stream.readline(limit)
        if not isinstance(raw, bytes):
            raise ValueError("evidence input must be a binary stream")
        self.digest.update(raw)
        return raw.decode("utf-8")


def build_evidence(binary_stream, robot_id="usv01", stale_after_s=1.0):
    """Return reproducible counts and observed state changes after full parsing.

    A failed parse raises ValueError and never returns a partial report.
    Memory stays bounded by the monitor's session history and the most recent
    MAX_REPORTED_TRANSITIONS changes, even for large valid recordings.
    """
    monitor = LinkMonitor(robot_id=robot_id, stale_after_s=stale_after_s)
    reader = _HashedUtf8Lines(binary_stream)
    previous = monitor.snapshot(0.0).state
    transitions = deque(maxlen=MAX_REPORTED_TRANSITIONS)
    transition_count = 0
    recovery_count = 0
    stale_count = 0
    first_time = None
    last_time = None
    longest_gap = 0.0
    first_accepted = None
    last_accepted = None
    observations = 0
    payload_observations = 0
    silence_ticks = 0
    rejection_reasons = {}

    for observation in read_observations(reader):
        observations += 1
        now = observation.time_s
        if first_time is None:
            first_time = now
        if last_time is not None:
            longest_gap = max(longest_gap, now - last_time)
        last_time = now

        if observation.payload is None:
            silence_ticks += 1
        else:
            payload_observations += 1
            accepted = monitor.ingest(observation.payload, now)
            if accepted:
                if first_accepted is None:
                    first_accepted = now
                last_accepted = now
            else:
                reason = monitor.last_rejection
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

        state = monitor.snapshot(now).state
        if state != previous:
            transition_count += 1
            transitions.append({"observed_at_s": now, "from": previous, "to": state})
            if state == "STALE":
                stale_count += 1
            if previous == "STALE" and state == "HEALTHY":
                recovery_count += 1
            previous = state

    end_s = 0.0 if last_time is None else last_time
    final = monitor.snapshot(end_s)
    return {
        "report_version": REPORT_VERSION,
        "recording_parsed_to_eof": True,
        "recording_sha256": reader.digest.hexdigest(),
        "robot_id": monitor.robot_id,
        "stale_after_s": monitor.stale_after_s,
        "observation_count": observations,
        "payload_observation_count": payload_observations,
        "silence_tick_count": silence_ticks,
        "first_observation_s": first_time,
        "last_observation_s": last_time,
        "max_between_observation_gap_s": longest_gap if observations > 1 else None,
        "accepted": final.accepted,
        "rejected": final.rejected,
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "first_accepted_arrival_s": first_accepted,
        "last_accepted_arrival_s": last_accepted,
        "final_state": final.state,
        "final_age_s": final.age_s,
        "last_sequence": final.last_sequence,
        "observed_state_change_count": transition_count,
        "observed_stale_change_count": stale_count,
        "observed_stale_to_healthy_recoveries": recovery_count,
        "recent_state_changes": list(transitions),
        "state_changes_truncated": transition_count > len(transitions),
        "interpretation": (
            "Receiver-arrival observations only; transitions are observed at "
            "recorded ticks, not inferred between ticks. No network delivery, "
            "one-way delay, capture freshness or vehicle-health claim."
        ),
    }


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", help="existing version-1 JSONL recording")
    parser.add_argument("--robot-id", default="usv01")
    parser.add_argument("--stale-after", type=float, default=1.0)
    options = parser.parse_args(args)
    try:
        with open(options.recording, "rb") as stream:
            result = build_evidence(stream, options.robot_id, options.stale_after)
        # Print only after EOF validation so malformed files yield no partial JSON.
        print(json.dumps(result, allow_nan=False, sort_keys=True, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
