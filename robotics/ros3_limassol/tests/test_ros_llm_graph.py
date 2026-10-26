"""ROS2 integration: status subscription -> worker -> read-only diagnostics topic.

A fake model response is used so CI does not require an Ollama server.
"""
import importlib.util
import json
import time
import unittest
import uuid
from unittest.mock import patch

HAS_ROS = importlib.util.find_spec("rclpy") is not None


@unittest.skipUnless(HAS_ROS, "ROS2 rclpy is not installed")
class LlmGraphTests(unittest.TestCase):
    def test_status_transition_reaches_diagnostics_topic(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from std_msgs.msg import String

        from ros3_limassol.monitor import LinkStatus
        from ros3_limassol.ros_nodes import LLMDiagnosticNode, status_qos

        rclpy.init()
        executor = SingleThreadedExecutor()
        nodes = []
        namespace = "/ros3_llm_test_" + uuid.uuid4().hex[:8]
        received = []
        observed = []
        try:
            publisher_node = Node("status_fixture", namespace=namespace)
            nodes.append(publisher_node)
            publisher = publisher_node.create_publisher(String, "link_status", status_qos())
            observer = LLMDiagnosticNode(namespace=namespace, parameter_overrides=[
                Parameter("robot_id", value="usv01"),
                Parameter("model", value="mock-local:1"),
                Parameter("min_interval_s", value=0.1),
                Parameter("timeout_s", value=1.0),
                Parameter("use_sim_time", value=True),
            ])
            nodes.append(observer)
            reader = Node("read_only_diagnostics_sink", namespace=namespace)
            nodes.append(reader)
            reader.create_subscription(
                String, "llm_diagnostics", lambda msg: received.append(json.loads(msg.data)),
                status_qos(),
            )
            for node in nodes:
                executor.add_node(node)

            status = LinkStatus(
                robot_id="usv01", state="STALE", age_s=2.0, accepted=3,
                rejected=0, last_sequence=2, last_rejection=None,
            )
            def fake_inference(snapshot, model, *, timeout_s):
                observed.append((snapshot, model, timeout_s))
                return {
                    "observed_state": snapshot["state"],
                    "navigation_authority": False,
                    "actuation_authority": False,
                    "diagnosis": {"summary": "Arrival state is stale"},
                }

            with patch("ros3_limassol.ros_nodes.explain_status", side_effect=fake_inference):
                deadline = time.monotonic() + 8
                while not received and time.monotonic() < deadline:
                    publisher.publish(String(data=status.to_json()))
                    executor.spin_once(timeout_sec=0.05)
                self.assertTrue(received, "LLM diagnostics were not published")
                self.assertEqual(received[0]["observed_state"], "STALE")
                self.assertFalse(received[0]["navigation_authority"])
                self.assertEqual(observed[0][1], "mock-local:1")
                self.assertEqual(len(observed), 1)
        finally:
            executor.shutdown()
            for node in reversed(nodes):
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
