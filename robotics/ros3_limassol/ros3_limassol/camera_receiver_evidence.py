# SPDX-License-Identifier: Apache-2.0
"""Read-only, bounded receiver-side camera compatibility counters.

No image bytes, hashes, locations, camera IDs or captions are persisted.
This is not frame capture-time, rendering, or camera quality validation.
"""
from __future__ import annotations

import math
import re

from .vlm_diagnostics import MAX_IMAGE_BYTES, validate_frame

TOPIC = re.compile(r"/[A-Za-z0-9_/]{1,160}\Z")
KNOWN_CODECS = ("jpeg", "png", "h264", "hevc", "other")
MAX_SAMPLE_LIMIT = 1000


def validate_camera_topic(topic):
    if (not isinstance(topic, str) or not TOPIC.fullmatch(topic)
            or "//" in topic or not topic.endswith("/compressed")):
        raise ValueError("camera topic must be an absolute /compressed ROS topic")
    return topic


def declared_codec(format_name):
    """Transport label only; never infer a codec from untrusted image bytes."""
    if not isinstance(format_name, str) or len(format_name) > 96:
        return "other"
    words = set(format_name.lower().replace(";", " ").split())
    if "h264" in words or "avc" in words:
        return "h264"
    if "hevc" in words or "h265" in words:
        return "hevc"
    if "png" in words and not ({"jpeg", "jpg"} & words):
        return "png"
    if ({"jpeg", "jpg"} & words) and "png" not in words:
        return "jpeg"
    return "other"


class CameraReceiverEvidence:
    """Bounded single-topic aggregate; values are *receiver* observations."""

    def __init__(self, topic="/camera/image_raw/compressed", max_frames=100):
        self.topic = validate_camera_topic(topic)
        if type(max_frames) is not int or not 1 <= max_frames <= MAX_SAMPLE_LIMIT:
            raise ValueError("max_frames must be an integer from 1 to 1000")
        self.max_frames = max_frames
        self.received = 0
        self.compatible = 0
        self.incompatible = 0
        self.invalid = 0
        self.oversized = 0
        self.bytes_received = 0
        self.codecs = {codec: 0 for codec in KNOWN_CODECS}
        self._first = None
        self._last = None

    def observe(self, payload, format_name, now_s):
        """Observe a delivered CompressedImage; retain only aggregate counters."""
        if self.received >= self.max_frames:
            raise ValueError("camera sample limit reached")
        if type(now_s) not in (float, int) or not math.isfinite(now_s) or now_s < 0:
            raise ValueError("invalid monotonic receiver time")
        if self._last is not None and now_s < self._last:
            raise ValueError("receiver clock moved backwards")
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise ValueError("camera payload must be binary")
        length = len(payload)
        # The ROS middleware has already received the message. Bound any
        # subsequent copying or image parsing done inside ROS3.
        codec = declared_codec(format_name)
        self.received += 1
        self.bytes_received += length
        self.codecs[codec] += 1
        self._first = now_s if self._first is None else self._first
        self._last = now_s
        if length > MAX_IMAGE_BYTES:
            self.oversized += 1
            self.invalid += 1
            return "oversized"
        if codec in ("h264", "hevc"):
            self.incompatible += 1
            return "unsupported_codec"
        if codec not in ("jpeg", "png"):
            self.invalid += 1
            return "unsupported_or_missing_format"
        try:
            validate_frame(payload, format_name)
        except ValueError:
            self.invalid += 1
            return "invalid_image_header"
        self.compatible += 1
        return "vlm_input_compatible_header"

    def report(self, *, reason):
        if reason not in ("max_frames", "timeout"):
            raise ValueError("invalid receiver observation termination reason")
        return {
            "camera_receiver_report_version": 1,
            "source": "ros2-compressed-image-receiver",
            "topic": self.topic,
            "max_frames": self.max_frames,
            "termination_reason": reason,
            "received_frames": self.received,
            "compatible_jpeg_png_headers": self.compatible,
            "unsupported_h264_hevc_frames": self.incompatible,
            "invalid_or_oversized_frames": self.invalid,
            "oversized_frames": self.oversized,
            "received_payload_bytes": self.bytes_received,
            "codec_declarations": dict(self.codecs),
            "first_receiver_monotonic_s": self._first,
            "last_receiver_monotonic_s": self._last,
            "observed_receiver_span_s": (
                self._last - self._first if self._first is not None else None
            ),
            "claims": {
                "camera_topic_messages_observed": self.received > 0,
                "jpeg_png_decoder_success_verified": False,
                "vlm_model_inference_verified": False,
                "image_capture_timestamps_verified": False,
                "isaac_sim_origin_verified": False,
                "simready_asset_loaded_verified": False,
                "time_alignment_verified": False,
                "actuation_authority": False,
            },
            "interpretation": (
                "Read-only ROS 2 CompressedImage receiver-side format/header probe. "
                "JPEG/PNG envelopes checked, not decoded. H264/HEVC transport is "
                "incompatible with the current ROS3 VLM observer; convert to "
                "bounded JPEG/PNG using a separately verified transport. "
                "No stored camera pixels, model inference, frame capture timing, "
                "DDS delivery rate, Isaac Sim provenance, or field validation."
            ),
        }
