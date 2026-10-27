# SPDX-License-Identifier: Apache-2.0
"""One-way UDP relay that applies a seeded impairment scenario to live MAVLink.

Validation tool for issue #33, not part of the installed package. It uses the
standard library and ``ros3_limassol.impairment``:

    python tools/udp_impairment_relay.py --listen 127.0.0.1:14550 \
        --forward 127.0.0.1:14551 --scenario live.json --robot-id usv01 \
        --warmup 30 --log relay.jsonl

**Sample alignment.** Datagrams pass unchanged for ``--warmup`` seconds after
the first one. The next ``GLOBAL_POSITION_INT`` datagram from ``--system-id``
then defines t = 0 and is sample 0; the k-th such datagram is sample k. Its
fate (burst state, independent loss, duplication, two delays) is the k-th
value of ``link_fates(model, seed)``: the same random stream and draw order
the virtual model uses for its sample k. A fate is drawn for every position
datagram, including those an outage drops, so the two stay aligned.

**Other datagrams** (``SYS_STATUS``, ``HEARTBEAT``, ...) are dropped inside
outages and while the latest position sample left the burst model in its loss
state; otherwise they are forwarded after the fixed ``delay_s``. Independent
loss, jitter and duplication model *samples*, so they apply only to position
datagrams, the only ones the bridge turns into samples. The relay reads the
first frame's header of each datagram (MAVProxy sends one frame per datagram)
and does not verify checksums.

Outages are the scenario's windows on the relay clock since t = 0 and drop
everything. Scenario ``restarts`` cannot be applied to live traffic and are
rejected. After ``duration_s`` the relay forwards unchanged for ``--tail``
seconds, delivers anything still scheduled, and exits.

Direction: datagrams from one source address (the first seen) go to
``--forward``. The relay never reads its forwarding socket and never sends to
the source. The JSON Lines log records t = 0 in wall-clock nanoseconds, each
position sample's outcome, and the relay's own send-time error.
"""

import argparse
import heapq
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time

try:
    from ros3_limassol.impairment import link_fates, parse_scenario
except ImportError:  # running from a checkout without installation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ros3_limassol.impairment import link_fates, parse_scenario

MAX_DATAGRAM = 65535
MSG_GLOBAL_POSITION_INT = 33
NO_POSITION_TIMEOUT_S = 60.0


def frame_header(data):
    """Return (system_id, message_id) of the first MAVLink frame, or None."""
    if len(data) >= 6 and data[0] == 0xFE:            # MAVLink 1
        return data[3], data[5]
    if len(data) >= 10 and data[0] == 0xFD:           # MAVLink 2
        return data[5], data[7] | (data[8] << 8) | (data[9] << 16)
    return None


def parse_endpoint(value):
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("expected HOST:PORT")
    return host.strip("[]"), int(port)


def select_model(scenario, robot_id=None):
    """Pick one robot's link model; reject what live traffic cannot express."""
    models = {m.robot_id: m for m in scenario.robots}
    if robot_id is None:
        if len(models) != 1:
            raise ValueError("scenario has several robots; choose one with --robot-id")
        robot_id = next(iter(models))
    if robot_id not in models:
        raise ValueError(f"robot {robot_id!r} is not in the scenario")
    model = models[robot_id]
    if model.restarts:
        raise ValueError("scenario restarts cannot be applied to live traffic")
    return model


