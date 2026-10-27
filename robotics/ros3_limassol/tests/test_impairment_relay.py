"""Tests for the issue #33 live impairment relay in tools/ (not the installed package)."""

import importlib.util
import json
from pathlib import Path
import unittest

from ros3_limassol.impairment import link_fates, parse_scenario
from ros3_limassol.recording import Observation
from ros3_limassol.simulator import UsvSimulator

TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("udp_impairment_relay",
                                              TOOLS / "udp_impairment_relay.py")
relay_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay_tool)

SOURCE = ("127.0.0.1", 5000)
WALL0 = 1_800_000_000_000_000_000


def frame(message_id, system_id=1, version=2, body=b"\x00" * 4):
    if version == 1:
        return bytes([0xFE, len(body), 0, system_id, 1, message_id]) + body
    return bytes([0xFD, len(body), 0, 0, 0, system_id, 1, message_id & 0xFF,
                  (message_id >> 8) & 0xFF, (message_id >> 16) & 0xFF]) + body


POSITION = frame(33)
STATUS = frame(1)


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, address):
        self.sent.append(data)


def scenario(**robot):
    return parse_scenario({"seed": 11, "duration_s": 60, "tick_s": 0.1,
                           "stale_after_s": 1.0,
                           "robots": [{"robot_id": "usv01", "rate_hz": 4, **robot}]})


class FrameHeaderTests(unittest.TestCase):
    def test_reads_system_and_message_id_in_both_versions(self):
        self.assertEqual(relay_tool.frame_header(frame(33)), (1, 33))
        self.assertEqual(relay_tool.frame_header(frame(33, version=1)), (1, 33))
        self.assertEqual(relay_tool.frame_header(frame(70000, system_id=7)), (7, 70000))
        self.assertIsNone(relay_tool.frame_header(b"\x00\x01\x02"))
        self.assertIsNone(relay_tool.frame_header(b"\xfd\x01"))


