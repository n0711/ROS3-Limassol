"""Opt-in VLM observer on a compressed camera stream; no model is downloaded."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    robot_id = LaunchConfiguration("robot_id")
    return LaunchDescription([
        DeclareLaunchArgument("robot_id", default_value="usv01"),
        DeclareLaunchArgument("model", default_value="gemma3:4b"),
        DeclareLaunchArgument("camera_topic", default_value="camera/image/compressed"),
        DeclareLaunchArgument("timeout_s", default_value="20.0"),
        DeclareLaunchArgument("min_interval_s", default_value="10.0"),
        DeclareLaunchArgument("max_result_age_s", default_value="30.0"),
        Node(
            package="ros3_limassol", executable="vlm_observer",
            namespace=["limassol/", robot_id], output="screen",
            remappings=[(
                "camera/image/compressed", LaunchConfiguration("camera_topic"),
            )],
            parameters=[{
                "robot_id": ParameterValue(robot_id, value_type=str),
                "model": ParameterValue(LaunchConfiguration("model"), value_type=str),
                "timeout_s": ParameterValue(
                    LaunchConfiguration("timeout_s"), value_type=float,
                ),
                "min_interval_s": ParameterValue(
                    LaunchConfiguration("min_interval_s"), value_type=float,
                ),
                "max_result_age_s": ParameterValue(
                    LaunchConfiguration("max_result_age_s"), value_type=float,
                ),
            }],
        ),
    ])
