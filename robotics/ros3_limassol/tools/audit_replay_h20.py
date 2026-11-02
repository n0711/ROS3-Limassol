#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H20 offline multi-robot observation recording/replay equivalence audit.

All events are synthetic; this does not measure physical hardware, ROS 2 DDS,
MAVLink, fleet throughput, field behavior, or worst-case response latency.
"""

import argparse
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import random

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.recording import Observation
from ros3_limassol.replay import run_replay
from ros3_limassol.telemetry import Telemetry

POLICIES = ("reject", "liveness")
STALE_AFTER_S = 1.0
MAX_ROBOTS = 16
MAX_TICKS = 256
MAX_EVENTS = 8192


def make_packet(robot_id, session, sequence):
    # Placeholder fields satisfy telemetry v1; no physical sensor readings.
    return Telemetry(
        schema_version=1, robot_id=robot_id, session_id=session,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


def check_replay(trace, expected, robot_id, policy):
    """Compare every transition and final summary, not merely final state."""
    obtained = list(run_replay(
        io.StringIO(trace), robot_id=robot_id,
        stale_after_s=STALE_AFTER_S, late_samples=policy,
    ))
    if obtained != expected:
        raise AssertionError(
            f"record/replay divergence for {robot_id} under {policy}")
    return obtained


def one_robot(index, robots, ticks, seed, policy):
    """Return verified recording and compact summary for one receiver."""
    robot_id = f"robot_{index:03d}"
    rng = random.Random(seed * 257 + index)
    monitor = LinkMonitor(robot_id=robot_id,
                          stale_after_s=STALE_AFTER_S,
                          late_samples=policy)
    previous = "WAITING"
    initial = monitor.snapshot(0.0)
    expected = [{"time_s": 0.0, **asdict(initial)}]
    recording = io.StringIO()
    silent = 0
    malformed = 0
    unexpected = 0
    for tick in range(ticks):
        now = tick * 0.25
        # A deterministic six-tick gap crosses the 1.0 s stale threshold.
        if 8 <= tick % 24 <= 13:
            raw = None
            silent += 1
        else:
            source_id = robot_id
            if rng.random() < 0.10:
                source_id = (f"robot_{(index + 1) % robots:03d}"
                             if robots > 1 else "intruder")
                unexpected += 1
            session = f"boot_{tick // 24}"
            if rng.random() < 0.10:
                session = "boot_0"  # sometimes revisit a retired session
            sequence = tick
            if rng.random() < 0.20:
                sequence = max(0, tick - rng.randrange(1, 20))
            if rng.random() < 0.04:
                raw = "{}"
                malformed += 1
            else:
                raw = make_packet(source_id, session, sequence)

        recording.write(Observation(now, raw).to_json() + "\n")
        if raw is not None:
            monitor.ingest(raw, now)
        snapshot = monitor.snapshot(now)
        if snapshot.state != previous:
            previous = snapshot.state
            expected.append({"time_s": now, **asdict(snapshot)})
    expected.append({"time_s": now, "event": "summary", **asdict(snapshot)})
    trace = recording.getvalue()
    check_replay(trace, expected, robot_id, policy)
    observations = trace.count("\n")
    if observations != ticks:
        raise AssertionError("incomplete synthetic recording")
    summary = {
        "robot_id": robot_id,
        "policy": policy,
        "observations": observations,
        "silence_ticks": silent,
        "malformed_payloads": malformed,
        "unexpected_identity_attempts": unexpected,
        "accepted": snapshot.accepted,
        "rejected": snapshot.rejected,
        "final_state": snapshot.state,
        "observed_transitions": [
            {"time_s": event["time_s"], "state": event["state"]}
            for event in expected[:-1]
        ],
        "replay_exact_match": True,
        "recording_sha256": hashlib.sha256(trace.encode("utf-8")).hexdigest(),
        "recording_bytes": len(trace.encode("utf-8")),
    }
    return summary, trace


def audit(robots=4, ticks=96, seed=17, policies=POLICIES):
    if (type(robots) is not int or not 1 <= robots <= MAX_ROBOTS or
            type(ticks) is not int or not 16 <= ticks <= MAX_TICKS or
            type(seed) is not int or not 0 <= seed <= 2147483647 or
            not policies or len(set(policies)) != len(policies) or
            any(policy not in POLICIES for policy in policies) or
            robots * ticks * len(policies) > MAX_EVENTS):
        raise ValueError("invalid or excessive H20 synthetic replay workload")

    summaries = []
    traces = {}
    for policy in policies:
        for index in range(robots):
            result, content = one_robot(index, robots, ticks, seed, policy)
            name = result["robot_id"] + "_" + policy + ".jsonl"
            summaries.append(result)
            traces[name] = content
    return {
        "schema_version": 1,
        "source": "synthetic_offline",
        "experiment": "H20 multi-robot recording replay exact equivalence",
        "parameters": {
            "robots": robots, "ticks_per_robot": ticks,
            "seed": seed, "policies": list(policies),
            "stale_after_s": STALE_AFTER_S,
        },
        "results": summaries,
        "claims": {
            "physical_link_validated": False,
            "distributed_network_validated": False,
            "exhaustive_correctness_proven": False,
            "hard_realtime_guarantee": False,
        },
    }, traces


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robots", type=int, default=4)
    parser.add_argument("--ticks", type=int, default=96)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--policies", choices=POLICIES, nargs="+",
                        default=list(POLICIES))
    parser.add_argument("--output-dir", type=Path,
                        help="create a new directory of synthetic JSONL files")
    options = parser.parse_args(argv)
    try:
        report, traces = audit(
            robots=options.robots, ticks=options.ticks,
            seed=options.seed, policies=options.policies,
        )
        if options.output_dir is not None:
            # Do not overwrite an existing evidence directory or its contents.
            options.output_dir.mkdir(parents=False, exist_ok=False)
            for name, content in traces.items():
                with (options.output_dir / name).open(
                        "x", encoding="utf-8", newline="\n") as stream:
                    stream.write(content)
            report["recordings_directory"] = str(options.output_dir)
    except (OSError, ValueError, AssertionError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
