"""Deterministic VLM tests; no ROS, camera, remote service or model download."""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from ros3_limassol.vlm_diagnostics import (
    MAX_IMAGE_BYTES, inspect_frame, main, validate_frame,
)


def png_chunk(name, data):
    return (
        struct.pack(">I", len(data)) + name + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    )


def sample_png(width=1, height=1):
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\x00" + b"\x00\x00\x00" * width
    image = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(pixels))
        + png_chunk(b"IEND", b"")
    )
    return image


def sample_jpeg():
    # Structurally shaped SOF sample for bounded header inspection; it is not
    # a valid decoded photograph. This exercises the header guard, not a codec.
    return (
        b"\xff\xd8"
        + b"\xff\xc0" + struct.pack(">H", 11)
        + b"\x08" + struct.pack(">HH", 1, 1)
        + b"\x01\x01\x11\x00"
        + b"\xff\xda" + struct.pack(">H", 8)
        + b"\x01\x01\x00\x00\x3f\x00"
        + b"\xff\xd9"
    )


def fake_model():
    return {
        "done": True,
        "message": {
            "content": json.dumps({
                "scene_summary": "A uniform small image is visible.",
                "visible_features": ["Simple image pattern"],
                "uncertainties": ["No scale or scene context"],
            }),
        },
    }


class VLMDiagnosticsTests(unittest.TestCase):
    def test_actual_vision_request_contains_base64_image_without_tools(self):
        raw = sample_png()
        sent = []
        def chat(request, timeout_s):
            sent.append((request, timeout_s))
            return fake_model()
        report = inspect_frame(raw, "png", model="gemma3:4b", chat=chat)
        self.assertEqual(report["image_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertFalse(report["navigation_authority"])
        self.assertFalse(report["inference_verified"])
        self.assertNotIn("image", report)
        self.assertNotIn(base64.b64encode(raw).decode(), json.dumps(report))
        self.assertEqual(len(sent), 1)
        request, timeout = sent[0]
        self.assertEqual(timeout, 20.0)
        self.assertEqual(request["stream"], False)
        self.assertNotIn("tools", request)
        self.assertEqual(request["format"]["type"], "object")
        self.assertEqual(
            base64.b64decode(request["messages"][1]["images"][0]), raw,
        )
        self.assertEqual(report["image_width"], 1)

    def test_ros_compressed_transport_format_variants(self):
        frame = sample_png()
        self.assertEqual(validate_frame(frame, "rgb8; png compressed rgb8")[1], "png")
        self.assertEqual(validate_frame(sample_jpeg(), "bgr8; jpeg compressed bgr8")[1], "jpeg")

    def test_format_size_and_dimension_guards(self):
        valid = sample_png()
        cases = [
            (valid, "unknown"),
            (valid, "jpeg"),
            (valid, "png jpeg"),
            (b"", "png"),
            (b"x" * (MAX_IMAGE_BYTES + 1), "png"),
            (sample_png(width=4097), "png"),
            (sample_png(width=4096, height=4096 + 1), "png"),
            (sample_png(width=0), "png"),
            (valid[:-12], "png"),
            (b"\xff\xd8\xff\xd9", "jpeg"),
        ]
        for data, fmt in cases:
            with self.subTest(fmt=fmt, length=len(data)), self.assertRaises(ValueError):
                validate_frame(data, fmt)

    def test_invalid_responses_and_inputs_fail_closed(self):
        image = sample_png()
        outputs = [
            {"done": False, "message": {"content": "{}"}},
            {"done": True, "message": {"tool_calls": [{"name": "drive"}], "content": "{}"}},
            {"done": True, "message": {"content": '{"scene_summary":"x"}'}},
            {"done": True, "message": {"content": '{"scene_summary":"x","visible_features":[],"uncertainties":[],"scene_summary":"duplicate"}'}},
            {"done": True, "message": {"content": json.dumps({
                "scene_summary": "x", "visible_features": ["y"] * 5,
                "uncertainties": [],
            })}},
        ]
        for bad in outputs:
            with self.subTest(bad=str(bad)[:60]), self.assertRaises(ValueError):
                inspect_frame(image, "png", chat=lambda payload, timeout_s: bad)
        called = []
        with self.assertRaises(ValueError):
            inspect_frame(image, "png", model="malformed model\n", chat=lambda *args: called.append(args))
        self.assertEqual(called, [])

    def test_cli_file_input_remains_bounded(self):
        image = sample_png()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "small.png"
            path.write_bytes(image)
            captured = io.StringIO()
            with patch("ros3_limassol.vlm_diagnostics.local_chat", return_value=fake_model()):
                with contextlib.redirect_stdout(captured):
                    main(["--image", str(path), "--model", "gemma3:4b"])
            self.assertEqual(json.loads(captured.getvalue())["image_format"], "png")
            path.write_bytes(b"x" * (MAX_IMAGE_BYTES + 1))
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--image", str(path)])


if __name__ == "__main__":
    unittest.main()
