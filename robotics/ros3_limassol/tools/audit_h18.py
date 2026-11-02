#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H18 reproducible, offline differential testing of receiver liveness.

A separate finite-state oracle checks LinkMonitor on seeded, multi-robot
interleavings. This exercises synthetic input; it proves neither the code
correct for all inputs nor any network/field performance property.
"""

import argparse
import hashlib
import json
import random

from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.telemetry import Telemetry

POLICIES = ("reject", "liveness")
STALE_AFTER_S = 1.0
MAX_SESSIONS = 4
LATE_WINDOW = 16
MAX_EVENT_BUDGET = 25000


class Reference:
    """Specification-style oracle using bounded sets, not LinkMonitor's heap.

    Not a performance comparison: the oracle deliberately scans its small
    sequence set and has a different complexity profile from production.
    """

    def __init__(self, robot_id, policy, max_sessions=MAX_SESSIONS,
                 window=LATE_WINDOW):
        self.robot_id = robot_id
        self.policy = policy
        self.max_sessions = max_sessions
        self.window = window
        self.session = None
        self.seen = set()
        self.highest = None
        self.recent = set()
        self.last_received = None
        self.accepted = 0
        self.rejected = 0
        self.last_rejection = None

    def reject(self, reason):
        self.rejected += 1
        self.last_rejection = reason
        return False

    def accept(self, robot_id, session, sequence, now_s, invalid=False):
        if invalid:
            return self.reject("invalid_payload")
        if robot_id != self.robot_id:
            return self.reject("unexpected_robot")

        if session == self.session:
            if sequence <= self.highest:
                inside_window = self.highest - sequence < self.window
                if (self.policy != "liveness" or not inside_window or
                        sequence in self.recent):
                    return self.reject("duplicate_or_out_of_order")
            else:
                self.highest = sequence
        else:
            if session in self.seen:
                return self.reject("retired_session")
            if len(self.seen) >= self.max_sessions:
                return self.reject("session_limit")
            self.seen.add(session)
            self.session = session
            self.highest = sequence
            self.recent.clear()

        if self.policy == "liveness":
            self.recent.add(sequence)
            # Independent reference: explicit filtering, no binary heap.
            self.recent = {
                item for item in self.recent
                if self.highest - item < self.window
            }
        self.last_received = now_s
        self.accepted += 1
        return True

    def snapshot(self, now_s):
        age = (None if self.last_received is None
               else now_s - self.last_received)
        state = ("WAITING" if age is None else
                 "STALE" if age >= STALE_AFTER_S else "HEALTHY")
        return {
            "state": state,
            "age_s": age,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "last_sequence": self.highest,
            "last_rejection": self.last_rejection,
        }


def make_packet(robot_id, session, sequence):
    # Zero-valued fields are schema placeholders, never real measurements.
    return Telemetry(
        schema_version=1, robot_id=robot_id, session_id=session,
        sequence=sequence, timestamp_ns=sequence,
        latitude_deg=0.0, longitude_deg=0.0, heading_deg=0.0,
        speed_m_s=0.0, battery_pct=0.0,
    ).to_json()


def simulate(robots=8, ticks=192, seed=17, policy="reject"):
    if (type(robots) is not int or not 1 <= robots <= 32 or
            type(ticks) is not int or not 8 <= ticks <= 384 or
            type(seed) is not int or not 0 <= seed <= 2147483647 or
            policy not in POLICIES or robots * ticks > MAX_EVENT_BUDGET):
        raise ValueError("invalid or oversized H18 scenario")
    rng = random.Random(seed)
    ids = [f"robot_{i:03d}" for i in range(robots)]
    monitors = [
        LinkMonitor(robot_id=identifier, stale_after_s=STALE_AFTER_S,
                    max_sessions=MAX_SESSIONS, late_samples=policy,
                    late_window=LATE_WINDOW)
        for identifier in ids
    ]
    references = [Reference(identifier, policy) for identifier in ids]
    digest = hashlib.sha256()
    injected = 0
    snapshots = 0
    stale_snapshots = 0
    wrong_robot = 0
    invalid_payload = 0

    for tick in range(ticks):
        now = tick * 0.25  # receiver monotonic clock, no wall-clock waiting
        for index, monitor in enumerate(monitors):
            reference = references[index]
            # Some receivers have no observation; still evaluate their clock.
            if rng.random() < 0.35:
                raw = None
            else:
                injected += 1
                event_robot = ids[index]
                if rng.random() < 0.08:
                    event_robot = (ids[(index + 1) % robots] if robots > 1
                                   else "intruder")
                    wrong_robot += 1
                session = f"boot_{tick // 48}"
                if rng.random() < 0.13:
                    session = f"boot_{rng.randrange(0, 8)}"
                sequence = tick * 2
                if rng.random() < 0.22:
                    sequence = max(0, sequence - rng.randrange(1, 36))
                if rng.random() < 0.07:
                    sequence = 0
                is_invalid = rng.random() < 0.04
                if is_invalid:
                    invalid_payload += 1
                    raw = "{}"
                else:
                    raw = make_packet(event_robot, session, sequence)

                expected_accepted = reference.accept(
                    event_robot, session, sequence, now, invalid=is_invalid)
                actual_accepted = monitor.ingest(raw, now)
                if expected_accepted != actual_accepted:
                    raise AssertionError(
                        f"acceptance mismatch: seed={seed} robot={index} "
                        f"tick={tick} policy={policy}")

            actual = monitor.snapshot(now)
            expected = reference.snapshot(now)
            for key, value in expected.items():
                if getattr(actual, key) != value:
                    raise AssertionError(
                        f"{key} mismatch: seed={seed} robot={index} "
                        f"tick={tick} policy={policy}")
            if (len(monitor._seen_sessions) > MAX_SESSIONS or
                    len(monitor._recent) > LATE_WINDOW or
                    len(monitor._recent_min_heap) > LATE_WINDOW or
                    monitor._recent != reference.recent):
                raise AssertionError("bounded-state or sequence-window mismatch")
            stale_snapshots += actual.state == "STALE"
            snapshots += 1
            # A digest is an exact trace fingerprint, not authentication.
            digest.update(
                f"{tick}|{index}|{raw}|{actual.to_json()}\n".encode("utf-8"))

    return {
        "robots": robots, "ticks": ticks, "seed": seed, "policy": policy,
        "injected_observations": injected,
        "accepted_total": sum(m.accepted for m in monitors),
        "rejected_total": sum(m.rejected for m in monitors),
        "wrong_robot_payloads": wrong_robot,
        "malformed_payloads": invalid_payload,
        "snapshots_checked": snapshots,
        "stale_snapshots": stale_snapshots,
        "trace_sha256": digest.hexdigest(),
        "session_ids_retained": sum(len(m._seen_sessions) for m in monitors),
        "late_entries_retained": sum(len(m._recent) for m in monitors),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robots", type=int, default=8)
    parser.add_argument("--ticks", type=int, default=192)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--modes", nargs="+", choices=POLICIES,
                        default=list(POLICIES))
    args = parser.parse_args(argv)
    if (not 1 <= args.robots <= 32 or not 8 <= args.ticks <= 384 or
            not 0 <= args.seed <= 2147483647 or
            len(set(args.modes)) != len(args.modes) or
            args.robots * args.ticks * len(args.modes) > MAX_EVENT_BUDGET):
        parser.error("invalid or oversized H18 workload")

    result = {
        "schema_version": 1,
        "source": "synthetic_offline",
        "experiment": "H18 seeded differential liveness and session oracle",
        "parameters": {
            "robots": args.robots, "ticks": args.ticks, "seed": args.seed,
            "modes": args.modes, "window": LATE_WINDOW,
            "max_sessions": MAX_SESSIONS, "stale_after_s": STALE_AFTER_S,
        },
        "results": [
            simulate(args.robots, args.ticks, args.seed, policy=mode)
            for mode in args.modes
        ],
        "claims": {
            "exhaustive_correctness_proven": False,
            "worst_case_time_proven": False,
            "physical_link_validated": False,
            "distributed_network_validated": False,
            "real_time_deadline_proven": False,
        },
    }
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
