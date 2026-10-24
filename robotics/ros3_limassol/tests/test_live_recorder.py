import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.live_recorder import (
    LiveRecorder, RecordingFullError, UnrecordablePayloadError,
)
from ros3_limassol.recording import MAX_RECORDS, read_observations
from ros3_limassol.replay import run_replay
from test_telemetry import packet


class LiveRecorderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "live.jsonl"
        self.now = 1000.0

    def recorder(self, **kwargs):
        result = LiveRecorder(self.path, clock=lambda: self.now, **kwargs)
        self.addCleanup(result.close)
        return result

    def events(self, **kwargs):
        return list(run_replay(io.StringIO(self.path.read_text(encoding="utf-8")), **kwargs))

    def test_live_arrivals_and_silence_replay_outage_and_recovery(self):
        recorder = self.recorder()
        self.now += 0.25
        recorder.receive(packet(timestamp_ns=999_999).to_json())
        self.now += 1.0
        recorder.tick()
        self.now += 0.25
        recorder.receive(packet(sequence=1, timestamp_ns=1).to_json())
        recorder.close()
        events = self.events()
        self.assertEqual([x["state"] for x in events[:-1]],
                         ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
        self.assertEqual([x["time_s"] for x in events[:-1]], [0, 0.25, 1.25, 1.5])
        self.assertEqual(events[-1]["accepted"], 2)
        self.assertEqual(events[-1]["rejected"], 0)

    def test_fully_silent_recording_preserves_waiting(self):
        recorder = self.recorder()
        for value in (1000.5, 1001.5, 1002.0):
            self.now = value
            recorder.tick()
        self.assertEqual(recorder.records, 4)
        self.assertEqual(self.events()[-1]["state"], "WAITING")
        self.assertEqual(self.events()[-1]["time_s"], 2)

    def test_malformed_duplicate_wrong_robot_and_retired_session_are_preserved(self):
        recorder = self.recorder()
        payloads = [packet(sequence=1).to_json(), packet(sequence=1).to_json(),
                    packet(robot_id="other").to_json(), "{", '{"x":1,"x":2}',
                    packet(session_id="restart").to_json(), packet(sequence=2).to_json()]
        for raw in payloads:
            recorder.receive(raw)
        self.now += 1
        recorder.tick()
        events = self.events()
        self.assertEqual(events[-1]["state"], "STALE")
        self.assertEqual(events[-1]["accepted"], 2)
        self.assertEqual(events[-1]["rejected"], 5)
        self.assertEqual(events[-1]["last_rejection"], "retired_session")
        with self.path.open(encoding="utf-8") as stream:
            self.assertEqual([x.payload for x in read_observations(stream)][1:-1], payloads)

    def test_new_timeout_can_be_applied_to_live_recording(self):
        recorder = self.recorder()
        recorder.receive(packet().to_json())
        self.now += 1.5
        recorder.tick()
        self.assertEqual(self.events()[-1]["state"], "STALE")
        self.assertEqual(self.events(stale_after_s=2)[-1]["state"], "HEALTHY")

    def test_existing_file_is_never_truncated(self):
        self.path.write_text("keep me", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.recorder()
        self.assertEqual(self.path.read_text(), "keep me")

    def test_configuration_is_checked_before_creating_a_file(self):
        for value in (0, -1, True, 1.5, MAX_RECORDS + 1):
            with self.subTest(limit=value), self.assertRaises(ValueError):
                self.recorder(max_records=value)
            self.assertFalse(self.path.exists())
        for value in (float("nan"), float("inf"), True):
            with self.subTest(clock=value), self.assertRaises(ValueError):
                LiveRecorder(self.path, clock=lambda: value)
            self.assertFalse(self.path.exists())

    def test_limit_counts_initial_tick_and_leaves_replayable_prefix(self):
        recorder = self.recorder(max_records=3)
        recorder.receive(packet().to_json())
        self.now += 1
        recorder.tick()
        before = self.path.read_bytes()
        with self.assertRaises(RecordingFullError):
            recorder.receive(packet(sequence=1).to_json())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(recorder.records, 3)
        self.assertEqual(self.events()[-1]["state"], "STALE")

    def test_unrecordable_payload_is_reported_without_breaking_silence_ticks(self):
        recorder = self.recorder()
        for raw in (None, b"{}", 7, "x" * 4097, "é" * 2049, "\ud800"):
            with self.subTest(raw=repr(raw)[:40]), self.assertRaises(UnrecordablePayloadError):
                recorder.receive(raw)
        self.assertEqual(recorder.records, 1)
        recorder.receive("not telemetry")
        self.now += 1
        recorder.tick()
        self.assertEqual(self.events()[-1]["rejected"], 1)

    def test_nonfinite_and_backwards_clocks_never_append_corrupt_records(self):
        recorder = self.recorder()
        self.now += 1
        recorder.tick()
        before = self.path.read_bytes()
        for value in (1000.5, 999.0, float("nan"), float("inf"), True):
            self.now = value
            with self.subTest(clock=value), self.assertRaises(ValueError):
                recorder.tick()
            self.assertEqual(self.path.read_bytes(), before)
        self.now = 1002
        recorder.tick()
        self.assertEqual(self.events()[-1]["time_s"], 2)

    def test_context_manager_closes_on_error_and_close_adds_no_tick(self):
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with LiveRecorder(self.path, clock=lambda: self.now) as recorder:
                recorder.receive(packet().to_json())
                raise RuntimeError("stop")
        self.assertTrue(recorder.closed)
        recorder.close()
        self.assertEqual(len(self.path.read_text().splitlines()), 2)
        with self.assertRaisesRegex(ValueError, "closed"):
            recorder.tick()

    def test_written_record_is_visible_before_close_and_has_relative_time(self):
        recorder = self.recorder()
        self.now += 0.5
        recorder.receive(packet().to_json())
        records = [json.loads(x) for x in self.path.read_text().splitlines()]
        self.assertEqual([x["time_s"] for x in records], [0.0, 0.5])
        self.assertTrue(all(x["record_version"] == 1 for x in records))
