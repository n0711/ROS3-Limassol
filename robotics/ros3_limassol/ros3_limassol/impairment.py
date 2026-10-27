# SPDX-License-Identifier: Apache-2.0
"""Seeded link-impairment experiments with declared timing ground truth.

Usage:
    python -m ros3_limassol.impairment scenario.json [--record-dir DIR]

A scenario declares one or more robots, each with its own link model: fixed
delay, uniform jitter (which reorders samples), independent loss, bursty
Gilbert-Elliott loss, duplication, scheduled outages and publisher restarts.
Everything runs on virtual time with per-robot seeded generators, so the same
scenario always yields the same report and recordings.

The scheduled outages are the ground truth. Each is matched against the STALE
episodes the standard monitor observes, giving detection and recovery latency,
missed outages and STALE episodes no outage explains. The monitor sees exactly
what replay of the written recordings would see. This characterises the
application rule under a synthetic link model; it is not a network measurement.
"""

import argparse
from dataclasses import dataclass
import io
import json
from pathlib import Path
import random

from .evidence import build_evidence
from .monitor import LATE_SAMPLE_POLICIES
from .recording import MAX_RECORDS, Observation
from .replay import run_replay
from .simulator import UsvSimulator
from .telemetry import finite_number, validate_robot_id

REPORT_VERSION = 1
MAX_ROBOTS = 16
MAX_DURATION_S = 3600.0
MAX_RATE_HZ = 100.0
MAX_EVENTS = 256

_TOP_KEYS = {"seed", "duration_s", "tick_s", "stale_after_s", "late_samples", "robots"}
_ROBOT_KEYS = {"robot_id", "rate_hz", "delay_s", "jitter_s", "loss", "burst_loss",
               "duplicate", "outages", "restarts"}
_BURST_KEYS = {"enter", "exit"}


def _keys(value, allowed, where, required=()):
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
    missing = set(required) - set(value)
    if missing:
        raise ValueError(f"{where}: missing keys {sorted(missing)}")


def _number(value, name, lower, upper, *, lower_open=False):
    value = finite_number(value, name)
    if value < lower or value > upper or (lower_open and value == lower):
        bracket = "(" if lower_open else "["
        raise ValueError(f"{name} must be in {bracket}{lower}, {upper}]")
    return value


def _probability(value, name):
    return _number(value, name, 0.0, 1.0)


@dataclass(frozen=True)
class LinkModel:
    robot_id: str
    rate_hz: float = 10.0
    delay_s: float = 0.0
    jitter_s: float = 0.0
    loss: float = 0.0
    burst_enter: float = 0.0
    burst_exit: float = 1.0
    duplicate: float = 0.0
    outages: tuple = ()
    restarts: tuple = ()


@dataclass(frozen=True)
class Scenario:
    seed: int
    duration_s: float
    tick_s: float
    stale_after_s: float
    robots: tuple
    late_samples: str = "reject"


def parse_scenario(data):
    """Validate a scenario mapping strictly; unknown keys are errors."""
    _keys(data, _TOP_KEYS, "scenario", required=("robots",))
    seed = data.get("seed", 0)
    if type(seed) is not int or not 0 <= seed < 2**63:
        raise ValueError("seed must be a nonnegative integer")
    duration = _number(data.get("duration_s", 30.0), "duration_s", 0, MAX_DURATION_S,
                       lower_open=True)
    tick = _number(data.get("tick_s", 0.1), "tick_s", 0, 60, lower_open=True)
    stale = _number(data.get("stale_after_s", 1.0), "stale_after_s", 0, 3600,
                    lower_open=True)
    robots = data["robots"]
    if not isinstance(robots, list) or not 1 <= len(robots) <= MAX_ROBOTS:
        raise ValueError(f"robots must be a list of 1-{MAX_ROBOTS} entries")
    models = []
    for index, raw in enumerate(robots):
        where = f"robots[{index}]"
        _keys(raw, _ROBOT_KEYS, where, required=("robot_id",))
        burst = raw.get("burst_loss", {"enter": 0.0, "exit": 1.0})
        _keys(burst, _BURST_KEYS, f"{where}.burst_loss", required=("enter", "exit"))
        model = LinkModel(
            robot_id=validate_robot_id(raw["robot_id"]),
            rate_hz=_number(raw.get("rate_hz", 10.0), f"{where}.rate_hz", 0,
                            MAX_RATE_HZ, lower_open=True),
            delay_s=_number(raw.get("delay_s", 0.0), f"{where}.delay_s", 0, 60),
            jitter_s=_number(raw.get("jitter_s", 0.0), f"{where}.jitter_s", 0, 60),
            loss=_probability(raw.get("loss", 0.0), f"{where}.loss"),
            burst_enter=_probability(burst["enter"], f"{where}.burst_loss.enter"),
            burst_exit=_number(burst["exit"], f"{where}.burst_loss.exit", 0, 1,
                               lower_open=True),
            duplicate=_probability(raw.get("duplicate", 0.0), f"{where}.duplicate"),
            outages=_intervals(raw.get("outages", []), f"{where}.outages", duration),
            restarts=_times(raw.get("restarts", []), f"{where}.restarts", duration),
        )
        if int(duration * model.rate_hz) + 1 > MAX_RECORDS // 4:
            raise ValueError(f"{where}: too many samples for one recording")
        models.append(model)
    if len({m.robot_id for m in models}) != len(models):
        raise ValueError("robot_id values must be unique")
    if int(duration / tick) + 1 > MAX_RECORDS // 2:
        raise ValueError("too many observation ticks for one recording")
    late = data.get("late_samples", "reject")
    if late not in LATE_SAMPLE_POLICIES:
        raise ValueError(f"late_samples must be one of {LATE_SAMPLE_POLICIES}")
    return Scenario(seed, duration, tick, stale, tuple(models), late)


