"""Start a read-only local LLM status observer; never starts a model server."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    robot = LaunchConfiguration("robot_id")
    return LaunchDescription([
        DeclareLaunchArgument("robot_id", default_value="usv01"),
        DeclareLaunchArgument("model", default_value="llama3.2"),
        DeclareLaunchArgument("timeout_s", default_value="8.0"),
        DeclareLaunchArgument("min_interval_s", default_value="3.0"),
        Node(
            package="ros3_limassol", executable="llm_diagnostics",
            namespace=["limassol/", robot], output="screen",
            parameters=[{
                "robot_id": ParameterValue(robot, value_type=str),
                "model": ParameterValue(LaunchConfiguration("model"), value_type=str),
                "timeout_s": ParameterValue(
                    LaunchConfiguration("timeout_s"), value_type=float,
                ),
                "min_interval_s": ParameterValue(
                    LaunchConfiguration("min_interval_s"), value_type=float,
                ),
            }],
        ),
    ])
