# SPDX-License-Identifier: Apache-2.0
"""Replay receiver observations without ROS, a robot, or wall-clock waiting."""

import argparse
from dataclasses import asdict
import json

from .monitor import LinkMonitor
from .recording import read_observations


def run_replay(stream, robot_id="usv01", stale_after_s=1.0):
    """Yield transitions and a final snapshot on the recorded receiver clock."""
    monitor = LinkMonitor(robot_id=robot_id, stale_after_s=stale_after_s)
    elapsed = 0.0
    status = monitor.snapshot(elapsed)
    previous = status.state
    yield {"time_s": elapsed, **asdict(status)}
    for observation in read_observations(stream):
        elapsed = observation.time_s
        if observation.payload is not None:
            monitor.ingest(observation.payload, elapsed)
        status = monitor.snapshot(elapsed)
        if status.state != previous:
            previous = status.state
            yield {"time_s": elapsed, **asdict(status)}
    yield {"time_s": elapsed, "event": "summary", **asdict(status)}


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", help="version-1 receiver observation JSONL file")
    parser.add_argument("--robot-id", default="usv01")
    parser.add_argument("--stale-after", type=float, default=1.0)
    parser.add_argument("--json", action="store_true", help="emit JSON Lines")
    options = parser.parse_args(args)
    try:
        # Decode one bounded line at a time. TextIOWrapper may read ahead and
        # report invalid bytes from a later line while reading the first line.
        with open(options.recording, "rb") as raw_stream:
            stream = _Utf8Lines(raw_stream)
            for event in run_replay(stream, options.robot_id, options.stale_after):
                if options.json:
                    print(json.dumps(event, allow_nan=False, separators=(",", ":")))
                elif event.get("event") == "summary":
                    print(f"Accepted: {event['accepted']}; rejected: {event['rejected']}")
                else:
                    print(f"t={event['time_s']:4.1f}s  {event['state']}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


class _Utf8Lines:
    """Decode bounded binary lines without reading ahead into later records."""

    def __init__(self, stream):
        self.stream = stream

    def readline(self, limit):
        return self.stream.readline(limit).decode("utf-8")


if __name__ == "__main__":
    main()