def _intervals(value, where, duration):
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise ValueError(f"{where} must be a list of at most {MAX_EVENTS} [start, end]")
    result = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"{where} entries must be [start_s, end_s]")
        start = _number(item[0], f"{where} start", 0, duration)
        end = _number(item[1], f"{where} end", 0, duration)
        if end <= start:
            raise ValueError(f"{where} end must be after start")
        if result and start < result[-1][1]:
            raise ValueError(f"{where} must be sorted and non-overlapping")
        result.append((start, end))
    return tuple(result)


def _times(value, where, duration):
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        raise ValueError(f"{where} must be a list of at most {MAX_EVENTS} times")
    result = tuple(_number(t, where, 0, duration, lower_open=True) for t in value)
    if list(result) != sorted(set(result)):
        raise ValueError(f"{where} must be strictly increasing")
    return result


def _send_and_deliver(model, scenario):
    """Return (arrivals, counts). Arrivals are (time_s, order, payload)."""
    rng = random.Random(f"{scenario.seed}:{model.robot_id}")
    counts = {"generated": 0, "dropped_outage": 0, "dropped_loss": 0,
              "dropped_burst": 0, "duplicated": 0, "delivered_after_end": 0}
    arrivals = []
    restarts = list(model.restarts)
    session = 0
    sim = UsvSimulator(model.robot_id, blackout_duration_s=0.0,
                       session_id=f"{model.robot_id}_s0")
    bad_state = False
    period = 1.0 / model.rate_hz
    for index in range(int(scenario.duration_s * model.rate_hz) + 1):
        sent = index * period
        if sent > scenario.duration_s:
            break
        while restarts and restarts[0] <= sent:
            restarts.pop(0)
            session += 1
            sim = UsvSimulator(model.robot_id, blackout_duration_s=0.0,
                               session_id=f"{model.robot_id}_s{session}")
        payload = sim.sample(sent, int(round(sent * 1e9))).to_json()
        counts["generated"] += 1
        # Common random numbers: every sample draws the same values in the same
        # order whatever happens to it, so changing one parameter does not
        # reshuffle the others. The burst state advances on every sample.
        bad_state = (rng.random() >= model.burst_exit) if bad_state else (
            rng.random() < model.burst_enter)
        lost = rng.random() < model.loss
        copies = 2 if rng.random() < model.duplicate else 1
        delays = [model.delay_s + rng.uniform(0.0, model.jitter_s) for _ in range(2)]
        if any(start <= sent < end for start, end in model.outages):
            counts["dropped_outage"] += 1
            continue
        if bad_state:
            counts["dropped_burst"] += 1
            continue
        if lost:
            counts["dropped_loss"] += 1
            continue
        if copies == 2:
            counts["duplicated"] += 1
        for copy in range(copies):
            arrival = sent + delays[copy]
            if arrival > scenario.duration_s:
                counts["delivered_after_end"] += 1
                continue
            arrivals.append((arrival, len(arrivals), payload))
    arrivals.sort()
    return arrivals, counts


def _observations(arrivals, scenario):
    """Merge arrivals and periodic ticks in receiver-time order."""
    ticks = [i * scenario.tick_s for i in range(int(scenario.duration_s / scenario.tick_s) + 1)]
    merged = [(t, 1, i, None) for i, t in enumerate(ticks)]
    merged += [(t, 0, order, payload) for t, order, payload in arrivals]
    merged.sort(key=lambda item: item[:3])
    return [Observation(round(t, 9), payload) for t, _, _, payload in merged]


def _episodes(events):
    episodes = []
    for event in events:
        if event.get("event") == "summary":
            continue
        if event["state"] == "STALE":
            episodes.append([event["time_s"], None])
        elif event["state"] == "HEALTHY" and episodes and episodes[-1][1] is None:
            episodes[-1][1] = event["time_s"]
    return episodes