class RelayTests(unittest.TestCase):
    def make(self, sc, warmup=2.0):
        self.now = 100.0
        self.events = []
        self.out = FakeSocket()
        return relay_tool.ImpairmentRelay(
            self.out, ("127.0.0.1", 9), sc.robots[0], sc.seed, sc.duration_s,
            warmup_s=warmup, emit=self.events.append, clock=lambda: self.now,
            wall_ns=lambda: WALL0 + int(round((self.now - 100.0) * 1e9)))

    def at(self, relay, t, data, source=SOURCE):
        self.now = 100.0 + t
        relay.flush()
        relay.handle(data, source)
        relay.flush()

    def feed_positions(self, relay, start, count, period=0.25, with_status=True):
        for i in range(count):
            self.at(relay, start + i * period, POSITION)
            if with_status:
                self.at(relay, start + i * period + 0.01, STATUS)

    def samples(self):
        return [e for e in self.events if e["event"] == "sample"]

    def test_warmup_passes_traffic_and_t0_is_the_first_position_after_it(self):
        relay = self.make(scenario(loss=1.0))
        self.at(relay, 0.0, STATUS)
        self.at(relay, 1.0, POSITION)        # inside the warm-up: forwarded unchanged
        self.at(relay, 2.5, STATUS)          # warm-up over, but not a position
        self.at(relay, 2.75, POSITION)       # t = 0, sample 0 (lost: loss = 1)
        self.assertEqual(self.out.sent, [STATUS, POSITION, STATUS])
        t0 = next(e for e in self.events if e["event"] == "t0")
        self.assertEqual(t0["wall_ns"], WALL0 + 2_750_000_000)
        self.assertEqual([(s["k"], s["outcome"]) for s in self.samples()], [(0, "loss")])

    def test_sample_fates_follow_link_fates_including_inside_outages(self):
        sc = scenario(delay_s=0.05, jitter_s=0.3, loss=0.2, duplicate=0.1,
                      burst_loss={"enter": 0.1, "exit": 0.4}, outages=[[5, 7]])
        relay = self.make(sc, warmup=0.0)
        self.feed_positions(relay, 0.0, 120)
        expected = []
        fates = link_fates(sc.robots[0], sc.seed)
        for k in range(120):
            fate, rel = next(fates), k * 0.25
            if 5 <= rel < 7:
                expected.append((k, "outage", None))
            elif fate.burst:
                expected.append((k, "burst", None))
            elif fate.lost:
                expected.append((k, "loss", None))
            else:
                expected.append((k, "forwarded",
                                 [round(d, 6) for d in fate.delays[:fate.copies]]))
        got = [(s["k"], s["outcome"], s.get("delays_s")) for s in self.samples()]
        self.assertEqual(got, expected)
        outcomes = {o for _, o, _ in got}
        self.assertEqual(outcomes, {"outage", "burst", "loss", "forwarded"})
        self.assertTrue(any(d and len(d) == 2 for _, _, d in got))   # duplication occurred

    def test_outages_and_bursts_also_drop_other_datagrams(self):
        relay = self.make(scenario(outages=[[1, 2]], burst_loss={"enter": 1.0, "exit": 1.0}),
                          warmup=0.0)
        # enter = exit = 1: the burst state alternates bad, good, bad, ... per sample.
        self.feed_positions(relay, 0.0, 12)
        self.assertEqual(relay.counts["other_outage"], 4)    # statuses at 1.01 .. 1.76 s
        self.assertEqual(relay.counts["other_burst"], 4)     # after bad samples outside it
        self.assertEqual(relay.counts["other_forwarded"], 4)
        self.assertEqual(relay.counts["samples_outage"], 4)

    def test_delayed_copies_are_sent_when_due_and_in_due_order(self):
        relay = self.make(scenario(delay_s=0.5), warmup=0.0)
        first, second = frame(33, body=b"\x01" * 4), frame(33, body=b"\x02" * 4)
        self.at(relay, 0.0, first)
        self.at(relay, 0.25, second)
        self.assertEqual(self.out.sent, [])
        self.now = 100.6
        relay.flush()
        self.assertEqual(self.out.sent, [first])
        self.now = 100.8
        relay.flush()
        self.assertEqual(self.out.sent, [first, second])
        self.assertAlmostEqual(relay.summary()["send_late_max_ms"], 100.0, places=3)

    def test_only_the_first_source_is_forwarded(self):
        relay = self.make(scenario(), warmup=0.0)
        self.at(relay, 0.0, POSITION)
        self.at(relay, 0.1, POSITION, source=("127.0.0.1", 6000))
        self.assertEqual(relay.counts["other_sources"], 1)
        self.assertEqual(relay.samples, 1)
        self.assertEqual(len(self.out.sent), 1)

    def test_traffic_after_the_scenario_passes_unchanged_then_relay_finishes(self):
        relay = self.make(scenario(loss=1.0), warmup=0.0)
        self.at(relay, 0.0, POSITION)
        self.at(relay, 60.5, POSITION)
        self.assertEqual(relay.counts["after_end"], 1)
        self.assertEqual(self.out.sent, [POSITION])
        self.assertFalse(relay.finished(100.0 + 64.0, 5.0))
        self.assertTrue(relay.finished(100.0 + 65.0, 5.0))

    def test_rejects_scenarios_live_traffic_cannot_express(self):
        sc = scenario(restarts=[10])
        with self.assertRaises(ValueError):
            relay_tool.select_model(sc)
        with self.assertRaises(ValueError):
            self.make(sc)
        two = parse_scenario({"robots": [{"robot_id": "usv01"}, {"robot_id": "usv02"}]})
        with self.assertRaises(ValueError):
            relay_tool.select_model(two)
        self.assertEqual(relay_tool.select_model(two, "usv02").robot_id, "usv02")


compare_spec = importlib.util.spec_from_file_location("compare_impairment",
                                                      TOOLS / "compare_impairment.py")
compare_tool = importlib.util.module_from_spec(compare_spec)
compare_spec.loader.exec_module(compare_tool)


