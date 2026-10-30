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
scenario's ``rate_hz`` should be the live position rate. The prediction is
reported twice: under the scenario's ``late_samples`` policy, and under
``"liveness"``. The second is the live path's analogue, because the bridge
numbers samples in arrival order and every arrival counts. Duplicates are the
exception: the bridge accepts both copies.

Fate agreement checks the alignment itself. Sample k drew the same fate in
both runs, so their outcomes (outage, burst, loss, forwarded) can differ only
where live timing moved a sample across an outage boundary.
"""

import argparse
import dataclasses
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
from ros3_limassol.recording import Observation
from ros3_limassol.replay import run_replay
from ros3_limassol.simulator import UsvSimulator

sys.path.insert(0, str(TOOLS))
from compare_outages import align_recording  # noqa: E402
from udp_impairment_relay import select_model  # noqa: E402


def load_relay_log(lines):
    log = {"t0_wall_ns": None, "samples": [], "summary": None, "scenario": None}
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"relay log line {number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise ValueError(f"relay log line {number}: expected a JSON object")
        if log["summary"] is not None:
            raise ValueError(f"relay log line {number}: record after final summary")
        event = record.get("event")
        if event == "scenario":
            if log["scenario"] is not None:
                raise ValueError("relay log has more than one scenario record")
            log["scenario"] = record
        elif event == "t0":
            if log["t0_wall_ns"] is not None:
                raise ValueError("relay log has more than one t0 record")
            wall_ns = record.get("wall_ns")
            if type(wall_ns) is not int or wall_ns < 0:
                raise ValueError(f"relay log line {number}: t0 wall_ns must be a nonnegative integer")
            log["t0_wall_ns"] = wall_ns
        elif event == "sample":
            log["samples"].append(record)
        elif event == "summary":
            log["summary"] = record
    if log["t0_wall_ns"] is None:
        raise ValueError("relay log has no t0 record; the run never started impairing")
    return log


def validate_relay_log(relay, scenario, model):
    """Refuse comparisons against a different relay scenario or incomplete sample log.

    The relay records its actual settings at launch. Checking them prevents a
    plausible-looking result from accidentally pairing different seeds, link
    profiles, durations or robots with the supplied scenario file.
    """
    recorded = relay["scenario"]
    if recorded is None:
        raise ValueError("relay log has no scenario record")
    expected = {
        "seed": scenario.seed, "duration_s": scenario.duration_s,
        "robot_id": model.robot_id, "delay_s": model.delay_s,
        "jitter_s": model.jitter_s, "loss": model.loss,
        "burst_loss": {"enter": model.burst_enter, "exit": model.burst_exit},
        "duplicate": model.duplicate, "outages": [list(o) for o in model.outages],
    }
    for field, value in expected.items():
        if recorded.get(field) != value:
            raise ValueError(f"relay log scenario mismatch for {field}: "
                             f"expected {value!r}, got {recorded.get(field)!r}")
    if not relay["samples"]:
        raise ValueError("relay log contains no position samples")
    for index, sample in enumerate(relay["samples"]):
        if sample.get("k") != index:
            raise ValueError(f"relay sample index out of sequence at position {index}")
    summary = relay["summary"]
    if summary is None:
        raise ValueError("relay log has no final summary; retain the complete relay log")
    count = summary.get("samples")
    if type(count) is not int or count != len(relay["samples"]):
        raise ValueError("relay summary sample count mismatch: "
                         f"recorded {count!r}, found {len(relay['samples'])} sample records")


def live_events(recording_text, robot_id, stale_after_s, t0_wall_ns, duration_s):
    """Replay events on scenario time, clipped to [0, duration_s], plus the state at t = 0."""
    origin_ns, spread_ns, aligned = align_recording(recording_text, robot_id)
    shift = (t0_wall_ns - origin_ns) / 1e9
    events = []
    state_at_t0 = "WAITING"
    covered = None
    for event in run_replay(io.StringIO(recording_text), robot_id, stale_after_s):
        t = event["time_s"] - shift
        if event.get("event") == "summary":
            covered = round(t, 3)   # the recording's last observation, on scenario time
            continue
        if t < 0:
            state_at_t0 = event["state"]
        elif t <= duration_s:
            events.append({**event, "time_s": round(t, 9)})
    return events, state_at_t0, {"samples": aligned, "spread_ms": round(spread_ns / 1e6, 3),
                                 "recording_covers_until_s": covered,
                                 "covers_scenario": covered is not None and covered >= duration_s}


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


def timed_virtual(model, scenario, samples):
    """Score the model's monitor driven by the live source's actual send times.

    Each sample the relay forwarded arrives at its relay time plus the delays
    the relay applied. Arrivals are numbered in arrival order, as the bridge
    numbers them, and ticks fall on multiples of ``tick_s`` from t = 0, as in
    the virtual run. So this differs from the nominal virtual run only in
    source timing (rate drift, phase, jitter), and from live only in the
    receive path (transport, bridge, battery gating, tick phase).
    """
    arrivals = sorted(s["rel_s"] + delay for s in samples if s["outcome"] == "forwarded"
                      for delay in s["delays_s"])
    sim = UsvSimulator(model.robot_id, blackout_duration_s=0.0,
                       session_id=f"{model.robot_id}_timed")
    merged = [(round(i * scenario.tick_s, 9), 1, None)
              for i in range(int(scenario.duration_s / scenario.tick_s) + 1)]
    merged += [(round(t, 9), 0, sim.sample(t, int(round(t * 1e9))).to_json())
               for t in arrivals if t <= scenario.duration_s]
    merged.sort(key=lambda item: item[:2])
    text = "".join(Observation(t, payload).to_json() + "\n" for t, _, payload in merged)
    events = list(run_replay(io.StringIO(text), model.robot_id, scenario.stale_after_s))
    return match_outages(model, scenario, events)


def source_timing(samples, rate_hz):
    """Effective live position rate and drift from the model's k / rate_hz."""
    times = [s["rel_s"] for s in samples]
    if len(times) < 2:
        return None
    period = 1.0 / rate_hz
    return {"rate_hz": round((len(times) - 1) / (times[-1] - times[0]), 5),
            "max_abs_drift_s": round(max(abs(t - k * period) for k, t in enumerate(times)), 4)}


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
    validate_relay_log(relay, scenario, model)
    events, state_at_t0, alignment = live_events(
        recording_text, model.robot_id, scenario.stale_after_s, relay["t0_wall_ns"],
        scenario.duration_s)
    live_matched, live_unexplained = match_outages(model, scenario, events)
    virtual, _ = run_robot(model, scenario)
    truth = virtual["ground_truth"]
    # The bridge numbers samples in arrival order, so on the live path every
    # arrival counts, like the monitor's "liveness" policy without duplicates.
    liveness, _ = run_robot(model, dataclasses.replace(scenario, late_samples="liveness"))
    liveness_truth = liveness["ground_truth"]
    live_outcomes = [s["outcome"] for s in relay["samples"]]
    expected = virtual_outcomes(model, scenario, len(live_outcomes))
    differ = [k for k, (a, b) in enumerate(zip(live_outcomes, expected)) if a != b]
    gaps = [b["rel_s"] - a["rel_s"] for a, b in zip(relay["samples"], relay["samples"][1:])]
    timed_matched, timed_unexplained = timed_virtual(model, scenario, relay["samples"])
    return {
        "robot_id": model.robot_id, "seed": scenario.seed,
        "duration_s": scenario.duration_s, "stale_after_s": scenario.stale_after_s,
        "tick_s": scenario.tick_s, "rate_hz": model.rate_hz,
        "alignment": alignment, "live_state_at_t0": state_at_t0,
        "position_interval_s": {
            "median": round(statistics.median(gaps), 4),
            "max": round(max(gaps), 4)} if gaps else None,
        "source_timing": source_timing(relay["samples"], model.rate_hz),
        "fate_agreement": {"samples": len(live_outcomes), "differ": len(differ),
                           "differing_samples": differ[:20]},
        "live": _side(live_matched, live_unexplained, scenario.duration_s),
        "virtual_timed": _side(timed_matched, timed_unexplained, scenario.duration_s),
        "virtual": _side(truth["outages"], truth["unexplained_stale_episodes"],
                         scenario.duration_s),
        "virtual_policy": scenario.late_samples,
        "virtual_monitor": virtual["monitor"],
        "virtual_liveness": _side(liveness_truth["outages"],
                                  liveness_truth["unexplained_stale_episodes"],
                                  scenario.duration_s),
        "virtual_liveness_monitor": liveness["monitor"],
        "relay": relay["summary"],
    }


