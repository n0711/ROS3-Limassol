import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol import evidence, replay
from ros3_limassol.mavlink import MavlinkTelemetryMapper
from ros3_limassol.mavlink_bridge import BridgeSession
from ros3_limassol.monitor import LinkMonitor
from ros3_limassol.recording import Observation
from test_telemetry import packet

# Sequences 0..9 sent every 0.1 s; 3 and 7 arrive 0.25 s late (after 4 and 8),
# and 5 arrives twice. Then silence from 1.0 s with ticks every 0.1 s.
ARRIVALS = [(0.0, 0), (0.1, 1), (0.2, 2), (0.4, 4), (0.45, 3), (0.5, 5), (0.55, 5),
            (0.6, 6), (0.8, 8), (0.85, 7), (0.9, 9)]


def recording_text():
    rows = [Observation(t, packet(sequence=s).to_json()) for t, s in ARRIVALS]
    rows += [Observation(round(1.0 + i / 10, 6), None) for i in range(25)]
    return "".join(r.to_json() + "\n" for r in rows)


class PolicyPlumbingTests(unittest.TestCase):
    def report(self, policy):
        return evidence.build_evidence(io.BytesIO(recording_text().encode()),
                                       late_samples=policy)

    def test_evidence_reports_policy_and_counts(self):
        strict, late = self.report("reject"), self.report("liveness")
        self.assertEqual((strict["accepted"], strict["rejected"], strict["late_accepted"]),
                         (8, 3, 0))
        self.assertEqual(strict["rejection_reasons"], {"duplicate_or_out_of_order": 3})
        self.assertEqual((late["accepted"], late["rejected"], late["late_accepted"]),
                         (10, 1, 2))
        self.assertEqual((strict["late_samples"], late["late_samples"]),
                         ("reject", "liveness"))
        self.assertEqual(late["last_sequence"], 9)
        self.assertEqual(late["recording_sha256"], strict["recording_sha256"])

    def test_replay_and_cli_accept_the_policy(self):
        events = list(replay.run_replay(io.StringIO(recording_text()),
                                        late_samples="liveness"))
        self.assertEqual(events[-1]["accepted"], 10)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "late.jsonl"
            path.write_text(recording_text(), encoding="utf-8")
            for module, args in ((replay, ["--json"]), (evidence, [])):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    module.main([str(path), "--late-samples", "liveness", *args])
                last = json.loads(out.getvalue().splitlines()[-1]
                                  if module is replay else out.getvalue())
                self.assertEqual(last["accepted"], 10)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                replay.main([str(path), "--late-samples", "accept"])

    def test_bridge_summary_reports_policy(self):
        now = [0.0]
        session = BridgeSession(MavlinkTelemetryMapper("usv01", 1),
                                LinkMonitor(late_samples="liveness"),
                                clock=lambda: now[0])
        summary = session.summary()
        self.assertEqual((summary["late_samples"], summary["late_accepted"]), ("liveness", 0))


if __name__ == "__main__":
    unittest.main()
