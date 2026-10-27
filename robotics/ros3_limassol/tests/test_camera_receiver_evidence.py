"""Deterministic camera format evidence tests without ROS or camera hardware."""
import json
import math
import unittest
from array import array

from ros3_limassol.camera_receiver_evidence import (
    CameraReceiverEvidence, declared_codec, validate_camera_topic,
)
from ros3_limassol.vlm_diagnostics import MAX_IMAGE_BYTES
from test_vlm_diagnostics import sample_jpeg, sample_png


class CameraReceiverEvidenceTests(unittest.TestCase):
    def test_jpeg_png_headers_are_counted_without_persisting_frames(self):
        image = sample_png()
        receiver = CameraReceiverEvidence(max_frames=2)
        self.assertEqual(
            receiver.observe(memoryview(array("B", image)), "png", 10.0),
            "vlm_input_compatible_header",
        )
        self.assertEqual(
            receiver.observe(sample_jpeg(), "rgb8; jpeg compressed bgr8", 10.5),
            "vlm_input_compatible_header",
        )
        out = receiver.report(reason="max_frames")
        self.assertEqual(out["received_frames"], 2)
        self.assertEqual(out["compatible_jpeg_png_headers"], 2)
        self.assertEqual(out["unsupported_h264_hevc_frames"], 0)
        self.assertEqual(out["observed_receiver_span_s"], 0.5)
        self.assertFalse(out["claims"]["jpeg_png_decoder_success_verified"])
        self.assertFalse(out["claims"]["isaac_sim_origin_verified"])
        self.assertFalse(out["claims"]["actuation_authority"])
        raw = json.dumps(out)
        self.assertNotIn("payload", raw.lower())
        self.assertNotIn("image_sha256", raw)
        self.assertNotIn(image.hex(), raw)

    def test_isaac_h264_hevc_require_conversion_for_current_vlm(self):
        receiver = CameraReceiverEvidence(max_frames=3)
        self.assertEqual(receiver.observe(memoryview(b"some h264 bitstream"), "h264", 1),
                         "unsupported_codec")
        self.assertEqual(receiver.observe(b"hevc data", "hevc", 2),
                         "unsupported_codec")
        self.assertEqual(receiver.observe(b"hevc alias", "h265", 3),
                         "unsupported_codec")
        out = receiver.report(reason="max_frames")
        self.assertEqual(out["unsupported_h264_hevc_frames"], 3)
        self.assertEqual(out["compatible_jpeg_png_headers"], 0)
        self.assertEqual(out["codec_declarations"]["h264"], 1)
        self.assertEqual(out["codec_declarations"]["hevc"], 2)

    def test_invalid_and_oversized_payloads_not_compatible(self):
        receiver = CameraReceiverEvidence(max_frames=4)
        self.assertEqual(receiver.observe(b"notpng", "png", 0), "invalid_image_header")
        self.assertEqual(receiver.observe(b"", "jpeg", 1), "invalid_image_header")
        self.assertEqual(receiver.observe(b"x", "untrusted", 2),
                         "unsupported_or_missing_format")
        self.assertEqual(receiver.observe(b"x" * (MAX_IMAGE_BYTES + 1), "png", 3),
                         "oversized")
        result = receiver.report(reason="max_frames")
        self.assertEqual(result["invalid_or_oversized_frames"], 4)
        self.assertEqual(result["oversized_frames"], 1)
        self.assertEqual(result["compatible_jpeg_png_headers"], 0)

    def test_zero_observations_is_not_evidence_of_camera(self):
        out = CameraReceiverEvidence().report(reason="timeout")
        self.assertEqual(out["received_frames"], 0)
        self.assertFalse(out["claims"]["camera_topic_messages_observed"])
        self.assertIsNone(out["first_receiver_monotonic_s"])
        self.assertIsNone(out["observed_receiver_span_s"])

    def test_strict_limits_clock_and_topics(self):
        for topic in ("relative", "/camera/image_raw", "//bad/compressed",
                      "/bad/../compressed", "/bad//compressed", "/"):
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                validate_camera_topic(topic)
        for count in (0, 1001, True, 2.0):
            with self.subTest(count=count), self.assertRaises(ValueError):
                CameraReceiverEvidence(max_frames=count)
        receiver = CameraReceiverEvidence(max_frames=1)
        for t in (-1, float("nan"), float("inf"), True):
            with self.subTest(t=t), self.assertRaises(ValueError):
                receiver.observe(b"stuff", "h264", t)
        self.assertEqual(receiver.received, 0)
        receiver.observe(b"stuff", "h264", 2)
        with self.assertRaises(ValueError):
            receiver.observe(b"stuff", "h264", 3)

    def test_monotonic_receiver_clock(self):
        receiver = CameraReceiverEvidence(max_frames=2)
        receiver.observe(b"stuff", "h264", 2)
        with self.assertRaisesRegex(ValueError, "backwards"):
            receiver.observe(b"stuff", "h264", 1)
        self.assertEqual(receiver.received, 1)

    def test_codec_labels_are_not_decoding_proof(self):
        self.assertEqual(declared_codec("rgb8; jpeg compressed bgr8"), "jpeg")
        self.assertEqual(declared_codec("rgb8; png compressed rgb8"), "png")
        self.assertEqual(declared_codec("AVC"), "h264")
        self.assertEqual(declared_codec("hevc"), "hevc")
        self.assertEqual(declared_codec("h265"), "hevc")
        self.assertEqual(declared_codec("png jpeg"), "other")
        self.assertEqual(declared_codec(""), "other")
        self.assertEqual(declared_codec("x" * 200), "other")


if __name__ == "__main__":
    unittest.main()