def markdown(report):
    live, timed, nominal = report["live"], report["virtual_timed"], report["virtual_liveness"]
    source = report["source_timing"] or {}
    lines = [
        f"Robot {report['robot_id']}, seed {report['seed']}, {report['duration_s']:g} s, "
        f"stale_after {report['stale_after_s']:g} s, tick {report['tick_s']:g} s; "
        f"live state at t=0: {report['live_state_at_t0']}",
        f"Fate agreement: {report['fate_agreement']['samples'] - report['fate_agreement']['differ']}"
        f"/{report['fate_agreement']['samples']} samples; alignment spread "
        f"{report['alignment']['spread_ms']} ms; recording covers the scenario: "
        f"{report['alignment']['covers_scenario']}",
        f"Live source: {source.get('rate_hz')} Hz, at most {source.get('max_abs_drift_s')} s "
        f"from the model's sample times",
        "",
        "Cells are detection / recovery latency (s). 'Live timing' drives the model with the",
        "live source's send times; 'nominal' assumes a perfectly periodic source. Both use",
        "late_samples='liveness', the bridge path's analogue.",
        "",
        "| Outage (s) | Live | Model, live timing | Model, nominal |",
        "| --- | --- | --- | --- |",
    ]

    def cell(m):
        if not m["detected"]:
            return "missed"
        det = ("already STALE" if m["already_stale"] else "—") \
            if m["detection_latency_s"] is None else f"{m['detection_latency_s']:.3f}"
        rec = "—" if m["recovery_latency_s"] is None else f"{m['recovery_latency_s']:.3f}"
        return f"{det} / {rec}"

    for a, b, c in zip(live["outages"], timed["outages"], nominal["outages"]):
        lines.append(f"| {a['outage_start_s']:g}–{a['outage_end_s']:g} | {cell(a)} | "
                     f"{cell(b)} | {cell(c)} |")
    lines += ["", f"Unexplained STALE: live {live['unexplained_stale']}, model with live timing "
                  f"{timed['unexplained_stale']}, model nominal {nominal['unexplained_stale']} "
                  f"(nominal under late_samples={report['virtual_policy']!r}: "
                  f"{report['virtual']['unexplained_stale']})"]
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
