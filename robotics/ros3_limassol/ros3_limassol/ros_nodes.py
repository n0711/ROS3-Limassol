# SPDX-License-Identifier: Apache-2.0
"""Optional ROS 2 transport adapter; the domain logic is ROS-independent."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .llm_diagnostics import explain_status, validate_status
from .live_recorder import LiveRecorder, UnrecordablePayloadError
from .monitor import LinkMonitor
from .recording import MAX_RECORDS
from .simulator import UsvSimulator
from .telemetry import finite_number


def telemetry_qos():
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )


def status_qos():
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST, depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
    )


class SimUsvNode(Node):
    def __init__(self, **kwargs):
        super().__init__("simulated_usv", **kwargs)
        robot_id = self.declare_parameter("robot_id", "usv01").value
        rate = finite_number(self.declare_parameter("rate_hz", 10.0).value, "rate_hz")
        if not 0 < rate <= 1000:
            raise ValueError("rate_hz must be in (0, 1000]")
        start = self.declare_parameter("blackout_start_s", 2.0).value
        duration = self.declare_parameter("blackout_duration_s", 3.0).value
        self.simulator = UsvSimulator(robot_id, start, duration)
        self.publisher = self.create_publisher(String, "telemetry", telemetry_qos())
        self._started = time.monotonic()
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(1.0 / rate, self._tick, clock=self._steady_clock)

    def _tick(self):
        sample = self.simulator.sample(time.monotonic() - self._started, time.time_ns())
        if sample is not None:
            self.publisher.publish(String(data=sample.to_json()))


class LinkMonitorNode(Node):
    def __init__(self, **kwargs):
        super().__init__("link_monitor", **kwargs)
        robot_id = self.declare_parameter("robot_id", "usv01").value
        stale = self.declare_parameter("stale_after_s", 1.0).value
        late = self.declare_parameter("late_samples", "reject").value
        self.monitor = LinkMonitor(robot_id, stale, late_samples=late)
        self.publisher = self.create_publisher(String, "link_status", status_qos())
        self.subscription = self.create_subscription(
            String, "telemetry", self._receive, telemetry_qos()
        )
        self._previous = None
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(0.1, self._tick, clock=self._steady_clock)

    def _receive(self, message):
        self.monitor.ingest(message.data, time.monotonic())

    def _tick(self):
        status = self.monitor.snapshot(time.monotonic())
        self.publisher.publish(String(data=status.to_json()))
        if status.state != self._previous:
            self.get_logger().info(f"{status.robot_id}: {status.state}")
            self._previous = status.state


class TelemetryRecorderNode(Node):
    """Observe telemetry without publishing application data or commands.

    The recorder's receiver clock is independent of both the publisher's
    timestamps and ROS simulation time. Write/clock/limit errors stop the
    process rather than quietly producing an incomplete experiment.
    """

    def __init__(self, **kwargs):
        super().__init__("telemetry_recorder", **kwargs)
        self.recorder = None
        self.unrecorded_payloads = 0
        try:
            output = self.declare_parameter("output_path", "").value
            if not isinstance(output, str) or not output.strip():
                raise ValueError("output_path must name a new recording file")
            period = finite_number(
                self.declare_parameter("tick_period_s", 0.1).value, "tick_period_s"
            )
            if not 0 < period <= 60:
                raise ValueError("tick_period_s must be in (0, 60]")
            maximum = self.declare_parameter("max_records", MAX_RECORDS).value
            self.recorder = LiveRecorder(output, max_records=maximum)
            self.subscription = self.create_subscription(
                String, "telemetry", self._receive, telemetry_qos()
            )
            self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
            self.timer = self.create_timer(period, self.recorder.tick, clock=self._steady_clock)
        except BaseException:
            if self.recorder is not None:
                self.recorder.close()
            super().destroy_node()
            raise

    def _receive(self, message):
        try:
            self.recorder.receive(message.data)
        except UnrecordablePayloadError:
            self.unrecorded_payloads += 1
            if self.unrecorded_payloads == 1:
                self.get_logger().warning(
                    "Payload outside version-1 text/size bounds was not recorded; "
                    "the total will be logged at shutdown."
                )

    def destroy_node(self):
        try:
            if self.recorder is not None:
                self.recorder.close()
                self.get_logger().info(
                    f"Recording closed: {self.recorder.records} observations; "
                    f"{self.unrecorded_payloads} unrecordable payloads"
                )
        finally:
            super().destroy_node()



class LLMDiagnosticNode(Node):
    """Read-only ROS status explanation via a separately running local Ollama.

    A worker performs inference outside ROS callbacks; only the ROS timer
    publishes results. This node never publishes telemetry, commands, or
    safety decisions. A single pending change bounds work during flapping.
    """

    def __init__(self, **kwargs):
        super().__init__("llm_diagnostics", **kwargs)
        self.robot_id = self.declare_parameter("robot_id", "usv01").value
        self.model = self.declare_parameter("model", "llama3.2").value
        self.timeout_s = finite_number(
            self.declare_parameter("timeout_s", 8.0).value, "timeout_s"
        )
        self.min_interval_s = finite_number(
            self.declare_parameter("min_interval_s", 3.0).value, "min_interval_s"
        )
        if not 0 < self.timeout_s <= 30 or not 0.1 <= self.min_interval_s <= 3600:
            raise ValueError("invalid LLM inference timeout or minimum interval")
        self.publisher = self.create_publisher(String, "llm_diagnostics", status_qos())
        self.subscription = self.create_subscription(
            String, "link_status", self._receive_status, status_qos()
        )
        self._last_seen_state = None
        self._queued = None
        self._future = None
        self._next_allowed = 0.0
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ros3-llm")
        self._steady_clock = Clock(clock_type=ClockType.STEADY_TIME)
        self.timer = self.create_timer(0.2, self._poll, clock=self._steady_clock)

    def _receive_status(self, message):
        try:
            status = validate_status(message.data)
        except ValueError:
            self.get_logger().warning("Invalid link status ignored by LLM observer")
            return
        if status["robot_id"] != self.robot_id:
            return
        if status["state"] == self._last_seen_state:
            return
        self._last_seen_state = status["state"]
        self._queued = status

    def _poll(self):
        if self._future is not None and self._future.done():
            completed = self._future
            self._future = None
            try:
                report = completed.result()
                # A delayed hypothesis about an old state is not current status.
                if report["observed_state"] == self._last_seen_state:
                    self.publisher.publish(String(data=json.dumps(
                        report, sort_keys=True, allow_nan=False,
                    )))
            except (OSError, ValueError, TypeError) as exc:
                self.get_logger().warning("Read-only LLM diagnosis unavailable: %s" % exc)
        now = time.monotonic()
        if self._future is None and self._queued is not None and now >= self._next_allowed:
            status = self._queued
            self._queued = None
            self._next_allowed = now + self.min_interval_s
            self._future = self._worker.submit(
                explain_status, status, self.model, timeout_s=self.timeout_s,
            )

    def destroy_node(self):
        try:
            self._worker.shutdown(wait=False, cancel_futures=True)
        finally:
            super().destroy_node()


def _spin(factory, args):
    rclpy.init(args=args)
    node = None
    try:
        node = factory()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def sim_main(args=None):
    _spin(SimUsvNode, args)


def monitor_main(args=None):
    _spin(LinkMonitorNode, args)


def recorder_main(args=None):
    try:
        _spin(TelemetryRecorderNode, args)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"telemetry recorder: {exc}") from exc


def llm_diagnostics_main(args=None):
    try:
        _spin(LLMDiagnosticNode, args)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"LLM diagnostics: {exc}") from exc
