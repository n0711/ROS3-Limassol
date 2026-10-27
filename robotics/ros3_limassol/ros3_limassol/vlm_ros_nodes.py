# SPDX-License-Identifier: Apache-2.0
"""Opt-in ROS 2 CompressedImage subscriber for local, read-only VLM inference.

This node is separate from the telemetry monitor. It never publishes robot
commands, image frames, or ROS services, and performs inference off callbacks.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

from .llm_diagnostics import MODEL_NAME
from .observation_context import ReceiverObservationContext
from .ros_nodes import status_qos, telemetry_qos
from .telemetry import finite_number, validate_robot_id
from .vlm_diagnostics import MAX_IMAGE_BYTES, inspect_frame, validate_frame


class VLMObserverNode(Node):
    """Sample at most one compressed frame per interval, without a backlog."""

    def __init__(self, **kwargs):
        super().__init__("vlm_observer", **kwargs)
        self.robot_id = validate_robot_id(
            self.declare_parameter("robot_id", "usv01").value
        )
        self.model = self.declare_parameter("model", "gemma3:4b").value
        if not isinstance(self.model, str) or not MODEL_NAME.fullmatch(self.model):
            raise ValueError("invalid local VLM model name")
        self.timeout_s = finite_number(
            self.declare_parameter("timeout_s", 20.0).value, "timeout_s"
        )
        self.min_interval_s = finite_number(
            self.declare_parameter("min_interval_s", 10.0).value, "min_interval_s"
        )
        self.max_result_age_s = finite_number(
            self.declare_parameter("max_result_age_s", 30.0).value,
            "max_result_age_s",
        )
        if not 0 < self.timeout_s <= 30:
            raise ValueError("timeout_s must be in (0,30]")
        if not 1 <= self.min_interval_s <= 3600:
            raise ValueError("min_interval_s must be in [1,3600]")
        if not 1 <= self.max_result_age_s <= 3600:
            raise ValueError("max_result_age_s must be in [1,3600]")
        self._context = ReceiverObservationContext(
            robot_id=self.robot_id,
            max_status_age_s=self.declare_parameter(
                "max_status_age_s", 1.0,
            ).value,
        )

        self.publisher = self.create_publisher(
            String, "vlm_diagnostics", status_qos()
        )
        self.subscription = self.create_subscription(
            CompressedImage, "camera/image/compressed", self._receive_frame,
            telemetry_qos(),
        )
        self.status_subscription = self.create_subscription(
            String, "link_status", self._receive_status, status_qos(),
        )
        self._future = None
        self._started_at = None
        self._pending_context = None
        self._next_allowed = 0.0
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ros3-vlm")
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(0.2, self._poll, clock=self._steady_clock)

    def _receive_status(self, message):
        try:
            self._context.receive_status(message.data)
        except ValueError:
            self.get_logger().warning(
                "Invalid link status ignored by read-only camera observer"
            )

    def _receive_frame(self, message):
        # Drop freely rather than ever queueing images faster than inference.
        now = time.monotonic()
        if self._future is not None or now < self._next_allowed:
            return
        if not 0 < len(message.data) <= MAX_IMAGE_BYTES:
            self.get_logger().warning("Oversized/empty compressed frame ignored")
            return
        try:
            frame, fmt, _, _ = validate_frame(bytes(message.data), message.format)
        except ValueError:
            self.get_logger().warning("Invalid compressed frame ignored")
            return
        # Snapshot *before* inference, so later status updates cannot rewrite
        # the frame's receiver-side context.
        self._pending_context = self._context.sample_frame(now_s=now)
        self._started_at = now
        self._next_allowed = now + self.min_interval_s
        self._future = self._worker.submit(
            inspect_frame, frame, fmt, model=self.model, timeout_s=self.timeout_s,
        )

    def _poll(self):
        if self._future is None or not self._future.done():
            return
        completed = self._future
        self._future = None
        context = self._pending_context
        self._pending_context = None
        age = time.monotonic() - self._started_at
        try:
            description = completed.result()
            # Delayed captions must not be published as current observations.
            if age <= self.max_result_age_s:
                description["robot_id"] = self.robot_id
                description["processing_age_s"] = age
                description["observation_context"] = context
                self.publisher.publish(String(data=json.dumps(
                    description, allow_nan=False, sort_keys=True,
                )))
            else:
                self.get_logger().warning("Outdated VLM result discarded")
        except (OSError, ValueError, TypeError) as exc:
            self.get_logger().warning("Local VLM unavailable or invalid: %s" % exc)

    def destroy_node(self):
        try:
            self._worker.shutdown(wait=False, cancel_futures=True)
        finally:
            super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    try:
        node = VLMObserverNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except (OSError, ValueError) as exc:
        raise SystemExit(f"VLM observer: {exc}") from exc
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
