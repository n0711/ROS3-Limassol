# SPDX-License-Identifier: Apache-2.0
"""Compare a live impairment run with the virtual model's prediction.

Validation tool for issue #33, not part of the installed package:

    python tools/compare_impairment.py scenario.json relay-log.jsonl bridge.jsonl \
        [--robot-id usv01] [--json]

The live side is the bridge recording from a run through
``tools/udp_impairment_relay.py``. It is replayed with the scenario's
``stale_after_s`` and shifted onto scenario time, where t = 0 is the relay's
first impaired position sample. The recording's wall-clock origin comes from
its samples' receive timestamps (see ``compare_outages.align_recording``).
Events before t = 0 or after ``duration_s`` are ignored. The live events are
then scored with ``ros3_limassol.impairment.match_outages``, the rule the
virtual report uses.

The virtual side is ``run_robot`` on the same scenario, seed and robot. The
scenario's ``rate_hz`` should be the live position rate.

Fate agreement checks the alignment itself. Sample k drew the same fate in
both runs, so their outcomes (outage, burst, loss, forwarded) can differ only
where live timing moved a sample across an outage boundary.
"""

import argparse
import io
import json
from pathlib import Path
import statistics
import sys

TOOLS = Path(__file__).resolve().parent
try:
    from ros3_limassol.impairment import (link_fates, match_outages, parse_scenario,
                                          run_robot)
except ImportError:  # running from a checkout without installation
    sys.path.insert(0, str(TOOLS.parent))
    from ros3_limassol.impairment import (link_fates, match_outages, parse_scenario,
                                          run_robot)
from ros3_limassol.replay import run_replay

sys.path.insert(0, str(TOOLS))
from compare_outages import align_recording  # noqa: E402
from udp_impairment_relay import select_model  # noqa: E402


def load_relay_log(lines):
    log = {"t0_wall_ns": None, "samples": [], "summary": None}
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"relay log line {number}: invalid JSON") from exc
        event = record.get("event")
        if event == "t0":
            log["t0_wall_ns"] = record["wall_ns"]
        elif event == "sample":
            log["samples"].append(record)
        elif event == "summary":
            log["summary"] = record
    if log["t0_wall_ns"] is None:
        raise ValueError("relay log has no t0 record; the run never started impairing")
    return log


def live_events(recording_text, robot_id, stale_after_s, t0_wall_ns, duration_s):
    """Replay events on scenario time, clipped to [0, duration_s], plus the state at t = 0."""
    origin_ns, spread_ns, aligned = align_recording(recording_text, robot_id)
    shift = (t0_wall_ns - origin_ns) / 1e9
    events = []
    state_at_t0 = "WAITING"
    for event in run_replay(io.StringIO(recording_text), robot_id, stale_after_s):
        if event.get("event") == "summary":
            continue
        t = event["time_s"] - shift
        if t < 0:
            state_at_t0 = event["state"]
        elif t <= duration_s:
            events.append({**event, "time_s": round(t, 9)})
    return events, state_at_t0, {"samples": aligned, "spread_ms": round(spread_ns / 1e6, 3)}


def virtual_outcomes(model, scenario, count):
    """The outcome the virtual model gives samples 0..count-1."""
    period = 1.0 / model.rate_hz
    fates = link_fates(model, scenario.seed)
    outcomes = []
    for k in range(count):
        fate, sent = next(fates), k * period
        if any(start <= sent < end for start, end in model.outages):
            outcomes.append("outage")
        elif fate.burst:
            outcomes.append("burst")
        elif fate.lost:
            outcomes.append("loss")
        else:
            outcomes.append("forwarded")
    return outcomes


def _side(matched, unexplained, duration_s):
    detected = [m for m in matched if m["detected"]]
    latencies = [m["detection_latency_s"] for m in detected
                 if m["detection_latency_s"] is not None]
    recoveries = [m["recovery_latency_s"] for m in detected
                  if m["recovery_latency_s"] is not None]
    return {
        "outages": [{k: m[k] for k in ("outage_start_s", "outage_end_s", "detected",
                                       "already_stale", "detection_latency_s",
                                       "recovery_latency_s")} for m in matched],
        "detected": len(detected),
        "already_stale": sum(m["already_stale"] for m in matched),
        "missed": len(matched) - len(detected),
        "mean_detection_latency_s": round(statistics.mean(latencies), 4) if latencies else None,
        "max_detection_latency_s": round(max(latencies), 4) if latencies else None,
        "mean_recovery_latency_s": round(statistics.mean(recoveries), 4) if recoveries else None,
        "unexplained_stale": len(unexplained),
        "unexplained_stale_per_hour": round(len(unexplained) * 3600 / duration_s, 1),
    }


