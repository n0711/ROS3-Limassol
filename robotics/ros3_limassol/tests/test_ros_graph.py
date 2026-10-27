"""DDS integration test. A missing ROS installation is an explicit skip."""

import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

HAS_ROS = importlib.util.find_spec("rclpy") is not None


@unittest.skipUnless(HAS_ROS, "ROS 2 rclpy is not installed")
class RosGraphTests(unittest.TestCase):
    def test_dds_recording_replays_blackout_and_recovery(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.parameter import Parameter
        from ros3_limassol.replay import run_replay
        from ros3_limassol.ros_nodes import SimUsvNode, TelemetryRecorderNode

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.jsonl"
            rclpy.init()
            executor = SingleThreadedExecutor()
            nodes = []
            namespace = "/limassol_record_" + uuid.uuid4().hex[:8]
            try:
                publisher = SimUsvNode(namespace=namespace, parameter_overrides=[
                    Parameter("rate_hz", value=20.0),
                    Parameter("blackout_start_s", value=1000.0),
                    Parameter("blackout_duration_s", value=0.0),
                    Parameter("use_sim_time", value=True),
                ])
                nodes.append(publisher)
                recorder = TelemetryRecorderNode(namespace=namespace, parameter_overrides=[
                    Parameter("output_path", value=str(path)),
                    Parameter("tick_period_s", value=0.05),
                    Parameter("use_sim_time", value=True),
                ])
                nodes.append(recorder)
                for node in nodes:
                    executor.add_node(node)

                def events():
                    with path.open(encoding="utf-8") as stream:
                        return list(run_replay(stream, stale_after_s=0.3))

                def wait_for(predicate, seconds=8):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        executor.spin_once(timeout_sec=0.02)
                        result = events()
                        if predicate(result):
                            return result
                    self.fail(f"live recording timeout; replayed {events()}")

                wait_for(lambda trace: trace[-1]["accepted"] >= 3)
                publisher.timer.cancel()
                stopped = wait_for(lambda trace: trace[-1]["state"] == "STALE")
                accepted_before_recovery = stopped[-1]["accepted"]
                publisher.timer.reset()
                recovered = wait_for(lambda trace: trace[-1]["state"] == "HEALTHY"
                                     and trace[-1]["accepted"] > accepted_before_recovery)
                self.assertEqual([item["state"] for item in recovered[:-1]],
                                 ["WAITING", "HEALTHY", "STALE", "HEALTHY"])
                self.assertEqual(recovered[-1]["rejected"], 0)
                lines = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertTrue(any(line["payload"] is None and line["time_s"] > 0
                                    for line in lines))
            finally:
                executor.shutdown()
                for node in reversed(nodes):
                    node.destroy_node()
                if rclpy.ok():
                    rclpy.shutdown()
            self.assertTrue(recorder.recorder.closed)
            self.assertEqual(events()[-1]["state"], "HEALTHY")

    def test_recorder_invalid_configuration_and_existing_file_protection(self):
        import rclpy
        from rclpy.parameter import Parameter
        from ros3_limassol.ros_nodes import TelemetryRecorderNode

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "live.jsonl"
            rclpy.init()
            try:
                for period in (0.0, -1.0, 61.0):
                    with self.subTest(period=period), self.assertRaises(ValueError):
                        TelemetryRecorderNode(parameter_overrides=[
                            Parameter("output_path", value=str(path)),
                            Parameter("tick_period_s", value=period),
                        ])
                    self.assertFalse(path.exists())
                with self.assertRaisesRegex(ValueError, "output_path"):
                    TelemetryRecorderNode()
                path.write_text("keep", encoding="utf-8")
                with self.assertRaises(FileExistsError):
                    TelemetryRecorderNode(parameter_overrides=[
                        Parameter("output_path", value=str(path)),
                    ])
                self.assertEqual(path.read_text(), "keep")
            finally:
                rclpy.shutdown()

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

    def test_two_robot_namespaces_are_monitored_independently(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from rclpy.parameter import Parameter
        from std_msgs.msg import String
        from ros3_limassol.ros_nodes import LinkMonitorNode, SimUsvNode, status_qos

        rclpy.init()
        executor = SingleThreadedExecutor()
        nodes = []
        base = "/limassol_pair_" + uuid.uuid4().hex[:8]
        spaces = {"usv01": f"{base}/usv01", "usv02": f"{base}/usv02"}
        statuses = {"usv01": [], "usv02": [], "miswired": []}
        try:
            publishers = {}
            for robot_id, namespace in spaces.items():
                publishers[robot_id] = SimUsvNode(namespace=namespace, parameter_overrides=[
                    Parameter("robot_id", value=robot_id),
                    Parameter("rate_hz", value=20.0),
                    Parameter("blackout_start_s", value=1000.0),
                    Parameter("blackout_duration_s", value=0.0),
                ])
                nodes.append(publishers[robot_id])
                nodes.append(LinkMonitorNode(namespace=namespace, parameter_overrides=[
                    Parameter("robot_id", value=robot_id),
                    Parameter("stale_after_s", value=0.5),
                ]))
            # Expects usv02 but is wired to usv01's telemetry; its own namespace keeps
            # its status off the real monitors' topics.
            nodes.append(LinkMonitorNode(
                namespace=f"{base}/miswired",
                cli_args=["--ros-args", "-r", f"telemetry:={spaces['usv01']}/telemetry"],
                parameter_overrides=[Parameter("robot_id", value="usv02"),
                                     Parameter("stale_after_s", value=0.5)]))
            sink = Node("test_sink", namespace=base)
            nodes.append(sink)
            for key, topic in (("usv01", f"{spaces['usv01']}/link_status"),
                               ("usv02", f"{spaces['usv02']}/link_status"),
                               ("miswired", f"{base}/miswired/link_status")):
                sink.create_subscription(
                    String, topic,
                    lambda msg, key=key: statuses[key].append(json.loads(msg.data)),
                    status_qos())
            for node in nodes:
                executor.add_node(node)

            def states(key, start=0):
                return [s["state"] for s in statuses[key][start:]]

            def wait_for(predicate, seconds=10):
                deadline = time.monotonic() + seconds
                while time.monotonic() < deadline:
                    executor.spin_once(timeout_sec=0.02)
                    if predicate():
                        return
                self.fail(f"ROS status timeout; observed {({k: states(k)[-5:] for k in statuses})}")

            wait_for(lambda: states("usv01")[-1:] == ["HEALTHY"]
                     and states("usv02")[-1:] == ["HEALTHY"]
                     and any(s["rejected"] for s in statuses["miswired"]))
            mark = {key: len(statuses[key]) for key in statuses}
            publishers["usv01"].timer.cancel()
            wait_for(lambda: "STALE" in states("usv01", mark["usv01"]))
            after_stale = len(statuses["usv01"])
            publishers["usv01"].timer.reset()
            wait_for(lambda: "HEALTHY" in states("usv01", after_stale))
            # usv01 went STALE and recovered; usv02 never noticed.
            self.assertEqual(set(states("usv02", mark["usv02"])), {"HEALTHY"})
            # Telemetry for the wrong robot is rejected and never counts as liveness.
            self.assertNotIn("HEALTHY", states("miswired"))
            last = statuses["miswired"][-1]
            self.assertEqual((last["state"], last["accepted"], last["last_rejection"]),
                             ("WAITING", 0, "unexpected_robot"))
        finally:
            executor.shutdown()
            for node in reversed(nodes):
                node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
