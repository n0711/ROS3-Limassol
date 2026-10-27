"""Read-only ROS 2 DDS camera format probe integration test, no Isaac runtime."""
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from test_vlm_diagnostics import sample_png

HAS_ROS = importlib.util.find_spec("rclpy") is not None


@unittest.skipUnless(HAS_ROS, "ROS 2 rclpy is not installed")
class CameraProbeROSTests(unittest.TestCase):
    def test_receives_formats_and_writes_one_bounded_report(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from sensor_msgs.msg import CompressedImage

        from ros3_limassol.camera_probe_ros import SimReadyCameraProbeNode
        from ros3_limassol.ros_nodes import telemetry_qos

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "camera-evidence.json"
            ns = "/ros3_camera_probe_" + uuid.uuid4().hex[:8]
            topic = ns + "/camera/image_raw/compressed"
            rclpy.init()
            source = observer = executor = None
            try:
                source = Node("camera_fixture", namespace=ns)
                publisher = source.create_publisher(
                    CompressedImage, topic, telemetry_qos()
                )
                observer = SimReadyCameraProbeNode(
                    namespace=ns, parameter_overrides=[
                        Parameter("camera_topic", value=topic),
                        Parameter("output_path", value=str(output_path)),
                        Parameter("max_frames", value=2),
                        Parameter("timeout_s", value=15.0),
                    ],
                )
                executor = SingleThreadedExecutor()
                executor.add_node(source)
                executor.add_node(observer)
                png_msg = CompressedImage()
                png_msg.format = "png"
                png_msg.data = sample_png()
                h264_msg = CompressedImage()
                h264_msg.format = "h264"
                h264_msg.data = b"\x00\x00\x00\x01"
                deadline = time.monotonic() + 9
                while not observer.finished and time.monotonic() < deadline:
                    if observer.receiver.received == 0:
                        publisher.publish(png_msg)
                    else:
                        publisher.publish(h264_msg)
                    executor.spin_once(timeout_sec=0.05)
                self.assertTrue(observer.finished, "camera evidence probe timed out")
                report = json.loads(output_path.read_text(encoding="utf-8"))
                self.assertEqual(report["termination_reason"], "max_frames")
                self.assertEqual(report["received_frames"], 2)
                self.assertEqual(report["compatible_jpeg_png_headers"], 1)
                self.assertEqual(report["unsupported_h264_hevc_frames"], 1)
                self.assertTrue(report["claims"]["camera_topic_messages_observed"])
                self.assertFalse(report["claims"]["isaac_sim_origin_verified"])
                self.assertFalse(report["claims"]["time_alignment_verified"])
                self.assertFalse(report["claims"]["actuation_authority"])
                self.assertEqual(report["topic"], topic)
                self.assertEqual(len(list(Path(directory).iterdir())), 1)
            finally:
                if executor is not None:
                    executor.shutdown()
                if observer is not None:
                    observer.destroy_node()
                if source is not None:
                    source.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()


if __name__ == "__main__":
    unittest.main()