def _match(model, scenario, episodes):
    """Pair each declared outage with the first unused STALE episode it explains.

    An outage explains an episode starting at or after its start and no later
    than end + stale_after + delay + jitter + tick: the latest moment that
    outage could first be observed by this receiver.
    """
    slack = scenario.stale_after_s + model.delay_s + model.jitter_s + scenario.tick_s
    used = set()
    matched = []
    for start, end in model.outages:
        # The link may already be STALE (e.g. from a loss burst) when the
        # outage begins: that is neither a detection nor a miss.
        ongoing = next((i for i, (stale_at, healthy_at) in enumerate(episodes)
                        if stale_at < start and
                        (healthy_at is None or healthy_at > start)), None)
        hit = ongoing if ongoing is not None else next(
            (i for i, (stale_at, _) in enumerate(episodes)
             if i not in used and start <= stale_at <= end + slack), None)
        entry = {"outage_start_s": start, "outage_end_s": end,
                 "detected": hit is not None, "already_stale": ongoing is not None,
                 "stale_at_s": None, "detection_latency_s": None,
                 "healthy_at_s": None, "recovery_latency_s": None}
        if hit is not None:
            used.add(hit)
            stale_at, healthy_at = episodes[hit]
            entry.update(stale_at_s=stale_at,
                         detection_latency_s=(None if ongoing is not None
                                              else round(stale_at - start, 9)),
                         healthy_at_s=healthy_at,
                         recovery_latency_s=(None if healthy_at is None
                                             else round(healthy_at - end, 9)))
        matched.append(entry)
    unexplained = [{"stale_at_s": s, "healthy_at_s": h}
                   for i, (s, h) in enumerate(episodes) if i not in used]
    return matched, unexplained


def run_robot(model, scenario):
    """Return (report, observations) for one robot."""
    arrivals, counts = _send_and_deliver(model, scenario)
    observations = _observations(arrivals, scenario)
    text = "".join(o.to_json() + "\n" for o in observations)
    events = list(run_replay(io.StringIO(text), model.robot_id, scenario.stale_after_s,
                             scenario.late_samples))
    summary = events[-1]
    matched, unexplained = _match(model, scenario, _episodes(events))
    monitor_events = [e for e in events if e.get("event") != "summary"]
    rejections = build_evidence(io.BytesIO(text.encode("utf-8")), model.robot_id,
                                scenario.stale_after_s,
                                scenario.late_samples)["rejection_reasons"]
    detected = [m for m in matched if m["detected"]]
    return {
        "robot_id": model.robot_id,
        "link_model": {
            "rate_hz": model.rate_hz, "delay_s": model.delay_s,
            "jitter_s": model.jitter_s, "loss": model.loss,
            "burst_loss": {"enter": model.burst_enter, "exit": model.burst_exit},
            "duplicate": model.duplicate,
            "outages": [list(o) for o in model.outages],
            "restarts": list(model.restarts),
        },
        "link": {**counts, "arrivals": len(arrivals)},
        "monitor": {
            "accepted": summary["accepted"], "rejected": summary["rejected"],
            "rejection_reasons": rejections,
            "final_state": summary["state"],
            "state_changes": len(monitor_events) - 1,
        },
        "ground_truth": {
            "outages": matched,
            "detected_outages": len(detected),
            "missed_outages": len(matched) - len(detected),
            "already_stale_outages": sum(m["already_stale"] for m in matched),
            "max_detection_latency_s": max(
                (m["detection_latency_s"] for m in detected
                 if m["detection_latency_s"] is not None), default=None),
            "unexplained_stale_episodes": unexplained,
        },
    }, observations


def run_scenario(scenario, record_dir=None):
    """Run every robot; optionally write ``<robot_id>.jsonl`` (never overwrite)."""
    paths = {}
    if record_dir is not None:
        record_dir = Path(record_dir)
        for model in scenario.robots:
            path = record_dir / f"{model.robot_id}.jsonl"
            if path.exists():
                raise ValueError(f"{path} already exists; choose a new directory")
            paths[model.robot_id] = path
        record_dir.mkdir(parents=True, exist_ok=True)
    robots = []
    for model in scenario.robots:
        report, observations = run_robot(model, scenario)
        if model.robot_id in paths:
            with paths[model.robot_id].open("x", encoding="utf-8", newline="\n") as stream:
                for observation in observations:
                    stream.write(observation.to_json() + "\n")
            report["recording"] = paths[model.robot_id].name
        robots.append(report)
    return {
        "report_version": REPORT_VERSION,
        "seed": scenario.seed, "duration_s": scenario.duration_s,
        "tick_s": scenario.tick_s, "stale_after_s": scenario.stale_after_s,
        "late_samples": scenario.late_samples,
        "robots": robots,
        "interpretation": (
            "Synthetic link model on virtual time. Outages are declared ground "
            "truth; latencies are observed at receiver ticks. Not a measurement "
            "of a real network, DDS, radio or vehicle."
        ),
    }


def _reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenario", help="scenario JSON file")
    parser.add_argument("--record-dir", metavar="DIR",
                        help="write one replayable JSONL recording per robot")
    options = parser.parse_args(args)
    try:
        with open(options.scenario, encoding="utf-8") as stream:
            data = json.load(stream, parse_constant=_reject_constant)
        report = run_scenario(parse_scenario(data), options.record_dir)
        print(json.dumps(report, allow_nan=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
