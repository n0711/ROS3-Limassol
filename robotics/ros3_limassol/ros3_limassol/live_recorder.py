# SPDX-License-Identifier: Apache-2.0
"""Write replayable live observations using one receiver monotonic clock."""

from pathlib import Path
from threading import Lock
import time

from .recording import MAX_RECORDS, Observation
from .telemetry import finite_number


class RecordingFullError(ValueError):
    """The recording reached its configured observation limit."""


class UnrecordablePayloadError(ValueError):
    """A payload cannot be represented within the version-1 recording bounds."""


class LiveRecorder:
    """Create a new JSONL file; record arrivals and independent silence ticks.

    The injected clock must have the same semantics as ``time.monotonic``.
    Each successful call flushes one complete observation. Callers schedule
    ``tick`` independently of ``receive``; the writer starts no background task.
    Flushing is not an fsync or a power-loss durability guarantee.
    """

    def __init__(self, output_path, *, clock=time.monotonic,
                 max_records=MAX_RECORDS):
        if type(max_records) is not int or not 1 <= max_records <= MAX_RECORDS:
            raise ValueError(f"max_records must be an integer in [1, {MAX_RECORDS}]")
        self._clock = clock
        self._started = finite_number(clock(), "receiver time")
        self._last_time = 0.0
        self._lock = Lock()
        self.max_records = max_records
        self.records = 0
        self._stream = Path(output_path).open("x", encoding="utf-8", newline="\n")
        try:
            # Preserve WAITING even when no telemetry ever arrives.
            self._append(Observation(0.0, None))
        except BaseException:
            self._stream.close()
            raise

    @property
    def closed(self):
        return self._stream.closed

    def _append(self, observation):
        if self._stream.closed:
            raise ValueError("recording is closed")
        if self.records >= self.max_records:
            raise RecordingFullError(
                f"recording reached {self.max_records} observations; use a new file"
            )
        self._stream.write(observation.to_json() + "\n")
        self._stream.flush()
        self._last_time = observation.time_s
        self.records += 1

    def _record(self, payload):
        # Sample the clock inside the lock so parallel callbacks cannot write
        # observations in a different order from their receiver timestamps.
        with self._lock:
            elapsed = finite_number(
                finite_number(self._clock(), "receiver time") - self._started,
                "elapsed receiver time",
            )
            if elapsed < self._last_time:
                raise ValueError("receiver monotonic clock moved backwards")
            self._append(Observation(elapsed, payload))

    def receive(self, payload):
        """Record raw bounded text, including malformed or rejected telemetry."""
        try:
            if not isinstance(payload, str):
                raise ValueError("received payload must be text")
            Observation(0.0, payload)
        except ValueError as exc:
            raise UnrecordablePayloadError(str(exc)) from exc
        self._record(payload)

    def tick(self):
        """Record an evaluation instant even when the source is silent."""
        self._record(None)

    def close(self):
        """Close without inventing a final observation at shutdown."""
        with self._lock:
            self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
