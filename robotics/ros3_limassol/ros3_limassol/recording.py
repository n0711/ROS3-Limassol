# SPDX-License-Identifier: Apache-2.0
"""Bounded JSON Lines observations, including ticks with no received telemetry."""

from dataclasses import asdict, dataclass
import json

from .telemetry import MAX_PAYLOAD_BYTES, finite_number

MAX_RECORD_BYTES = 32768
MAX_RECORDS = 1_000_000


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate recording key: {key}")
        value[key] = item
    return value


def _reject_constant(value):
    raise ValueError(f"invalid recording number: {value}")


@dataclass(frozen=True)
class Observation:
    """Receiver-relative seconds and raw JSON, or None for an observation tick.

    Payload validation belongs to LinkMonitor so malformed telemetry remains
    reproducible. An invalid recording envelope is a separate input error.
    """

    time_s: float
    payload: str | None
    record_version: int = 1

    def __post_init__(self):
        if type(self.record_version) is not int or self.record_version != 1:
            raise ValueError("record_version must be integer 1")
        if finite_number(self.time_s, "time_s") < 0:
            raise ValueError("time_s must be nonnegative")
        if self.payload is not None:
            if not isinstance(self.payload, str):
                raise ValueError("payload must be JSON text or null")
            try:
                if (len(self.payload) > MAX_PAYLOAD_BYTES or
                        len(self.payload.encode("utf-8")) > MAX_PAYLOAD_BYTES):
                    raise ValueError("recorded payload exceeds 4096 bytes")
            except UnicodeError as exc:
                raise ValueError("recorded payload must be UTF-8 text") from exc

    def to_json(self):
        return json.dumps(asdict(self), allow_nan=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, str) or len(raw) > MAX_RECORD_BYTES:
            raise ValueError("recording line exceeds 32768 bytes or is not text")
        try:
            if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
                raise ValueError("recording line exceeds 32768 bytes")
            value = json.loads(raw, object_pairs_hook=_unique_object,
                               parse_constant=_reject_constant)
        except (UnicodeError, RecursionError) as exc:
            raise ValueError("invalid recording JSON") from exc
        if not isinstance(value, dict) or set(value) != {
                "record_version", "time_s", "payload"}:
            raise ValueError("recording fields must exactly match version 1")
        return cls(**value)


def read_observations(stream):
    """Read a text stream with bounded line lengths, retaining no full trace."""
    previous = None
    for index in range(MAX_RECORDS + 1):
        try:
            line = stream.readline(MAX_RECORD_BYTES + 1)
        except UnicodeError as exc:
            raise ValueError(f"line {index + 1}: recording must be UTF-8 text") from exc
        if not line:
            return
        if index == MAX_RECORDS:
            raise ValueError(f"recording exceeds {MAX_RECORDS} observations")
        try:
            record = Observation.from_json(line)
            if previous is not None and record.time_s < previous:
                raise ValueError("receiver time moved backwards")
        except ValueError as exc:
            raise ValueError(f"line {index + 1}: {exc}") from exc
        previous = record.time_s
        yield record
