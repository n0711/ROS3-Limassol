# SPDX-License-Identifier: Apache-2.0
"""Listen for MAVLink over UDP and observe arrival liveness, receive-only.

Run ``python -m ros3_limassol.mavlink_bridge --record run.jsonl``. The bridge
binds a UDP socket and only calls ``recv``: it never sends, so it never
requests streams, sends heartbeats or commands a vehicle. The sender must
already be configured to push MAVLink to this address (e.g. ArduPilot SITL
``--out udp:127.0.0.1:14550``).

Mapped samples are schema-v1 telemetry, so an optional recording replays
and exports evidence with the existing ``replay`` and ``evidence`` tools.
"""

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
import socket
import time

from .live_recorder import LiveRecorder
from .mavlink import MavlinkParser, MavlinkTelemetryMapper
from .monitor import LinkMonitor
from .telemetry import finite_number

MAX_DATAGRAM = 65535


class BridgeSession:
    """Feed datagrams through parser, mapper, monitor and optional recorder.

    All times come from one injected monotonic ``clock``. Callers invoke
    ``tick`` independently of arrivals so silence is observed and recorded.
    """

    def __init__(self, mapper, monitor, *, recorder=None, clock=time.monotonic):
        self.parser = MavlinkParser()
        self.mapper = mapper
        self.monitor = monitor
        self.recorder = recorder
        self._clock = clock
        self._started = finite_number(clock(), "receiver time")
        self._previous_state = None
        self.datagrams = 0

    def _elapsed(self):
        return self._clock() - self._started

    def handle_datagram(self, data):
        """Return status-change events caused by one received datagram."""
        self.datagrams += 1
        events = []
        for frame in self.parser.feed(data):
            sample = self.mapper.observe(frame)
            if sample is None:
                continue
            raw = sample.to_json()
            if self.recorder is not None:
                self.recorder.receive(raw)
            self.monitor.ingest(raw, self._elapsed())
            events.extend(self._status_change())
        return events

    def tick(self):
        """Observe the link now, recording a silence tick if enabled."""
        if self.recorder is not None:
            self.recorder.tick()
        return self._status_change()

    def _status_change(self):
        now = self._elapsed()
        status = self.monitor.snapshot(now)
        if status.state == self._previous_state:
            return []
        self._previous_state = status.state
        return [{"time_s": now, **asdict(status)}]

    def summary(self):
        now = self._elapsed()
        return {"time_s": now, "event": "summary",
                **asdict(self.monitor.snapshot(now)),
                "datagrams": self.datagrams,
                "session_id": self.mapper.session_id,
                "mavlink": dict(self.parser.stats),
                "mapping": dict(self.mapper.stats)}


def serve(sock, session, *, tick_s=0.5, duration_s=None, emit=print,
          clock=time.monotonic):
    """Receive until ``duration_s`` elapses (or forever), ticking every ``tick_s``."""
    tick_s = finite_number(tick_s, "tick_s")
    if not 0 < tick_s <= 60:
        raise ValueError("tick_s must be in (0, 60]")
    started = clock()
    deadline = None if duration_s is None else started + duration_s
    next_tick = started
    while True:
        now = clock()
        if deadline is not None and now >= deadline:
            return
        if now >= next_tick:
            for event in session.tick():
                emit(event)
            while next_tick <= now:
                next_tick += tick_s
        wait = next_tick - now
        if deadline is not None:
            wait = min(wait, deadline - now)
        sock.settimeout(max(wait, 0.001))
        try:
            data = sock.recv(MAX_DATAGRAM)
        except socket.timeout:
            continue
        for event in session.handle_datagram(data):
            emit(event)


def _endpoint(value):
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("expected HOST:PORT")
    return host.strip("[]"), int(port)


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--listen", type=_endpoint, default=("127.0.0.1", 14550),
                        metavar="HOST:PORT", help="UDP address to bind (default 127.0.0.1:14550)")
    parser.add_argument("--robot-id", default="usv01")
    parser.add_argument("--system-id", type=int, default=1, help="MAVLink source system ID")
    parser.add_argument("--component-id", type=int, help="optional MAVLink source component ID")
    parser.add_argument("--record", metavar="PATH", help="create an observation JSONL file; never overwrite")
    parser.add_argument("--stale-after", type=float, default=1.0)
    parser.add_argument("--tick", type=float, default=0.5, help="observation interval in seconds")
    parser.add_argument("--battery-max-age", type=float, default=5.0)
    parser.add_argument("--duration", type=float, help="stop after this many seconds")
    options = parser.parse_args(args)
    emit = lambda event: print(json.dumps(event, allow_nan=False, separators=(",", ":")), flush=True)
    try:
        if options.duration is not None and not finite_number(options.duration, "duration") > 0:
            raise ValueError("duration must be positive")
        mapper = MavlinkTelemetryMapper(
            options.robot_id, options.system_id, options.component_id,
            battery_max_age_s=options.battery_max_age)
        monitor = LinkMonitor(robot_id=options.robot_id, stale_after_s=options.stale_after)
        family = socket.AF_INET6 if ":" in options.listen[0] else socket.AF_INET
        with ExitStack() as stack:
            sock = stack.enter_context(socket.socket(family, socket.SOCK_DGRAM))
            sock.bind(options.listen)
            recorder = (stack.enter_context(LiveRecorder(options.record))
                        if options.record else None)
            session = BridgeSession(mapper, monitor, recorder=recorder)
            try:
                serve(sock, session, tick_s=options.tick,
                      duration_s=options.duration, emit=emit)
            except KeyboardInterrupt:
                pass
            emit(session.summary())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
