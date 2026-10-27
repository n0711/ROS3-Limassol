"""Offline manifest verification does not establish real simulation execution."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from ros3_limassol.demo import run_demo
from ros3_limassol.camera_receiver_evidence import CameraReceiverEvidence
from test_vlm_diagnostics import sample_png
from ros3_limassol.simready_evidence import (
    build_simready_evidence, main, validate_manifest, validate_camera_report,
)

ASSET = b"#usda 1.0\n"  # Synthetic fixture, not a published NVIDIA asset.


def manifest():
    return {
        "experiment_version": 1,
        "experiment_id": "unit_case_1",
        "simulator": "isaac-sim",
        "ros_distro": "humble",
        "robot_id": "usv01",
        "asset_dataset": "nvidia/simready-assets",
        "asset_revision": "a" * 40,
        "asset_path": "example/fixture.usda",
        "asset_license": "CC-BY-4.0",
        "asset_sha256": hashlib.sha256(ASSET).hexdigest(),
        "camera_topic": "/camera/image_raw/compressed",
        "telemetry_topic": "/limassol/usv01/telemetry",
    }


def raw_manifest(data=None):
    return json.dumps(manifest() if data is None else data).encode("utf-8")


def trace():
    stream = io.StringIO()
    list(run_demo(record_to=stream))
    return stream.getvalue().encode("utf-8")


class SimreadyEvidenceTests(unittest.TestCase):
    def test_asset_and_receiver_recording_hashes_verified(self):
        report = build_simready_evidence(raw_manifest(), io.BytesIO(trace()), io.BytesIO(ASSET))
        self.assertTrue(report["asset"]["local_bytes_sha256_verified"])
        self.assertEqual(report["receiver_evidence"]["accepted"], 51)
        self.assertEqual(report["receiver_evidence"]["observed_stale_to_healthy_recoveries"], 1)
        self.assertEqual(report["receiver_evidence"]["recording_sha256"], hashlib.sha256(trace()).hexdigest())
        self.assertFalse(report["claims"]["simulator_executed_verified"])
        self.assertFalse(report["claims"]["usd_asset_loaded_in_scene_verified"])
        self.assertFalse(report["claims"]["camera_frame_capture_alignment_verified"])

    def test_unchecked_asset_never_marked_verified(self):
        report = build_simready_evidence(raw_manifest(), io.BytesIO(trace()))
        self.assertFalse(report["asset"]["local_bytes_sha256_verified"])

    def test_bind_camera_probe_without_claiming_simulator_origin(self):
        receiver = CameraReceiverEvidence(max_frames=2)
        receiver.observe(sample_png(), "png", 100.0)
        receiver.observe(b"\x00\x00\x00\x01", "h264", 100.1)
        raw = json.dumps(receiver.report(reason="max_frames")).encode("utf-8")
        report = build_simready_evidence(
            raw_manifest(), io.BytesIO(trace()), camera_report_bytes=raw,
        )
        camera = report["camera_receiver_evidence"]
        self.assertEqual(camera["topic"], manifest()["camera_topic"])
        self.assertEqual(camera["report_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(camera["received_frames"], 2)
        self.assertEqual(camera["compatible_jpeg_png_headers"], 1)
        self.assertEqual(camera["unsupported_h264_hevc_frames"], 1)
        self.assertFalse(camera["simulator_origin_verified"])
        self.assertFalse(camera["ros2_delivery_independently_verified"])
        self.assertFalse(report["claims"]["simulator_executed_verified"])

    def test_camera_topic_mismatch_and_inflated_claims_fail(self):
        receiver = CameraReceiverEvidence(max_frames=1)
        receiver.observe(sample_png(), "png", 5.0)
        original = receiver.report(reason="max_frames")
        for patch in (
            {"topic": "/elsewhere/compressed"},
            {"received_frames": 3},
            {"compatible_jpeg_png_headers": 2},
            {"termination_reason": "unknown"},
            {"claims": {**original["claims"], "isaac_sim_origin_verified": True}},
        ):
            with self.subTest(patch=patch):
                report = dict(original)
                report.update(patch)
                raw = json.dumps(report).encode()
                with self.assertRaises(ValueError):
                    validate_camera_report(raw, expected_topic=manifest()["camera_topic"])

    def test_optional_camera_cli_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "manifest.json").write_bytes(raw_manifest())
            (root / "recording.jsonl").write_bytes(trace())
            receiver = CameraReceiverEvidence(max_frames=1)
            receiver.observe(sample_png(), "png", 10.0)
            (root / "camera.json").write_text(json.dumps(receiver.report(reason="max_frames")))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main([str(root / "manifest.json"), str(root / "recording.jsonl"),
                      "--camera-report", str(root / "camera.json")])
            report = json.loads(output.getvalue())
            self.assertEqual(report["camera_receiver_evidence"]["received_frames"], 1)
            self.assertFalse(report["camera_receiver_evidence"]["simulator_origin_verified"])

    def test_mismatched_asset_fails(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
            build_simready_evidence(raw_manifest(), io.BytesIO(trace()), io.BytesIO(b"different"))

    def test_strict_schema_and_disallowed_paths(self):
        for patch in (
            {"asset_path": "../private.usd"},
            {"asset_path": "/root/fixture.usda"},
            {"asset_path": "scene/../../fixture.usd"},
            {"asset_path": "scene/not-usd.obj"},
            {"camera_topic": "/camera/image_raw"},
            {"asset_revision": "main"},
            {"experiment_version": True},
            {"ros_distro": "iron"},
        ):
            with self.subTest(patch=patch):
                data = manifest()
                data.update(patch)
                with self.assertRaises(ValueError):
                    validate_manifest(raw_manifest(data))

    def test_invalid_json_and_duplicate_keys(self):
        for value in (b'{"experiment_id": "x", "experiment_id": "y"}',
                      b'{"x": NaN}', b"\xff", b" " * 16385):
            with self.subTest(value=value[:30]):
                with self.assertRaises(ValueError):
                    validate_manifest(value)

    def test_invalid_recording_prevents_any_output(self):
        with tempfile.TemporaryDirectory() as d:
            manifest_path = Path(d) / "manifest.json"
            trace_path = Path(d) / "recording.jsonl"
            manifest_path.write_bytes(raw_manifest())
            trace_path.write_bytes(b"\xff\n")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as exc:
                    main([str(manifest_path), str(trace_path)])
            self.assertEqual(exc.exception.code, 2)
            self.assertEqual(out.getvalue(), "")

    def test_cli_report(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "manifest.json").write_bytes(raw_manifest())
            (root / "recording.jsonl").write_bytes(trace())
            (root / "fixture.usda").write_bytes(ASSET)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                main([str(root / "manifest.json"), str(root / "recording.jsonl"),
                      "--asset-file", str(root / "fixture.usda")])
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["asset"]["local_bytes_sha256_verified"])


if __name__ == "__main__":
    unittest.main()
