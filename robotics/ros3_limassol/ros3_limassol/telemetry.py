# SPDX-License-Identifier: Apache-2.0
"""Small, strict telemetry contract. This module has no ROS dependencies."""

from dataclasses import asdict, dataclass, fields
import json
import math
import re

MAX_PAYLOAD_BYTES = 4096
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")
SESSION_PATTERN = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


def finite_number(value, name):
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def validate_robot_id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError("robot_id must match [a-z][a-z0-9_]{0,31}")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"invalid JSON number: {value}")


@dataclass(frozen=True)
class Telemetry:
    schema_version: int
    robot_id: str
    session_id: str
    sequence: int
    timestamp_ns: int
    latitude_deg: float
    longitude_deg: float
    heading_deg: float
    speed_m_s: float
    battery_pct: float

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("schema_version must be integer 1")
        validate_robot_id(self.robot_id)
        if not isinstance(self.session_id, str) or not SESSION_PATTERN.fullmatch(
            self.session_id
        ):
            raise ValueError("invalid session_id")
        for name in ("sequence", "timestamp_ns"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 2**63 - 1:
                raise ValueError(f"{name} must be an integer in [0, 2^63-1]")
        limits = {
            "latitude_deg": (-90, 90),
            "longitude_deg": (-180, 180),
            "heading_deg": (0, 360),
            "speed_m_s": (0, 100),
            "battery_pct": (0, 100),
        }
        for name, (lower, upper) in limits.items():
            value = finite_number(getattr(self, name), name)
            if not lower <= value <= upper:
                raise ValueError(f"{name} outside [{lower}, {upper}]")
        if self.heading_deg == 360:
            raise ValueError("heading_deg must be less than 360")

    def to_json(self):
        return json.dumps(asdict(self), allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, str):
            raise ValueError("telemetry must be JSON text")
        # Check characters first to avoid encoding an arbitrarily large input.
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ValueError("telemetry exceeds 4096 bytes")
        try:
            if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                raise ValueError("telemetry exceeds 4096 bytes")
            data = json.loads(
                raw, object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, RecursionError) as exc:
            raise ValueError("invalid telemetry JSON") from exc
        required = {field.name for field in fields(cls)}
        if not isinstance(data, dict) or set(data) != required:
            raise ValueError("telemetry fields must exactly match schema v1")
        return cls(**data)
