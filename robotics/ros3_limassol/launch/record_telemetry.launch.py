"""Record an existing robot namespace without launching a publisher."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument("output_path", description="New receiver-observation JSONL file"),
        DeclareLaunchArgument("robot_id", default_value="usv01"),
        DeclareLaunchArgument("tick_period_s", default_value="0.1"),
        DeclareLaunchArgument("max_records", default_value="1000000"),
        Node(
            package="ros3_limassol", executable="telemetry_recorder", output="screen",
            namespace=["limassol/", LaunchConfiguration("robot_id")],
            parameters=[{
                "output_path": ParameterValue(LaunchConfiguration("output_path"), value_type=str),
                "tick_period_s": ParameterValue(
                    LaunchConfiguration("tick_period_s"), value_type=float
                ),
                "max_records": ParameterValue(LaunchConfiguration("max_records"), value_type=int),
            }],
        ),
    ])
