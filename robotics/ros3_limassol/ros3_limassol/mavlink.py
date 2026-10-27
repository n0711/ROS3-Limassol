# SPDX-License-Identifier: Apache-2.0
"""Receive-only MAVLink framing and an explicit mapping to telemetry schema v1.

Standard library only. This module decodes bytes that have already been
received; it contains no encoder, no socket and no way to send MAVLink, so it
cannot command a vehicle. Only the messages listed in ``SUPPORTED_MESSAGES``
are checksum-verified and decoded; every other frame is skipped and counted.

Mapping (see docs/MAVLINK.md for units and limits):

- GLOBAL_POSITION_INT (33) ``lat``/``lon`` degE7 -> ``latitude_deg``/``longitude_deg``
- GLOBAL_POSITION_INT ``hdg`` cdeg -> ``heading_deg`` (65535 = unknown, no sample)
- GLOBAL_POSITION_INT ``vx``/``vy`` cm/s -> ``speed_m_s`` (horizontal ground speed)
- latest SYS_STATUS (1) ``battery_remaining`` % -> ``battery_pct`` (-1 = unknown)

One telemetry sample is produced per accepted GLOBAL_POSITION_INT. The adapter
assigns ``session_id`` and a strictly increasing ``sequence``; ``timestamp_ns``
is the receiver's wall clock, because MAVLink ``time_boot_ms`` is not Unix time.
"""

from dataclasses import dataclass
import math
import struct
import time
import uuid

from .telemetry import Telemetry, finite_number, validate_robot_id

MAGIC_V1 = 0xFE
MAGIC_V2 = 0xFD
V1_HEADER = 5   # len, seq, sysid, compid, msgid
V2_HEADER = 9   # len, incompat, compat, seq, sysid, compid, msgid (3 bytes)
SIGNATURE_LEN = 13
INCOMPAT_SIGNED = 0x01
MAX_FRAME = 1 + V2_HEADER + 255 + 2 + SIGNATURE_LEN
MAX_BUFFER = 4 * MAX_FRAME

MSG_SYS_STATUS = 1
MSG_GLOBAL_POSITION_INT = 33


@dataclass(frozen=True)
class MessageSpec:
    name: str
    crc_extra: int
    base_len: int      # MAVLink 1 length (no extension fields)
    full_len: int      # MAVLink 2 maximum length (with extension fields)
    layout: struct.Struct  # base fields in wire order


SUPPORTED_MESSAGES = {
    MSG_SYS_STATUS: MessageSpec(
        "SYS_STATUS", 124, 31, 43, struct.Struct("<IIIHHhHHHHHHb")),
    MSG_GLOBAL_POSITION_INT: MessageSpec(
        "GLOBAL_POSITION_INT", 104, 28, 28, struct.Struct("<IiiiihhhH")),
}


def x25_crc(data, crc=0xFFFF):
    """MAVLink CRC-16/MCRF4XX over ``data``."""
    for byte in data:
        tmp = byte ^ (crc & 0xFF)
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    version: int
    sequence: int
    system_id: int
    component_id: int
    message_id: int
    payload: bytes  # zero-padded to the message's full length

    def decode(self):
        spec = SUPPORTED_MESSAGES[self.message_id]
        return spec.layout.unpack_from(self.payload)


