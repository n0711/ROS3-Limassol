"""Tests for the issue #28 validation tools in tools/ (not the installed package)."""

import argparse
import importlib.util
import json
from pathlib import Path
import socket
import unittest

from ros3_limassol.recording import Observation
from ros3_limassol.simulator import UsvSimulator

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay_tool = load("udp_outage_relay")
compare_tool = load("compare_outages")
WALL0 = 1_800_000_000_000_000_000


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, address):
        self.sent.append((data, address))


class RelayTests(unittest.TestCase):
    def relay(self, windows):
        self.now = 50.0
        self.events = []
        self.out = FakeSocket()
        return relay_tool.OutageRelay(
            None, self.out, ("127.0.0.1", 9), windows, emit=self.events.append,
            clock=lambda: self.now, wall_ns=lambda: WALL0 + int(round((self.now - 50) * 1e9)))

    def feed(self, relay, until_s, source=("127.0.0.1", 5000)):
        for i in range(int(round(until_s * 10)) + 1):
            self.now = 50.0 + i / 10
            relay._advance(relay.elapsed() or 0.0)
            relay.handle(bytes([i % 256]), source)

    def test_drops_only_inside_windows_and_logs_ground_truth(self):
        relay = self.relay([(2.0, 3.0)])
        self.feed(relay, 5.0)
        self.assertEqual((relay.forwarded, relay.dropped), (41, 10))
        events = {e["event"]: e for e in self.events}
        self.assertEqual([e["event"] for e in self.events],
                         ["first_datagram", "drop_start", "drop_end", "first_forwarded_after"])
        self.assertEqual(events["drop_start"]["last_forwarded_wall_ns"], WALL0 + 1_900_000_000)
        self.assertEqual(events["drop_start"]["scheduled_wall_ns"], WALL0 + 2_000_000_000)
        self.assertEqual(events["drop_end"]["dropped"], 10)
        self.assertEqual(events["first_forwarded_after"]["wall_ns"], WALL0 + 3_000_000_000)
        self.assertEqual(relay.summary()["windows_completed"], 1)

    def test_forwards_one_way_from_a_single_source(self):
        relay = self.relay([])
        self.feed(relay, 0.3)
        relay.handle(b"x", ("127.0.0.1", 6000))
        self.assertEqual(relay.other_sources, 1)
        self.assertEqual({address for _, address in self.out.sent}, {("127.0.0.1", 9)})

    def test_rejects_bad_windows(self):
        for bad in ("3:2", "nan:1", "a:b", "-1:2", "1", "1:inf"):
            with self.subTest(bad=bad), self.assertRaises(argparse.ArgumentTypeError):
                relay_tool.parse_window(bad)
        with self.assertRaises(ValueError):
            relay_tool.validate_windows([(1, 3), (2, 4)])
        with self.assertRaises(ValueError):
            relay_tool.validate_windows([(1, 3)], duration_s=2)

    def test_relays_real_udp_datagrams(self):
        sockets = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(4)]
        for s in sockets:
            self.addCleanup(s.close)
        listen, out, sink, source = sockets
        listen.bind(("127.0.0.1", 0))
        sink.bind(("127.0.0.1", 0))
        for i in range(3):
            source.sendto(bytes([i]), listen.getsockname())
        relay = relay_tool.OutageRelay(listen, out, sink.getsockname(), [],
                                       emit=lambda record: None)
        relay_tool.run(relay, duration_s=0.3)
        sink.settimeout(1.0)
        self.assertEqual([sink.recv(16) for _ in range(3)], [b"\x00", b"\x01", b"\x02"])


def recording(gaps, end_s=6.0, stale_after=1.0):
    """Samples every 0.1 s (wall = WALL0 + t) except inside gaps; ticks every 0.1 s."""
    sim = UsvSimulator(blackout_duration_s=0.0, session_id="sitl")
    lines = []
    for i in range(int(end_s * 10) + 1):
        t = round(i / 10, 6)
        if not any(a < t < b for a, b in gaps):
            payload = sim.sample(t, WALL0 + int(t * 1e9) + 30_000).to_json()
            lines.append(Observation(t, payload).to_json())
        lines.append(Observation(t, None).to_json())
    return "\n".join(lines) + "\n"


