# SPDX-License-Identifier: Apache-2.0
"""One-way UDP relay that drops every datagram during scripted outage windows.

Validation tool for issue #28, not part of the installed package. Standard
library only. Place it between a MAVLink source (e.g. MAVProxy ``--out``) and
the receive-only bridge to create independently known outages:

    python tools/udp_outage_relay.py --listen 127.0.0.1:14550 \
        --forward 127.0.0.1:14551 --outage 30:35 --outage 70:72 \
        --duration 120 --log relay-log.jsonl

Outage times are seconds after the **first datagram** the relay receives, so
they land in live traffic however long the source takes to start.

Direction: datagrams from one source address (the first one seen) go to
``--forward``. Nothing travels the other way: the relay never reads its
forwarding socket and never sends to the source, so it cannot carry anything
from the bridge to the vehicle. Datagrams from any other address are counted
and discarded.

The JSON Lines log records wall-clock (``time.time_ns``) instants: each
window's scheduled start/end, the last datagram forwarded before it and the
first forwarded after it. Those are the ground truth for the arrival gap.
"""

import argparse
import ipaddress
import json
import math
import socket
import time

MAX_DATAGRAM = 65535


def parse_endpoint(value):
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit() or not 0 <= int(port) <= 65535:
        raise argparse.ArgumentTypeError("expected HOST:PORT")
    return host.strip("[]"), int(port)


def parse_window(value):
    start, sep, end = value.partition(":")
    try:
        window = (float(start), float(end))
    except ValueError:
        window = None
    if (not sep or window is None or not all(math.isfinite(x) for x in window)
            or not 0 <= window[0] < window[1]):
        raise argparse.ArgumentTypeError("expected START:END seconds with 0 <= START < END")
    return window


def validate_windows(windows, duration_s=None):
    windows = sorted(windows)
    for (_, end), (start, _) in zip(windows, windows[1:]):
        if start < end:
            raise ValueError("outage windows must not overlap")
    if duration_s is not None and windows and windows[-1][1] > duration_s:
        raise ValueError("outage windows must end before --duration")
    return windows


class OutageRelay:
    """Forward datagrams from one source, dropping those inside windows.

    ``clock`` is monotonic seconds and ``wall_ns`` Unix nanoseconds; both are
    injectable for tests. ``emit`` receives each log record as a dict.
    """

    def __init__(self, listen_sock, forward_sock, forward_to, windows, *,
                 emit, clock=time.monotonic, wall_ns=time.time_ns):
        self.listen = listen_sock
        self.out = forward_sock
        self.forward_to = forward_to
        self.windows = validate_windows(windows)
        self.emit = emit
        self.clock = clock
        self.wall_ns = wall_ns
        self.source = None
        self.origin = None          # (monotonic s, wall ns) at first datagram
        self.forwarded = 0
        self.dropped = 0
        self.other_sources = 0
        self._last_forwarded_ns = None
        self._state = [None] * len(self.windows)  # None -> "open" -> "closed"
        self._window_drops = [0] * len(self.windows)

    def _wall_at(self, offset_s):
        return self.origin[1] + int(round(offset_s * 1e9))

    def elapsed(self):
        return None if self.origin is None else self.clock() - self.origin[0]

    def _advance(self, elapsed):
        """Emit window boundaries crossed by ``elapsed``, in order."""
        for index, (start, end) in enumerate(self.windows):
            if self._state[index] is None and elapsed >= start:
                self._state[index] = "open"
                self.emit({"event": "drop_start", "window": index,
                           "scheduled_s": start, "scheduled_wall_ns": self._wall_at(start),
                           "last_forwarded_wall_ns": self._last_forwarded_ns})
            if self._state[index] == "open" and elapsed >= end:
                self._state[index] = "closing"
                self.emit({"event": "drop_end", "window": index,
                           "scheduled_s": end, "scheduled_wall_ns": self._wall_at(end),
                           "dropped": self._window_drops[index]})

    def _in_window(self, elapsed):
        for index, (start, end) in enumerate(self.windows):
            if start <= elapsed < end:
                return index
        return None

    def handle(self, data, address):
        now_ns = self.wall_ns()
        if self.origin is None:
            self.origin = (self.clock(), now_ns)
            self.source = address
            self.emit({"event": "first_datagram", "wall_ns": now_ns,
                       "source": f"{address[0]}:{address[1]}",
                       "forward_to": f"{self.forward_to[0]}:{self.forward_to[1]}",
                       "windows": [list(w) for w in self.windows]})
        if address != self.source:
            self.other_sources += 1
            return
        elapsed = self.elapsed()
        self._advance(elapsed)
        index = self._in_window(elapsed)
        if index is not None:
            self.dropped += 1
            self._window_drops[index] += 1
            return
        self.out.sendto(data, self.forward_to)
        self.forwarded += 1
        self._last_forwarded_ns = now_ns
        for i, state in enumerate(self._state):
            if state == "closing":
                self._state[i] = "closed"
                self.emit({"event": "first_forwarded_after", "window": i,
                           "wall_ns": now_ns})

    def next_deadline(self):
        """Seconds until the next window boundary, or None."""
        elapsed = self.elapsed()
        if elapsed is None:
            return None
        upcoming = [t for w in self.windows for t in w if t > elapsed]
        return min(upcoming) - elapsed if upcoming else None

    def summary(self):
        return {"event": "summary", "forwarded": self.forwarded,
                "dropped": self.dropped, "other_sources": self.other_sources,
                "elapsed_s": self.elapsed(),
                "windows_completed": sum(s == "closed" for s in self._state)}