class TimedSocket(FakeSocket):
    def __init__(self, clock):
        super().__init__()
        self.clock = clock
        self.times = []

    def sendto(self, data, address):
        super().sendto(data, address)
        self.times.append(self.clock())


class CompareTests(unittest.TestCase):
    """A perfectly periodic synthetic live run must score exactly like the model."""

    def run_synthetic(self, sc, warmup=3.0, period=0.25):
        base, self.now = 100.0, 100.0
        out = TimedSocket(lambda: self.now)
        log = []
        relay = relay_tool.ImpairmentRelay(
            out, ("127.0.0.1", 9), sc.robots[0], sc.seed, sc.duration_s, warmup_s=warmup,
            emit=log.append, clock=lambda: self.now,
            wall_ns=lambda: WALL0 + int(round((self.now - base) * 1e9)))
        k = 0
        while True:
            t = base + k * period
            if t > base + warmup + sc.duration_s + 2:
                break
            for when, data in ((t, POSITION), (t + 0.01, STATUS)):
                # deliver anything due before this datagram arrives
                while relay._queue and relay._queue[0][0] <= when:
                    self.now = relay._queue[0][0]
                    relay.flush()
                self.now = when
                relay.handle(data, SOURCE)
                relay.flush()
            k += 1
        t0 = relay.t0
        # A bridge started 10 s before t0 ticks every 0.1 s in phase with the model
        # and numbers samples in arrival order.
        start = t0 - 10.0
        sim = UsvSimulator("usv01", blackout_duration_s=0.0, session_id="live")
        records = [Observation(round(i * 0.1, 9), None)
                   for i in range(int((out.times[-1] - start) / 0.1) + 2)]
        for data, sent in zip(out.sent, out.times):
            if relay_tool.frame_header(data) == (1, 33) and sent >= start:
                wall = WALL0 + int(round((sent - base) * 1e9))
                records.append(Observation(round(sent - start, 9),
                                           sim.sample(sent - start, wall).to_json()))
        records.sort(key=lambda o: (o.time_s, o.payload is None))
        text = "".join(o.to_json() + "\n" for o in records)
        model = sc.robots[0]
        settings = {"event": "scenario", "seed": sc.seed, "duration_s": sc.duration_s,
                    "robot_id": model.robot_id, "delay_s": model.delay_s,
                    "jitter_s": model.jitter_s, "loss": model.loss,
                    "burst_loss": {"enter": model.burst_enter, "exit": model.burst_exit},
                    "duplicate": model.duplicate,
                    "outages": [list(o) for o in model.outages]}
        lines = [json.dumps(settings)] + [json.dumps(e) for e in log]
        return compare_tool.compare(sc, lines, text)

    def test_periodic_live_run_matches_the_virtual_prediction(self):
        # delay 0.03 s keeps every arrival + stale_after at least 20 ms from a 0.1 s
        # tick, so no STALE decision rests on floating-point equality.
        sc = parse_scenario({"seed": 5, "duration_s": 60, "tick_s": 0.1, "stale_after_s": 1.0,
                             "robots": [{"robot_id": "usv01", "rate_hz": 4, "delay_s": 0.03,
                                         "loss": 0.2, "burst_loss": {"enter": 0.05, "exit": 0.3},
                                         "outages": [[10, 13], [30, 30.8], [45, 48]]}]})
        report = self.run_synthetic(sc)
        self.assertEqual(report["fate_agreement"]["differ"], 0)
        self.assertEqual(report["live_state_at_t0"], "HEALTHY")
        self.assertTrue(report["alignment"]["covers_scenario"])
        live, virtual = report["live"], report["virtual"]
        for key in ("detected", "missed", "already_stale", "unexplained_stale"):
            self.assertEqual(live[key], virtual[key], key)
        for a, b in zip(live["outages"], virtual["outages"]):
            for key in ("detection_latency_s", "recovery_latency_s"):
                if b[key] is None:
                    self.assertIsNone(a[key])
                else:
                    self.assertAlmostEqual(a[key], b[key], places=6)
        self.assertGreater(virtual["unexplained_stale"], 0)   # bursts did cause false alarms
        # Without jitter nothing is reordered, so both virtual policies agree, and a
        # perfectly periodic source makes the live-timed model the nominal one.
        self.assertEqual(report["virtual_policy"], "reject")
        self.assertEqual(report["virtual_liveness"], virtual)
        self.assertEqual(report["virtual_timed"], virtual)
        self.assertEqual(report["source_timing"]["max_abs_drift_s"], 0.0)
        self.assertIn("Fate agreement", compare_tool.markdown(report))

    def test_live_timed_model_absorbs_source_drift(self):
        # A source 0.5 % slower than the scenario's 4 Hz drifts ~0.3 s over 60 s, so
        # samples cross outage boundaries differently from the nominal model. Driven
        # by the live send times, the model must reproduce the live run exactly.
        # (Period 0.2513 s keeps every arrival + stale_after >= 0.2 ms from a tick.)
        sc = parse_scenario({"seed": 5, "duration_s": 60, "tick_s": 0.1, "stale_after_s": 1.0,
                             "robots": [{"robot_id": "usv01", "rate_hz": 4, "delay_s": 0.03,
                                         "loss": 0.2, "burst_loss": {"enter": 0.05, "exit": 0.3},
                                         "outages": [[10, 13], [30, 30.8], [45, 48]]}]})
        report = self.run_synthetic(sc, period=0.2513)
        self.assertGreater(report["source_timing"]["max_abs_drift_s"], 0.25)
        live, timed = report["live"], report["virtual_timed"]
        for key in ("detected", "missed", "already_stale", "unexplained_stale"):
            self.assertEqual(live[key], timed[key], key)
        for a, b in zip(live["outages"], timed["outages"]):
            for key in ("detection_latency_s", "recovery_latency_s"):
                if b[key] is None:
                    self.assertIsNone(a[key])
                else:
                    self.assertAlmostEqual(a[key], b[key], places=6)
        self.assertIn("Model, live timing", compare_tool.markdown(report))

    def test_comparison_requires_matching_relay_settings(self):
        sc = scenario()
        valid = {"event": "scenario", "seed": sc.seed,
                 "duration_s": sc.duration_s, "robot_id": "usv01",
                 "delay_s": 0.0, "jitter_s": 0.0, "loss": 0.0,
                 "burst_loss": {"enter": 0.0, "exit": 1.0},
                 "duplicate": 0.0, "outages": []}
        t0 = {"event": "t0", "wall_ns": WALL0}
        sample = {"event": "sample", "k": 0, "rel_s": 0.0,
                  "outcome": "forwarded", "delays_s": [0.0]}
        def records(*entries):
            return [json.dumps(e) for e in entries]

        with self.assertRaisesRegex(ValueError, "no scenario record"):
            compare_tool.compare(sc, records(t0, sample), "")
        with self.assertRaisesRegex(ValueError, "seed"):
            compare_tool.compare(sc, records({**valid, "seed": sc.seed + 1},
                                             t0, sample), "")
        with self.assertRaisesRegex(ValueError, "robot_id"):
            compare_tool.compare(sc, records({**valid, "robot_id": "usv02"},
                                             t0, sample), "")
        with self.assertRaisesRegex(ValueError, "loss"):
            compare_tool.compare(sc, records({**valid, "loss": 0.3},
                                             t0, sample), "")
        with self.assertRaisesRegex(ValueError, "sample index"):
            compare_tool.compare(sc, records(valid, t0, {**sample, "k": 1}), "")
        with self.assertRaisesRegex(ValueError, "more than one scenario"):
            compare_tool.load_relay_log(records(valid, valid, t0, sample))

    def test_relay_log_without_t0_is_rejected(self):
        with self.assertRaises(ValueError):
            compare_tool.load_relay_log(['{"event": "first_datagram", "wall_ns": 1}'])


if __name__ == "__main__":
    unittest.main()
