# SPDX-License-Identifier: Apache-2.0
"""Compare relay-induced outages with the bridge's observed STALE/HEALTHY changes.

Validation tool for issue #28, not part of the installed package:

    python tools/compare_outages.py relay-log.jsonl sitl.jsonl \
        --robot-id usv01 --stale-after 1.0 [--bridge-output bridge.out] [--json]

Clock alignment: the bridge writes receiver-relative ``time_s`` and stamps
each mapped sample's ``timestamp_ns`` with the receiver wall clock at mapping
time. Their difference gives the recording's wall-clock origin; the spread of
that difference across samples is reported as the alignment uncertainty.
Transitions come from replaying the recording with the standard monitor.

For each relay window the arrival gap runs from the last datagram forwarded
before the drop to the first forwarded after it. A STALE change is expected
only when that gap reaches ``--stale-after``; on loopback it should appear at
``last forwarded + stale_after`` plus at most one bridge tick.
"""

import argparse
import io
import json
from pathlib import Path
import statistics
import sys

try:
    from ros3_limassol.recording import read_observations
except ImportError:  # running from a checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ros3_limassol.recording import read_observations
from ros3_limassol.replay import run_replay
from ros3_limassol.telemetry import Telemetry


def load_relay_log(lines):
    windows = {}
    first = None
    end = None
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"relay log line {number}: invalid JSON") from exc
        event = record.get("event")
        if event == "first_datagram":
            first = record["wall_ns"]
        elif event in ("drop_start", "drop_end", "first_forwarded_after"):
            windows.setdefault(record["window"], {})[event] = record
        elif event == "summary" and first is not None and record.get("elapsed_s") is not None:
            end = first + int(record["elapsed_s"] * 1e9)
    if first is None:
        raise ValueError("relay log has no first_datagram record")
    return first, end, [windows[i] for i in sorted(windows)]


def align_recording(text, robot_id):
    """Return (origin_wall_ns, spread_ns, sample_count) from accepted payloads."""
    offsets = []
    for observation in read_observations(io.StringIO(text)):
        if observation.payload is None:
            continue
        try:
            sample = Telemetry.from_json(observation.payload)
        except ValueError:
            continue
        if sample.robot_id == robot_id:
            offsets.append(sample.timestamp_ns - observation.time_s * 1e9)
    if not offsets:
        raise ValueError("recording has no valid samples to align with wall time")
    return statistics.median(offsets), max(offsets) - min(offsets), len(offsets)


def transitions(text, robot_id, stale_after_s):
    return [(e["time_s"], e["state"]) for e in
            run_replay(io.StringIO(text), robot_id, stale_after_s)
            if e.get("event") != "summary"]