class ImpairmentRelay:
    """Apply one robot's link model to datagrams from a single source.

    ``clock`` is monotonic seconds and ``wall_ns`` Unix nanoseconds; both are
    injectable for tests, as is ``emit`` (receives each log record).
    """

    def __init__(self, forward_sock, forward_to, model, seed, duration_s, *,
                 warmup_s=30.0, system_id=1, emit, clock=time.monotonic,
                 wall_ns=time.time_ns):
        if model.restarts:
            raise ValueError("scenario restarts cannot be applied to live traffic")
        if not warmup_s >= 0:
            raise ValueError("warmup must be nonnegative")
        self.out = forward_sock
        self.forward_to = forward_to
        self.model = model
        self.duration_s = duration_s
        self.warmup_s = warmup_s
        self.system_id = system_id
        self.emit = emit
        self.clock = clock
        self.wall_ns = wall_ns
        self._fates = link_fates(model, seed)
        self._queue = []        # (due monotonic s, order, data)
        self._order = 0
        self._burst = False
        self.source = None
        self.first = None       # monotonic time of the first datagram
        self.t0 = None          # monotonic time of sample 0
        self.samples = 0
        self.counts = {"warmup": 0, "after_end": 0, "other_sources": 0,
                       "samples_forwarded": 0, "samples_outage": 0,
                       "samples_burst": 0, "samples_loss": 0, "sample_copies_sent": 0,
                       "other_forwarded": 0, "other_outage": 0, "other_burst": 0,
                       "datagrams_sent": 0}
        self._late_max = 0.0
        self._late_sum = 0.0

    def _schedule(self, due, data):
        heapq.heappush(self._queue, (due, self._order, data))
        self._order += 1

    def flush(self, now=None):
        """Send every datagram due by ``now``; return the next due time or None."""
        now = self.clock() if now is None else now
        while self._queue and self._queue[0][0] <= now:
            due, _, data = heapq.heappop(self._queue)
            self.out.sendto(data, self.forward_to)
            self.counts["datagrams_sent"] += 1
            late = now - due
            self._late_max = max(self._late_max, late)
            self._late_sum += late
        return self._queue[0][0] if self._queue else None

    def handle(self, data, address):
        now = self.clock()
        if self.source is None:
            self.source, self.first = address, now
            self.emit({"event": "first_datagram", "wall_ns": self.wall_ns(),
                       "source": f"{address[0]}:{address[1]}",
                       "forward_to": f"{self.forward_to[0]}:{self.forward_to[1]}",
                       "robot_id": self.model.robot_id, "warmup_s": self.warmup_s})
        if address != self.source:
            self.counts["other_sources"] += 1
            return
        is_sample = frame_header(data) == (self.system_id, MSG_GLOBAL_POSITION_INT)
        if self.t0 is None:
            if is_sample and now - self.first >= self.warmup_s:
                self.t0 = now
                self.emit({"event": "t0", "wall_ns": self.wall_ns(),
                           "after_first_datagram_s": round(now - self.first, 6)})
            else:
                self.counts["warmup"] += 1
                self._schedule(now, data)
                return
        rel = now - self.t0
        if rel >= self.duration_s:
            self.counts["after_end"] += 1
            self._schedule(now, data)
            return
        in_outage = any(start <= rel < end for start, end in self.model.outages)
        if not is_sample:
            if in_outage:
                self.counts["other_outage"] += 1
            elif self._burst:
                self.counts["other_burst"] += 1
            else:
                self.counts["other_forwarded"] += 1
                self._schedule(now + self.model.delay_s, data)
            return
        fate = next(self._fates)  # drawn for every sample, whatever happens to it
        self._burst = fate.burst
        if in_outage:
            outcome = "outage"
        elif fate.burst:
            outcome = "burst"
        elif fate.lost:
            outcome = "loss"
        else:
            outcome = "forwarded"
        record = {"event": "sample", "k": self.samples, "rel_s": round(rel, 6),
                  "wall_ns": self.wall_ns(), "outcome": outcome}
        if outcome == "forwarded":
            delays = fate.delays[:fate.copies]
            for delay in delays:
                self._schedule(now + delay, data)
            self.counts["sample_copies_sent"] += len(delays)
            record["delays_s"] = [round(d, 6) for d in delays]
        self.counts[f"samples_{outcome}"] += 1
        self.samples += 1
        self.emit(record)

    def finished(self, now, tail_s):
        return (self.t0 is not None and now - self.t0 >= self.duration_s + tail_s
                and not self._queue)

    def summary(self):
        sent = self.counts["datagrams_sent"]
        return {"event": "summary", "samples": self.samples, **self.counts,
                "send_late_max_ms": round(self._late_max * 1e3, 3),
                "send_late_mean_ms": round(self._late_sum / sent * 1e3, 3) if sent else None}


