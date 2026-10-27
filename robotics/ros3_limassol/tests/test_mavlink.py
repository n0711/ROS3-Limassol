import contextlib
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import unittest

from ros3_limassol import mavlink, mavlink_bridge
from ros3_limassol.live_recorder import LiveRecorder
from ros3_limassol.mavlink import (
    MSG_GLOBAL_POSITION_INT, MSG_SYS_STATUS, SUPPORTED_MESSAGES,
    MavlinkParser, MavlinkTelemetryMapper, x25_crc,
)
from ros3_limassol.mavlink_bridge import BridgeSession, serve
from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.replay import run_replay

# Independently encoded by pymavlink 2.4 (common dialect), sysid=1 compid=1
# seq=7: position lat=34.67 lon=33.04 vx=30 vy=40 cm/s hdg=90.00 deg, and
# SYS_STATUS battery_remaining=85. V2_SYS has its zero extensions truncated.
V2_POS = bytes.fromhex("fd1c0000070101210000d2040000e038aa140081b113e8030000"
                       "f40100001e002800000028230d4a")
V2_SYS = bytes.fromhex("fd1f00000701010100000000000000000000000000000000e02e"
                       "ffff000000000000000000000000551c4e")
V1_POS = bytes.fromhex("fe1c07010121d2040000e038aa140081b113e8030000f4010000"
                       "1e0028000000282399cc")
V1_SYS = bytes.fromhex("fe1f070101010000000000000000000000000000e02effff0000"
                       "000000000000000000005559f2")
V2_HEARTBEAT = bytes.fromhex("fd090000070101000000000000000b030004037a40")


def encode(msgid, payload, *, v2=True, sysid=1, compid=1, seq=0,
           signed=False, crc_extra=None):
    """Test-only encoder; the package itself deliberately has none."""
    if crc_extra is None:
        crc_extra = SUPPORTED_MESSAGES[msgid].crc_extra
    if v2:
        payload = payload.rstrip(b"\0") or b"\0"
        header = bytes([len(payload), 1 if signed else 0, 0, seq, sysid, compid,
                        msgid & 0xFF, (msgid >> 8) & 0xFF, msgid >> 16])
    else:
        header = bytes([len(payload), seq, sysid, compid, msgid])
    crc = x25_crc((crc_extra,), x25_crc(header + payload))
    frame = bytes([0xFD if v2 else 0xFE]) + header + payload + struct.pack("<H", crc)
    return frame + (b"\x01" * 13 if signed else b"")


def position(lat=346700000, lon=330400000, vx=30, vy=40, hdg=9000, **kw):
    payload = SUPPORTED_MESSAGES[MSG_GLOBAL_POSITION_INT].layout.pack(
        0, lat, lon, 0, 0, vx, vy, 0, hdg)
    return encode(MSG_GLOBAL_POSITION_INT, payload, **kw)


def battery(remaining=85, **kw):
    payload = SUPPORTED_MESSAGES[MSG_SYS_STATUS].layout.pack(
        0, 0, 0, 0, 12000, -1, 0, 0, 0, 0, 0, 0, remaining)
    return encode(MSG_SYS_STATUS, payload, **kw)


class ParserTests(unittest.TestCase):
    def frames(self, data, parser=None):
        parser = parser or MavlinkParser()
        return list(parser.feed(data)), parser

    def test_decodes_independently_encoded_v1_and_v2_frames(self):
        frames, parser = self.frames(V2_POS + V2_SYS + V1_POS + V1_SYS + V2_HEARTBEAT)
        self.assertEqual([(f.version, f.message_id) for f in frames],
                         [(2, 33), (2, 1), (1, 33), (1, 1)])
        self.assertEqual(frames[0].decode(), (1234, 346700000, 330400000, 1000,
                                              500, 30, 40, 0, 9000))
        self.assertEqual(frames[1].decode()[-1], 85)
        self.assertEqual(frames[1].decode(), frames[3].decode())
        self.assertEqual((frames[0].sequence, frames[0].system_id), (7, 1))
        self.assertEqual(parser.stats["unsupported_messages"], 1)

    def test_byte_at_a_time_matches_whole_buffer(self):
        parser = MavlinkParser()
        frames = [f for byte in V2_SYS + V2_POS for f in parser.feed(bytes([byte]))]
        self.assertEqual([f.message_id for f in frames], [1, 33])

    def test_bad_checksum_resynchronises_on_next_frame(self):
        corrupt = bytearray(V2_POS)
        corrupt[12] ^= 0xFF
        frames, parser = self.frames(b"junk\x00" + bytes(corrupt) + V1_POS)
        self.assertEqual([f.version for f in frames], [1])
        self.assertEqual(parser.stats["crc_errors"], 1)
        self.assertGreater(parser.stats["bytes_discarded"], 5)

    def test_signed_frames_are_skipped_not_trusted(self):
        frames, parser = self.frames(position(signed=True) + position())
        self.assertEqual(len(frames), 1)
        self.assertEqual(parser.stats["signed_skipped"], 1)

    def test_v1_frame_with_wrong_length_is_rejected(self):
        frames, parser = self.frames(encode(MSG_GLOBAL_POSITION_INT, b"\0" * 20, v2=False))
        self.assertEqual(frames, [])
        self.assertEqual(parser.stats["bad_length"], 1)

    def test_rejects_non_bytes(self):
        with self.assertRaises(TypeError):
            list(MavlinkParser().feed("fd00"))

    def test_package_has_no_send_path(self):
        for module in (mavlink, mavlink_bridge):
            source = Path(module.__file__).read_text(encoding="utf-8")
            for forbidden in ("sendto(", ".send(", "sendall("):
                self.assertNotIn(forbidden, source, module.__name__)


class MapperTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.mapper = MavlinkTelemetryMapper(
            "usv01", 1, clock=lambda: self.now, wall_clock_ns=lambda: 42)

    def observe(self, data):
        return [self.mapper.observe(f) for f in MavlinkParser().feed(data)]

    def test_maps_golden_frames_to_schema_v1(self):
        _, sample = self.observe(V2_SYS + V2_POS)
        self.assertEqual(
            (sample.latitude_deg, sample.longitude_deg, sample.heading_deg,
             sample.speed_m_s, sample.battery_pct, sample.sequence, sample.timestamp_ns),
            (34.67, 33.04, 90.0, 0.5, 85.0, 0, 42))
        self.assertRegex(sample.session_id, r"^mav1_[0-9a-f]{16}$")
        self.assertEqual(self.observe(V1_POS)[0].sequence, 1)
        self.assertEqual(self.mapper.stats["emitted"], 2)

    def test_withholds_sample_without_known_fresh_battery(self):
        self.assertEqual(self.observe(V2_POS), [None])
        self.observe(battery(-1) + position())
        self.assertEqual(self.mapper.stats["battery_unknown"], 2)
        self.observe(battery(50))
        self.now += 5.5
        self.assertEqual(self.observe(position()), [None])
        self.assertEqual(self.mapper.stats["battery_stale"], 1)

    def test_withholds_unknown_or_invalid_heading_and_speed(self):
        self.observe(battery())
        self.assertEqual(self.observe(position(hdg=0xFFFF)), [None])
        self.assertEqual(self.observe(position(hdg=36000)), [None])
        self.assertEqual(self.observe(position(vx=10001)), [None])
        self.assertEqual(self.mapper.stats["heading_unknown"], 1)
        self.assertEqual(self.mapper.stats["out_of_schema"], 2)
        self.assertEqual(self.observe(position(hdg=35999))[0].heading_deg, 359.99)

    def test_ignores_other_systems_and_components(self):
        mapper = MavlinkTelemetryMapper("usv01", 1, 1)
        for data in (battery(sysid=2), battery(compid=191)):
            for frame in MavlinkParser().feed(data):
                self.assertIsNone(mapper.observe(frame))
        self.assertEqual(mapper.stats["other_source"], 2)

    def test_validates_configuration(self):
        for kwargs in ({"system_id": 256}, {"system_id": None},
                       {"component_id": -1}, {"battery_max_age_s": 0}):
            with self.assertRaises(ValueError):
                MavlinkTelemetryMapper("usv01", **kwargs)
        with self.assertRaises(ValueError):
            MavlinkTelemetryMapper("USV")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = lambda: self.now

    def session(self, recorder=None):
        mapper = MavlinkTelemetryMapper("usv01", 1, clock=self.clock,
                                        battery_max_age_s=60)
        return BridgeSession(mapper, LinkMonitor(stale_after_s=1.0),
                             recorder=recorder, clock=self.clock)

    def test_outage_and_recovery_are_recorded_and_replayable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mav.jsonl"
            with LiveRecorder(path, clock=self.clock) as recorder:
                session = self.session(recorder)
                states = [e["state"] for e in session.tick()]
                self.now += 0.1
                states += [e["state"] for e in session.handle_datagram(V2_SYS + V2_POS)]
                self.now += 1.5
                states += [e["state"] for e in session.tick()]
                self.now += 0.2
                states += [e["state"] for e in session.handle_datagram(V1_POS)]
                summary = session.summary()
            self.assertEqual(states, ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
            self.assertEqual((summary["accepted"], summary["rejected"]), (2, 0))
            self.assertEqual(summary["mavlink"]["frames"], 3)
            text = path.read_text(encoding="utf-8")
            events = list(run_replay(io.StringIO(text), stale_after_s=1.0))
            self.assertEqual([e["state"] for e in events[:-1]],
                             ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
            self.assertEqual(events[-1]["accepted"], 2)

    def test_serve_reads_real_udp_datagrams(self):
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(receiver.close)
        self.addCleanup(sender.close)
        receiver.bind(("127.0.0.1", 0))
        sender.sendto(V2_SYS, receiver.getsockname())
        sender.sendto(V2_POS, receiver.getsockname())
        session = BridgeSession(MavlinkTelemetryMapper("usv01", 1),
                                LinkMonitor(stale_after_s=5.0))
        events = []
        serve(receiver, session, tick_s=0.05, duration_s=0.5, emit=events.append)
        self.assertEqual([e["state"] for e in events], ["WAITING", "HEALTHY"])
        self.assertEqual(session.summary()["accepted"], 1)

    def test_cli_emits_summary_and_rejects_bad_options(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mavlink_bridge.main(["--listen", "127.0.0.1:0", "--duration", "0.2", "--tick", "0.05"])
        lines = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(lines[0]["state"], "WAITING")
        self.assertEqual(lines[-1]["event"], "summary")
        self.assertEqual(lines[-1]["mavlink"]["frames"], 0)
        for bad in (["--listen", "nohost"], ["--system-id", "300"], ["--tick", "0"],
                    ["--duration", "-1"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                mavlink_bridge.main(["--listen", "127.0.0.1:0", *bad]
                                    if bad[0] != "--listen" else bad)


if __name__ == "__main__":
    unittest.main()
