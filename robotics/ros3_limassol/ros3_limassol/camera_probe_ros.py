# SPDX-License-Identifier: Apache-2.0
"""Receive-only ROS 2 camera transport probe. No image files or publications.

Usage (built/sourced ROS2 Humble/Jazzy workspace):
    ros2 run ros3_limassol simready_camera_probe --ros-args \
      -p camera_topic:=/camera/image_raw/compressed \
      -p output_path:=/tmp/camera-probe-01.json
"""
from __future__ import annotations

import json
from pathlib import Path
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from .camera_receiver_evidence import CameraReceiverEvidence
from .ros_nodes import telemetry_qos
from .telemetry import finite_number


class SimReadyCameraProbeNode(Node):
    def __init__(self, **kwargs):
        super().__init__("simready_camera_probe", **kwargs)
        topic = self.declare_parameter(
            "camera_topic", "/camera/image_raw/compressed"
        ).value
        limit = self.declare_parameter("max_frames", 100).value
        self.receiver = CameraReceiverEvidence(topic=topic, max_frames=limit)
        self.timeout_s = finite_number(
            self.declare_parameter("timeout_s", 30.0).value, "timeout_s"
        )
        if not 0.1 <= self.timeout_s <= 600:
            raise ValueError("timeout_s must be between 0.1 and 600 seconds")
        output = self.declare_parameter("output_path", "").value
        if not isinstance(output, str) or not output or len(output) > 4096:
            raise ValueError("output_path must name a new JSON report file")
        self.output_path = Path(output)
        self.started_s = time.monotonic()
        self.finished = False
        self.report = None
        self.subscription = self.create_subscription(
            CompressedImage, topic, self._receive, telemetry_qos()
        )
        self.timer = self.create_timer(0.1, self._tick)

    def _receive(self, message):
        if self.finished:
            return
        self.receiver.observe(memoryview(message.data), message.format, time.monotonic())
        if self.receiver.received >= self.receiver.max_frames:
            self._finish("max_frames")

    def _tick(self):
        if not self.finished and time.monotonic() - self.started_s >= self.timeout_s:
            self._finish("timeout")

    def _finish(self, reason):
        # Make the complete bounded JSON before creating the destination file.
        report = self.receiver.report(reason=reason)
        serialized = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        # Exclusive creation avoids silently clobbering previous experiment evidence.
        with self.output_path.open("x", encoding="utf-8") as stream:
            try:
                stream.write(serialized)
                stream.flush()
            except BaseException:
                self.output_path.unlink(missing_ok=True)
                raise
        self.report = report
        self.finished = True
        self.get_logger().info(
            f"Camera transport report saved: {self.output_path} "
            f"(received={report['received_frames']}, "
            f"JPEG/PNG-compatible={report['compatible_jpeg_png_headers']})"
        )


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = SimReadyCameraProbeNode()
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=0.1)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except (OSError, ValueError, TypeError) as exc:
        raise SystemExit(f"SimReady camera probe: {exc}") from exc
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
