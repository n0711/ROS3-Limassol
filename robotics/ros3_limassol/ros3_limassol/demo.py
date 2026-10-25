# SPDX-License-Identifier: Apache-2.0
"""Run `python -m ros3_limassol.demo` without installing ROS."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import time

from .monitor import LinkMonitor
from .recording import MAX_RECORDS, Observation
from .simulator import UsvSimulator
from .telemetry import finite_number


def _configure_demo(duration_s, rate_hz, stale_after_s,
                    blackout_start_s, blackout_duration_s):
    """Validate all options before a CLI recording file is created."""
    duration_s = finite_number(duration_s, "duration_s")
    rate_hz = finite_number(rate_hz, "rate_hz")
    if not 0 < duration_s <= 3600 or not 0 < rate_hz <= 1000:
        raise ValueError("duration must be in (0, 3600]; rate in (0, 1000]")
    if int(duration_s * rate_hz) + 1 > MAX_RECORDS:
        raise ValueError("demo is limited to one million samples")
    monitor = LinkMonitor(stale_after_s=stale_after_s)
    sim = UsvSimulator(blackout_start_s=blackout_start_s,
                       blackout_duration_s=blackout_duration_s,
                       session_id="deterministic_demo")
    return duration_s, rate_hz, monitor, sim


def run_demo(duration_s=8.0, rate_hz=10.0, stale_after_s=1.0,
             blackout_start_s=2.0, blackout_duration_s=3.0, realtime=False,
             record_to=None):
    """Yield status transitions using virtual time, or pace them in real time."""
    configuration = _configure_demo(duration_s, rate_hz, stale_after_s,
                                    blackout_start_s, blackout_duration_s)
    return _run_demo(configuration, realtime, record_to)


def _run_demo(configuration, realtime, record_to):
    duration_s, rate_hz, monitor, sim = configuration
    previous = "WAITING"
    yield {"time_s": 0.0, **asdict(monitor.snapshot(0.0))}
    started = time.monotonic()
    for index in range(int(duration_s * rate_hz) + 1):
        elapsed = index / rate_hz
        if realtime:
            time.sleep(max(0.0, started + elapsed - time.monotonic()))
        packet = sim.sample(elapsed, int(elapsed * 1_000_000_000))
        raw = None if packet is None else packet.to_json()
        if record_to is not None:
            record_to.write(Observation(elapsed, raw).to_json() + "\n")
        if raw is not None:
            monitor.ingest(raw, elapsed)
        status = monitor.snapshot(elapsed)
        if status.state != previous:
            previous = status.state
            yield {"time_s": elapsed, **asdict(status)}
    yield {"time_s": elapsed, "event": "summary", **asdict(status)}


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--realtime", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit JSON Lines")
    parser.add_argument("--record", metavar="PATH", help="create an observation JSONL file; never overwrite")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--stale-after", type=float, default=1.0)
    parser.add_argument("--blackout-start", type=float, default=2.0)
    parser.add_argument("--blackout-duration", type=float, default=3.0)
    options = parser.parse_args(args)
    try:
        configuration = _configure_demo(
            options.duration, options.rate, options.stale_after,
            options.blackout_start, options.blackout_duration,
        )
        with ExitStack() as stack:
            stream = (stack.enter_context(open(options.record, "x", encoding="utf-8", newline="\n"))
                      if options.record else None)
            for event in _run_demo(configuration, options.realtime, stream):
                if options.json:
                    print(json.dumps(event, allow_nan=False, separators=(",", ":")))
                elif event.get("event") == "summary":
                    print(f"Accepted: {event['accepted']}; rejected: {event['rejected']}")
                else:
                    print(f"t={event['time_s']:4.1f}s  {event['state']}")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
