# SPDX-License-Identifier: Apache-2.0
"""Optional ROS 2 transport adapter; the domain logic is ROS-independent."""

import time

import rclpy
from rclpy.clock import Clock
from rclpy.clock_type import ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .monitor import LinkMonitor
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
        self.monitor = LinkMonitor(robot_id, stale)
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