class MavlinkParser:
    """Incremental, bounded MAVLink v1/v2 stream parser.

    ``feed`` accepts arbitrary byte chunks (datagrams or stream reads) and
    yields checksum-verified frames of supported messages. Bad checksums drop
    only the magic byte and resynchronise. Signed MAVLink 2 frames are skipped
    and counted: signatures are not verified, so their origin is not
    authenticated and they are not decoded.
    """

    def __init__(self):
        self._buffer = bytearray()
        self.stats = {
            "frames": 0, "crc_errors": 0, "unsupported_messages": 0,
            "signed_skipped": 0, "bad_length": 0, "bytes_discarded": 0,
        }

    def _discard(self, count):
        del self._buffer[:count]
        self.stats["bytes_discarded"] += count

    def feed(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("MAVLink input must be bytes")
        self._buffer.extend(data)
        while True:
            frame = self._next_frame()
            if frame is None:
                break
            if frame is not False:
                yield frame
        if len(self._buffer) > MAX_BUFFER:
            self._discard(len(self._buffer) - MAX_BUFFER)

    def _next_frame(self):
        """Return a Frame, False for a consumed non-frame, or None if waiting."""
        buf = self._buffer
        start = next((i for i, b in enumerate(buf) if b in (MAGIC_V1, MAGIC_V2)), None)
        if start is None:
            if buf:
                self._discard(len(buf))
            return None
        if start:
            self._discard(start)
        if len(buf) < 2:
            return None
        v2 = buf[0] == MAGIC_V2
        header = V2_HEADER if v2 else V1_HEADER
        if len(buf) < 1 + header:
            return None
        length = buf[1]
        signed = v2 and bool(buf[2] & INCOMPAT_SIGNED)
        total = 1 + header + length + 2 + (SIGNATURE_LEN if signed else 0)
        if len(buf) < total:
            return None
        if v2:
            seq, sysid, compid = buf[4], buf[5], buf[6]
            msgid = buf[7] | (buf[8] << 8) | (buf[9] << 16)
        else:
            seq, sysid, compid, msgid = buf[2], buf[3], buf[4], buf[5]
        spec = SUPPORTED_MESSAGES.get(msgid)
        if spec is None:
            # Cannot verify without its CRC_EXTRA; skip by declared length.
            del buf[:total]
            self.stats["unsupported_messages"] += 1
            return False
        end = 1 + header + length
        crc = x25_crc(buf[1:end])
        crc = x25_crc((spec.crc_extra,), crc)
        if crc != (buf[end] | (buf[end + 1] << 8)):
            self.stats["crc_errors"] += 1
            self._discard(1)
            return False
        if signed:
            del buf[:total]
            self.stats["signed_skipped"] += 1
            return False
        if (length != spec.base_len) if not v2 else not 1 <= length <= spec.full_len:
            del buf[:total]
            self.stats["bad_length"] += 1
            return False
        payload = bytes(buf[1 + header:end]).ljust(spec.full_len, b"\0")
        del buf[:total]
        self.stats["frames"] += 1
        return Frame(2 if v2 else 1, seq, sysid, compid, msgid, payload)


class MavlinkTelemetryMapper:
    """Map frames from one MAVLink system to schema-v1 telemetry.

    ``clock`` must be monotonic (battery age); ``wall_clock_ns`` supplies
    ``timestamp_ns``. A sample is withheld, and counted, when heading or
    battery is unknown, the battery report is older than
    ``battery_max_age_s``, or a mapped value falls outside schema v1.
    """

    def __init__(self, robot_id, system_id=1, component_id=None, *,
                 session_id=None, battery_max_age_s=5.0,
                 clock=time.monotonic, wall_clock_ns=time.time_ns):
        self.robot_id = validate_robot_id(robot_id)
        for name, value in (("system_id", system_id), ("component_id", component_id)):
            if value is not None and (type(value) is not int or not 0 <= value <= 255):
                raise ValueError(f"{name} must be an integer in [0, 255]")
        if system_id is None:
            raise ValueError("system_id is required")
        self.system_id = system_id
        self.component_id = component_id
        self.battery_max_age_s = finite_number(battery_max_age_s, "battery_max_age_s")
        if self.battery_max_age_s <= 0:
            raise ValueError("battery_max_age_s must be positive")
        self.session_id = session_id or f"mav{system_id}_{uuid.uuid4().hex[:16]}"
        self._clock = clock
        self._wall_clock_ns = wall_clock_ns
        self._sequence = 0
        self._battery = None  # (percent or None, receiver monotonic time)
        self.stats = {
            "emitted": 0, "other_source": 0, "heading_unknown": 0,
            "battery_unknown": 0, "battery_stale": 0, "out_of_schema": 0,
        }

    def observe(self, frame):
        if frame.system_id != self.system_id or (
                self.component_id is not None and frame.component_id != self.component_id):
            self.stats["other_source"] += 1
            return None
        fields = frame.decode()
        if frame.message_id == MSG_SYS_STATUS:
            remaining = fields[-1]
            self._battery = (None if remaining < 0 else remaining, self._clock())
            return None
        if frame.message_id != MSG_GLOBAL_POSITION_INT:
            return None
        _, lat, lon, _, _, vx, vy, _, hdg = fields
        if hdg == 0xFFFF:
            self.stats["heading_unknown"] += 1
            return None
        if self._battery is None or self._battery[0] is None:
            self.stats["battery_unknown"] += 1
            return None
        if self._clock() - self._battery[1] > self.battery_max_age_s:
            self.stats["battery_stale"] += 1
            return None
        try:
            sample = Telemetry(
                schema_version=1, robot_id=self.robot_id,
                session_id=self.session_id, sequence=self._sequence,
                timestamp_ns=self._wall_clock_ns(),
                latitude_deg=lat / 1e7, longitude_deg=lon / 1e7,
                heading_deg=hdg / 100.0,  # >= 36000 is rejected, not wrapped
                speed_m_s=math.hypot(vx, vy) / 100.0,
                battery_pct=float(self._battery[0]),
            )
        except ValueError:
            self.stats["out_of_schema"] += 1
            return None
        self._sequence += 1
        self.stats["emitted"] += 1
        return sample