def run(relay, duration_s=None, poll_s=0.05):
    """Receive until ``duration_s`` after the first datagram, if given."""
    while True:
        elapsed = relay.elapsed()
        if elapsed is not None:
            relay._advance(elapsed)
            if duration_s is not None and elapsed >= duration_s:
                return
        wait = relay.next_deadline()
        if duration_s is not None and elapsed is not None:
            remaining = duration_s - elapsed
            wait = remaining if wait is None else min(wait, remaining)
        relay.listen.settimeout(max(min(wait if wait is not None else poll_s, 1.0), 0.001))
        try:
            data, address = relay.listen.recvfrom(MAX_DATAGRAM)
        except socket.timeout:
            continue
        relay.handle(data, address)


def _family(host):
    try:
        return socket.AF_INET6 if ipaddress.ip_address(host).version == 6 else socket.AF_INET
    except ValueError:
        return socket.AF_INET


def main(args=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--listen", type=parse_endpoint, required=True, metavar="HOST:PORT")
    parser.add_argument("--forward", type=parse_endpoint, required=True, metavar="HOST:PORT")
    parser.add_argument("--outage", type=parse_window, action="append", default=[],
                        metavar="START:END", help="seconds after the first datagram; repeatable")
    parser.add_argument("--duration", type=float, help="stop this many seconds after the first datagram")
    parser.add_argument("--log", metavar="PATH", help="create a JSON Lines log; never overwrite")
    options = parser.parse_args(args)
    if options.listen == options.forward:
        parser.error("--listen and --forward must differ")
    if options.duration is not None and not options.duration > 0:
        parser.error("--duration must be positive")
    try:
        windows = validate_windows(options.outage, options.duration)
    except ValueError as exc:
        parser.error(str(exc))
    log = open(options.log, "x", encoding="utf-8", newline="\n") if options.log else None

    def emit(record):
        line = json.dumps(record, separators=(",", ":"))
        print(line, flush=True)
        if log is not None:
            log.write(line + "\n")
            log.flush()

    try:
        with socket.socket(_family(options.listen[0]), socket.SOCK_DGRAM) as listen, \
                socket.socket(_family(options.forward[0]), socket.SOCK_DGRAM) as out:
            listen.bind(options.listen)
            relay = OutageRelay(listen, out, options.forward, windows, emit=emit)
            try:
                run(relay, options.duration)
            except KeyboardInterrupt:
                pass
            emit(relay.summary())
    except OSError as exc:
        parser.error(str(exc))
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    main()