def run(relay, listen, tail_s=5.0, poll_s=0.05):
    """Receive and forward until ``duration_s + tail_s`` after t = 0."""
    while True:
        now = relay.clock()
        if relay.finished(now, tail_s):
            return
        if relay.t0 is None and relay.first is not None and \
                now - relay.first > relay.warmup_s + NO_POSITION_TIMEOUT_S:
            raise RuntimeError(f"no GLOBAL_POSITION_INT from system {relay.system_id} "
                               f"within {NO_POSITION_TIMEOUT_S:g} s after the warm-up")
        due = relay.flush(now)
        wait = poll_s if due is None else min(max(due - now, 0.0), poll_s)
        listen.settimeout(max(wait, 0.0005))
        try:
            data, address = listen.recvfrom(MAX_DATAGRAM)
        except socket.timeout:
            continue
        relay.handle(data, address)
        relay.flush()


def _family(host):
    try:
        return socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    except ValueError:
        return socket.AF_INET


def _reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--listen", type=parse_endpoint, required=True, metavar="HOST:PORT")
    parser.add_argument("--forward", type=parse_endpoint, required=True, metavar="HOST:PORT")
    parser.add_argument("--scenario", required=True, help="impairment scenario JSON")
    parser.add_argument("--robot-id", help="robot whose link model to apply (default: the only one)")
    parser.add_argument("--system-id", type=int, default=1, help="MAVLink system ID of the vehicle")
    parser.add_argument("--warmup", type=float, default=30.0,
                        help="seconds after the first datagram before t = 0 (default 30)")
    parser.add_argument("--tail", type=float, default=5.0,
                        help="seconds of unchanged forwarding after duration_s (default 5)")
    parser.add_argument("--log", metavar="PATH", help="create a JSON Lines log; never overwrite")
    options = parser.parse_args(args)
    if options.listen == options.forward:
        parser.error("--listen and --forward must differ")
    if not 0 <= options.system_id <= 255:
        parser.error("--system-id must be in [0, 255]")
    if not options.tail >= 0:
        parser.error("--tail must be nonnegative")
    try:
        with open(options.scenario, encoding="utf-8") as stream:
            scenario = parse_scenario(json.load(stream, parse_constant=_reject_constant))
        model = select_model(scenario, options.robot_id)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    log = open(options.log, "x", encoding="utf-8", newline="\n") if options.log else None

    def emit(record):
        line = json.dumps(record, separators=(",", ":"))
        if log is not None:
            log.write(line + "\n")
            log.flush()
        if record["event"] != "sample":
            print(line, flush=True)

    try:
        with socket.socket(_family(options.listen[0]), socket.SOCK_DGRAM) as listen, \
                socket.socket(_family(options.forward[0]), socket.SOCK_DGRAM) as out:
            listen.bind(options.listen)
            relay = ImpairmentRelay(out, options.forward, model, scenario.seed,
                                    scenario.duration_s, warmup_s=options.warmup,
                                    system_id=options.system_id, emit=emit)
            emit({"event": "scenario", "seed": scenario.seed, "duration_s": scenario.duration_s,
                  "robot_id": model.robot_id, "delay_s": model.delay_s,
                  "jitter_s": model.jitter_s, "loss": model.loss,
                  "burst_loss": {"enter": model.burst_enter, "exit": model.burst_exit},
                  "duplicate": model.duplicate, "outages": [list(o) for o in model.outages]})
            try:
                run(relay, listen, options.tail)
            except KeyboardInterrupt:
                pass
            except RuntimeError as exc:
                emit(relay.summary())
                parser.exit(1, f"{parser.prog}: error: {exc}\n")
            emit(relay.summary())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    main()