def relay_log(windows, end_s=6.0):
    """windows: (scheduled start, end, last forwarded, first forwarded after) in s."""
    records = [{"event": "first_datagram", "wall_ns": WALL0}]
    for i, (start, end, last, resumed) in enumerate(windows):
        records += [{"event": "drop_start", "window": i, "scheduled_s": start,
                     "scheduled_wall_ns": WALL0 + int(start * 1e9),
                     "last_forwarded_wall_ns": WALL0 + int(last * 1e9)},
                    {"event": "drop_end", "window": i, "scheduled_s": end,
                     "scheduled_wall_ns": WALL0 + int(end * 1e9), "dropped": 10},
                    {"event": "first_forwarded_after", "window": i,
                     "wall_ns": WALL0 + int(resumed * 1e9)}]
    records.append({"event": "summary", "elapsed_s": end_s})
    return [json.dumps(r) for r in records]


class CompareTests(unittest.TestCase):
    def test_rejects_truncated_logs_instead_of_reporting_success(self):
        complete = relay_log([(2.0, 3.5, 1.9, 3.5)])
        for length in range(1, len(complete)):
            with self.subTest(length=length), self.assertRaisesRegex(ValueError, "final summary"):
                compare_tool.compare(complete[:length], recording([]))
        for missing in range(1, 4):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                compare_tool.compare(complete[:missing] + complete[missing + 1:], recording([]))

    def test_completed_zero_window_control_remains_valid(self):
        self.assertTrue(compare_tool.compare(relay_log([]), recording([]))["all_expected_detected"])

    def test_rejects_duplicate_nonobject_and_invalid_summary_records(self):
        complete = relay_log([(2.0, 3.5, 1.9, 3.5)])
        cases = [complete + complete[-1:], complete[:1] + complete,
                 complete[:2] + complete[1:], ["null"], ["[]"]]
        for elapsed in (None, True, -1, float("nan"), float("inf"), "6"):
            cases.append(complete[:-1] + [json.dumps({"event": "summary", "elapsed_s": elapsed})])
        for lines in cases:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                compare_tool.load_relay_log(lines)

    def test_rejects_recovery_after_summary_end(self):
        lines = relay_log([(2.0, 3.5, 1.9, 3.5)], end_s=3.0)
        with self.assertRaisesRegex(ValueError, "timestamps"):
            compare_tool.compare(lines, recording([]))

    def test_matches_detectable_outage_and_skips_short_one(self):
        text = recording([(1.9, 3.5), (4.2, 4.8)])
        log = relay_log([(2.0, 3.5, 1.9, 3.5), (4.3, 4.8, 4.2, 4.8)])
        report = compare_tool.compare(log, text)
        long, short = report["windows"]
        self.assertTrue(long["matched"] and long["stale_expected"])
        self.assertAlmostEqual(long["arrival_gap_s"], 1.6, places=6)
        self.assertGreaterEqual(long["stale_minus_expected_s"], -0.001)
        self.assertLessEqual(long["stale_minus_expected_s"], 0.101)
        self.assertAlmostEqual(long["healthy_after_resume_s"], 0.0, places=3)
        self.assertEqual((short["stale_expected"], short["matched"]), (False, False))
        self.assertTrue(report["all_expected_detected"])
        self.assertEqual(report["unexplained_stale"], [])
        self.assertLess(report["alignment"]["spread_ms"], 1.0)
        self.assertIn("| 0 | 2.0–3.5 |", compare_tool.markdown(report))

    def test_flags_stale_without_a_relay_outage_but_not_after_relay_end(self):
        text = recording([(1.0, 2.5), (4.0, 99)])
        report = compare_tool.compare(relay_log([], end_s=4.5), text)
        self.assertEqual(len(report["unexplained_stale"]), 1)
        self.assertEqual(report["stale_after_relay_stopped"], 1)

    def test_compares_replay_with_live_bridge_output(self):
        text = recording([(1.9, 3.5)])
        report = compare_tool.compare(relay_log([(2.0, 3.5, 1.9, 3.5)]), text)
        live = [json.dumps({"time_s": t + 0.0002, "state": s})
                for t, s in report["replay_transitions"]]
        live.append(json.dumps({"event": "summary", "state": "HEALTHY", "time_s": 6.0}))
        match = compare_tool.compare(relay_log([(2.0, 3.5, 1.9, 3.5)]), text,
                                     bridge_lines=live)["replay_matches_live"]
        self.assertEqual(match, {"same_state_sequence": True, "max_time_difference_s": 0.0002})
        wrong = compare_tool.compare(relay_log([]), text, bridge_lines=live[1:])
        self.assertFalse(wrong["replay_matches_live"]["same_state_sequence"])

    def test_requires_alignable_inputs(self):
        with self.assertRaises(ValueError):
            compare_tool.compare(["{}"], recording([]))
        empty = Observation(0.0, None).to_json() + "\n"
        with self.assertRaises(ValueError):
            compare_tool.compare(relay_log([]), empty)


if __name__ == "__main__":
    unittest.main()