def compare(scenario, relay_lines, recording_text, robot_id=None):
    model = select_model(scenario, robot_id)
    relay = load_relay_log(relay_lines)
    events, state_at_t0, alignment = live_events(
        recording_text, model.robot_id, scenario.stale_after_s, relay["t0_wall_ns"],
        scenario.duration_s)
    live_matched, live_unexplained = match_outages(model, scenario, events)
    virtual, _ = run_robot(model, scenario)
    truth = virtual["ground_truth"]
    live_outcomes = [s["outcome"] for s in relay["samples"]]
    expected = virtual_outcomes(model, scenario, len(live_outcomes))
    differ = [k for k, (a, b) in enumerate(zip(live_outcomes, expected)) if a != b]
    gaps = [b["rel_s"] - a["rel_s"] for a, b in zip(relay["samples"], relay["samples"][1:])]
    return {
        "robot_id": model.robot_id, "seed": scenario.seed,
        "duration_s": scenario.duration_s, "stale_after_s": scenario.stale_after_s,
        "tick_s": scenario.tick_s, "rate_hz": model.rate_hz,
        "alignment": alignment, "live_state_at_t0": state_at_t0,
        "position_interval_s": {
            "median": round(statistics.median(gaps), 4),
            "max": round(max(gaps), 4)} if gaps else None,
        "fate_agreement": {"samples": len(live_outcomes), "differ": len(differ),
                           "differing_samples": differ[:20]},
        "live": _side(live_matched, live_unexplained, scenario.duration_s),
        "virtual": _side(truth["outages"], truth["unexplained_stale_episodes"],
                         scenario.duration_s),
        "virtual_monitor": virtual["monitor"],
        "relay": relay["summary"],
    }


def markdown(report):
    live, virtual = report["live"], report["virtual"]
    lines = [
        f"Robot {report['robot_id']}, seed {report['seed']}, {report['duration_s']:g} s, "
        f"stale_after {report['stale_after_s']:g} s, tick {report['tick_s']:g} s; "
        f"live state at t=0: {report['live_state_at_t0']}",
        f"Fate agreement: {report['fate_agreement']['samples'] - report['fate_agreement']['differ']}"
        f"/{report['fate_agreement']['samples']} samples; alignment spread "
        f"{report['alignment']['spread_ms']} ms",
        "",
        "| Outage (s) | Live detection (s) | Virtual detection (s) | Live recovery (s) | Virtual recovery (s) |",
        "| --- | --- | --- | --- | --- |",
    ]

    def cell(m, key):
        if not m["detected"]:
            return "missed"
        if m[key] is None:
            return "already STALE" if m["already_stale"] else "—"
        return f"{m[key]:.3f}"

    for a, b in zip(live["outages"], virtual["outages"]):
        lines.append(f"| {a['outage_start_s']:g}–{a['outage_end_s']:g} | "
                     f"{cell(a, 'detection_latency_s')} | {cell(b, 'detection_latency_s')} | "
                     f"{cell(a, 'recovery_latency_s')} | {cell(b, 'recovery_latency_s')} |")
    lines += ["", f"Unexplained STALE: live {live['unexplained_stale']}, "
                  f"virtual {virtual['unexplained_stale']}"]
    return "\n".join(lines)


def _reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scenario")
    parser.add_argument("relay_log")
    parser.add_argument("recording")
    parser.add_argument("--robot-id")
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(args)
    try:
        with open(options.scenario, encoding="utf-8") as stream:
            scenario = parse_scenario(json.load(stream, parse_constant=_reject_constant))
        relay = Path(options.relay_log).read_text(encoding="utf-8").splitlines()
        recording = Path(options.recording).read_text(encoding="utf-8")
        report = compare(scenario, relay, recording, options.robot_id)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2) if options.json else markdown(report))


if __name__ == "__main__":
    main()