def compare(relay_lines, recording_text, robot_id="usv01", stale_after_s=1.0,
            bridge_lines=None):
    relay_origin, relay_end, windows = load_relay_log(relay_lines)
    origin, spread, samples = align_recording(recording_text, robot_id)
    changes = transitions(recording_text, robot_id, stale_after_s)
    wall = lambda t: origin + t * 1e9  # noqa: E731
    to_s = lambda ns: None if ns is None else round(ns / 1e9, 6)  # noqa: E731
    used = set()
    rows = []
    for index, window in enumerate(windows):
        start = window.get("drop_start", {})
        end = window.get("drop_end", {})
        last = start.get("last_forwarded_wall_ns")
        resumed = window.get("first_forwarded_after", {}).get("wall_ns")
        row = {"window": index,
               "scheduled_s": [start.get("scheduled_s"), end.get("scheduled_s")],
               "dropped_datagrams": end.get("dropped"),
               "arrival_gap_s": None, "stale_expected": None,
               "stale_after_drop_s": None, "stale_minus_expected_s": None,
               "healthy_after_resume_s": None, "matched": False}
        if last is not None and resumed is not None:
            gap = (resumed - last) / 1e9
            row["arrival_gap_s"] = round(gap, 6)
            row["stale_expected"] = gap >= stale_after_s
            hit = next((i for i, (t, state) in enumerate(changes)
                        if i not in used and state == "STALE" and last <= wall(t) <= resumed), None)
            if hit is not None:
                used.add(hit)
                stale_ns = wall(changes[hit][0])
                row["matched"] = True
                row["stale_after_drop_s"] = to_s(stale_ns - start["scheduled_wall_ns"])
                row["stale_minus_expected_s"] = to_s(stale_ns - (last + stale_after_s * 1e9))
                healthy = next((t for t, state in changes[hit + 1:] if state == "HEALTHY"), None)
                if healthy is not None:
                    row["healthy_after_resume_s"] = to_s(wall(healthy) - resumed)
        rows.append(row)
    unmatched = [(t, wall(t)) for i, (t, state) in enumerate(changes)
                 if state == "STALE" and i not in used]
    # Once the relay stops forwarding, the bridge is expected to go STALE.
    after_end = [t for t, w in unmatched if relay_end is not None and w >= relay_end]
    unexplained = [{"time_s": t, "wall_offset_s": to_s(w - relay_origin)}
                   for t, w in unmatched if relay_end is None or w < relay_end]
    report = {
        "robot_id": robot_id, "stale_after_s": stale_after_s,
        "alignment": {"samples": samples, "spread_ms": round(spread / 1e6, 3)},
        "windows": rows,
        "unexplained_stale": unexplained,
        "stale_after_relay_stopped": len(after_end),
        "all_expected_detected": all(r["matched"] == bool(r["stale_expected"]) for r in rows),
        "replay_transitions": [[round(t, 6), s] for t, s in changes],
    }
    if bridge_lines is not None:
        live = [(json.loads(line)["time_s"], json.loads(line)["state"]) for line in bridge_lines
                if line.strip() and "event" not in json.loads(line)]
        same = [s for _, s in live] == [s for _, s in changes]
        report["replay_matches_live"] = {
            "same_state_sequence": same,
            "max_time_difference_s": (round(max(abs(a - b) for (a, _), (b, _) in
                                                zip(live, changes)), 6) if same and live else None),
        }
    return report


def markdown(report):
    lines = [
        f"Alignment: {report['alignment']['samples']} samples, "
        f"spread {report['alignment']['spread_ms']} ms; stale_after {report['stale_after_s']} s",
        "",
        "| Window | Scheduled (s) | Dropped | Arrival gap (s) | STALE expected | "
        "STALE after drop (s) | STALE − expected (s) | HEALTHY after resume (s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in report["windows"]:
        cells = [r["window"], "–".join(str(x) for x in r["scheduled_s"]), r["dropped_datagrams"],
                 r["arrival_gap_s"], r["stale_expected"], r["stale_after_drop_s"],
                 r["stale_minus_expected_s"], r["healthy_after_resume_s"]]
        lines.append("| " + " | ".join("—" if c is None else str(c) for c in cells) + " |")
    lines += ["", f"Unexplained STALE changes: {len(report['unexplained_stale'])} "
              f"(plus {report['stale_after_relay_stopped']} after the relay stopped)",
              f"All expected outages detected: {report['all_expected_detected']}"]
    if "replay_matches_live" in report:
        match = report["replay_matches_live"]
        lines.append(f"Replay matches live: {match['same_state_sequence']} "
                     f"(max time difference {match['max_time_difference_s']} s)")
    return "\n".join(lines)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("relay_log")
    parser.add_argument("recording")
    parser.add_argument("--robot-id", default="usv01")
    parser.add_argument("--stale-after", type=float, default=1.0)
    parser.add_argument("--bridge-output", help="the bridge's stdout (JSON Lines)")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(args)
    try:
        relay = Path(options.relay_log).read_text(encoding="utf-8").splitlines()
        recording = Path(options.recording).read_text(encoding="utf-8")
        bridge = (Path(options.bridge_output).read_text(encoding="utf-8").splitlines()
                  if options.bridge_output else None)
        report = compare(relay, recording, options.robot_id, options.stale_after, bridge)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2) if options.json else markdown(report))


if __name__ == "__main__":
    main()
