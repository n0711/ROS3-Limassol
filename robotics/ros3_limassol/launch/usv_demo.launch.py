from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    robot_id = LaunchConfiguration("robot_id")
    common = {"robot_id": ParameterValue(robot_id, value_type=str)}
    return LaunchDescription([
        DeclareLaunchArgument("robot_id", default_value="usv01"),
        DeclareLaunchArgument("rate_hz", default_value="10.0"),
        DeclareLaunchArgument("stale_after_s", default_value="1.0"),
        DeclareLaunchArgument("blackout_start_s", default_value="2.0"),
        DeclareLaunchArgument("blackout_duration_s", default_value="3.0"),
        DeclareLaunchArgument("late_samples", default_value="reject"),
        Node(
            package="ros3_limassol", executable="sim_usv", output="screen",
            namespace=["limassol/", robot_id],
            parameters=[common, {
                "rate_hz": ParameterValue(LaunchConfiguration("rate_hz"), value_type=float),
                "blackout_start_s": ParameterValue(
                    LaunchConfiguration("blackout_start_s"), value_type=float
                ),
                "blackout_duration_s": ParameterValue(
                    LaunchConfiguration("blackout_duration_s"), value_type=float
                ),
            }],
        ),
        Node(
            package="ros3_limassol", executable="link_monitor", output="screen",
            namespace=["limassol/", robot_id],
            parameters=[common, {
                "stale_after_s": ParameterValue(
                    LaunchConfiguration("stale_after_s"), value_type=float
                ),
                "late_samples": ParameterValue(
                    LaunchConfiguration("late_samples"), value_type=str
                ),
            }],
        ),
    ])
