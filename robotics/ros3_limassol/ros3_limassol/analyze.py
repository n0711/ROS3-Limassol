# SPDX-License-Identifier: Apache-2.0
"""Summarize recorded receiver observations without retaining the full trace."""

import argparse
import json

from .monitor import LinkMonitor
from .recording import Utf8Lines, read_observations


def analyze_recording(stream, robot_id="usv01", stale_after_s=1.0):
    """Measure state durations by holding each observed state to the next tick.

    No state evaluations are invented between recorded observations. Durations
    cover only the first through last recorded times, excluding any unobserved
    prefix or suffix. They are observations, not physical link availability.
    """
    monitor = LinkMonitor(robot_id=robot_id, stale_after_s=stale_after_s)
    durations = {state: 0.0 for state in ("WAITING", "HEALTHY", "STALE")}
    first = previous = None
    state = "WAITING"
    records = ticks = stale_entries = recoveries = 0
    max_gap = 0.0
    for observation in read_observations(stream):
        now = observation.time_s
        if first is None:
            first = now
        if previous is not None:
            gap = now - previous
            durations[state] += gap
            max_gap = max(max_gap, gap)
        if observation.payload is None:
            ticks += 1
        else:
            monitor.ingest(observation.payload, now)
        observed = monitor.snapshot(now).state
        if observed == "STALE" and state != "STALE":
            stale_entries += 1
        if observed == "HEALTHY" and state == "STALE":
            recoveries += 1
        state, previous = observed, now
        records += 1
    return {
        "report_version": 1,
        "robot_id": robot_id,
        "stale_after_s": monitor.stale_after_s,
        "observations": records,
        "silence_ticks": ticks,
        "payloads": records - ticks,
        "accepted": monitor.accepted,
        "rejected": monitor.rejected,
        "first_time_s": first,
        "last_time_s": previous,
        "observed_span_s": 0.0 if first is None else previous - first,
        "max_observation_gap_s": max_gap,
        "state_hold_duration_s": durations,
        "stale_entries": stale_entries,
        "recoveries": recoveries,
        "final_state": state,
        "final_stale_unresolved": state == "STALE",
    }


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", help="receiver observation JSONL file")
    parser.add_argument("--robot-id", default="usv01")
    parser.add_argument("--stale-after", type=float, default=1.0)
    options = parser.parse_args(args)
    try:
        with open(options.recording, "rb") as stream:
            result = analyze_recording(Utf8Lines(stream), options.robot_id,
                                       options.stale_after)
        # Print only after the entire input passes validation.
        print(json.dumps(result, allow_nan=False, sort_keys=True))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
