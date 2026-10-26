"""ROS 2 DDS compressed-image -> fake-model -> diagnostic topic smoke test."""
import importlib.util
import json
import struct
import time
import unittest
import uuid
from unittest.mock import patch
import zlib

HAS_ROS = importlib.util.find_spec("rclpy") is not None


def _chunk(name, data):
    return (
        struct.pack(">I", len(data)) + name + data
        + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    )


def single_pixel_png():
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + _chunk(b"IEND", b"")
    )


@unittest.skipUnless(HAS_ROS, "ROS 2 rclpy is not installed")
class VLMGraphTests(unittest.TestCase):
    def test_compressed_camera_frame_reaches_read_only_diagnostic_topic(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from sensor_msgs.msg import CompressedImage
        from std_msgs.msg import String

        from ros3_limassol.ros_nodes import status_qos, telemetry_qos
        from ros3_limassol.vlm_ros_nodes import VLMObserverNode

        rclpy.init()
        namespace = "/ros3_vlm_test_" + uuid.uuid4().hex[:8]
        executor = SingleThreadedExecutor()
        nodes = []
        received = []
        model_calls = []
        try:
            source = Node("image_fixture", namespace=namespace)
            nodes.append(source)
            camera = source.create_publisher(
                CompressedImage, "camera/image/compressed", telemetry_qos()
            )
            observer = VLMObserverNode(namespace=namespace, parameter_overrides=[
                Parameter("robot_id", value="usv01"),
                Parameter("model", value="mock-vision:1"),
                Parameter("timeout_s", value=1.0),
                Parameter("min_interval_s", value=1.0),
                Parameter("max_result_age_s", value=5.0),
                Parameter("use_sim_time", value=True),
            ])
            nodes.append(observer)
            sink = Node("caption_sink", namespace=namespace)
            nodes.append(sink)
            sink.create_subscription(
                String, "vlm_diagnostics",
                lambda msg: received.append(json.loads(msg.data)), status_qos(),
            )
            for node in nodes:
                executor.add_node(node)

            def fake_inspect(image, fmt, *, model, timeout_s):
                model_calls.append((bytes(image), fmt, model, timeout_s))
                return {
                    "source": "mock-inference-for-graph-test",
                    "vlm_diagnostic_version": 1,
                    "description": {"scene_summary": "Synthetic image"},
                    "navigation_authority": False,
                    "actuation_authority": False,
                    "inference_verified": False,
                }

            msg = CompressedImage()
            msg.format = "png"
            msg.data = single_pixel_png()
            with patch("ros3_limassol.vlm_ros_nodes.inspect_frame", side_effect=fake_inspect):
                deadline = time.monotonic() + 9
                while not received and time.monotonic() < deadline:
                    camera.publish(msg)
                    executor.spin_once(timeout_sec=0.05)
                self.assertTrue(received, "No read-only VLM diagnostics observed")
                self.assertEqual(received[0]["robot_id"], "usv01")
                self.assertEqual(received[0]["description"]["scene_summary"], "Synthetic image")
                self.assertFalse(received[0]["actuation_authority"])
                self.assertEqual(len(model_calls), 1)
                self.assertEqual(model_calls[0][1:3], ("png", "mock-vision:1"))
        finally:
            executor.shutdown()
            for node in reversed(nodes):
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
