"""DDS integration test. A missing ROS installation is an explicit skip."""

import importlib.util
import json
import time
import unittest
import uuid

HAS_ROS = importlib.util.find_spec("rclpy") is not None


@unittest.skipUnless(HAS_ROS, "ROS 2 rclpy is not installed")
class RosGraphTests(unittest.TestCase):
    def test_dds_blackout_and_recovery(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from std_msgs.msg import String
        from ros3_limassol.ros_nodes import LinkMonitorNode, SimUsvNode, status_qos

        rclpy.init()
        executor = SingleThreadedExecutor()
        nodes = []
        seen = []
        namespace = "/limassol_test_" + uuid.uuid4().hex[:8]
        try:
            # Observe healthy traffic before introducing the blackout; do not
            # make success depend on a particular DDS discovery duration.
            publisher = SimUsvNode(namespace=namespace, parameter_overrides=[
                Parameter("rate_hz", value=20.0),
                Parameter("blackout_start_s", value=1000.0),
                Parameter("blackout_duration_s", value=0.0),
                Parameter("use_sim_time", value=True),
            ])
            nodes.append(publisher)
            monitor = LinkMonitorNode(namespace=namespace, parameter_overrides=[
                Parameter("stale_after_s", value=0.3),
                Parameter("use_sim_time", value=True),
            ])
            nodes.append(monitor)
            sink = Node("test_sink", namespace=namespace)
            nodes.append(sink)
            subscription = sink.create_subscription(
                String, "link_status", lambda msg: seen.append(json.loads(msg.data)["state"]),
                status_qos(),
            )
            self.assertIsNotNone(subscription)
            for node in nodes:
                executor.add_node(node)

            def wait_for(predicate, seconds=8):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.02)
                    if predicate():
                        return
                self.fail(f"ROS status timeout; observed {seen}")

            wait_for(lambda: "HEALTHY" in seen)
            publisher.timer.cancel()
            wait_for(lambda: "STALE" in seen)
            seen_after_stale = len(seen)
            publisher.timer.reset()
            wait_for(lambda: "HEALTHY" in seen[seen_after_stale:])
        finally:
            executor.shutdown()
            for node in reversed(nodes):
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
