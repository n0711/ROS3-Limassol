from glob import glob
from setuptools import find_packages, setup

PACKAGE = "ros3_limassol"

setup(
    name=PACKAGE,
    version="0.3.1",
    packages=find_packages(exclude=("tests", "tests.*")),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE]),
        ("share/" + PACKAGE, ["package.xml", "LICENSE", "NOTICE"]),
        ("share/" + PACKAGE + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    python_requires=">=3.10",
    zip_safe=True,
    author="Charalampos Nadiotis",
    url="https://github.com/n0711/ROS3-Limassol",
    maintainer="Charalampos Nadiotis",
    maintainer_email="149877461+n0711@users.noreply.github.com",
    description="Experimental ROS 2 toolkit for field-robot telemetry and link liveness",
    license="Apache-2.0",
    extras_require={"test": ["pytest"]},
    entry_points={
        "console_scripts": [
            "limassol_demo = ros3_limassol.demo:main",
            "limassol_replay = ros3_limassol.replay:main",
            "limassol_evidence = ros3_limassol.evidence:main",
            "limassol_analyse = ros3_limassol.analysis:main",
            "sim_usv = ros3_limassol.ros_nodes:sim_main",
            "link_monitor = ros3_limassol.ros_nodes:monitor_main",
            "telemetry_recorder = ros3_limassol.ros_nodes:recorder_main",
        ],
    },
)
