"""Verify an installed wheel and record/replay from outside its source tree."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    package = Path(__file__).resolve().parents[1]
    wheels = list((package / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Build exactly one wheel in dist/ before running this check")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
        for suffix in ("ros3_limassol/analyze.py", "ros3_limassol/replay.py", "ros3_limassol/recording.py",
                       "ros3_limassol/live_recorder.py", "/launch/record_telemetry.launch.py",
                       "/launch/usv_demo.launch.py", "/package.xml", "/LICENSE",
                       "/NOTICE", "/resource_index/packages/ros3_limassol"):
            if not any(member.endswith(suffix) for member in members):
                raise RuntimeError(f"wheel is missing {suffix}")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "installed"
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-index",
                        "--no-deps", "--target", str(target), str(wheel)], check=True)
        env = {**os.environ, "PYTHONPATH": str(target)}
        recording = root / "trace.jsonl"
        demo = subprocess.check_output([
            sys.executable, "-m", "ros3_limassol.demo", "--json", "--record",
            str(recording),
        ], cwd=root, env=env, text=True)
        replay = subprocess.check_output([
            sys.executable, "-m", "ros3_limassol.replay", str(recording), "--json",
        ], cwd=root, env=env, text=True)
        if demo != replay:
            raise RuntimeError("installed record/replay output differs")
        analysis = json.loads(subprocess.check_output([
            sys.executable, "-m", "ros3_limassol.analyze", str(recording),
        ], cwd=root, env=env, text=True))
        if (analysis["observations"] != 81 or analysis["accepted"] != 51 or
                analysis["stale_entries"] != 1 or analysis["recoveries"] != 1):
            raise RuntimeError("installed analysis did not reproduce the scenario")
        events = [json.loads(line) for line in demo.splitlines()]
        if events[-1]["accepted"] != 51 or events[-1]["rejected"] != 0:
            raise RuntimeError("installed demo did not reproduce the paper's counts")
        # Exercise the live writer from the installed package without ROS.
        # A synthetic receiver clock makes the outage reproducible here.
        script = '''
from ros3_limassol.live_recorder import LiveRecorder
from ros3_limassol.simulator import UsvSimulator
now = [123.0]
with LiveRecorder("live.jsonl", clock=lambda: now[0]) as recorder:
    recorder.receive(UsvSimulator(session_id="wheel").sample(0, 0).to_json())
    now[0] += 1.0
    recorder.tick()
'''
        subprocess.run([sys.executable, "-c", script], cwd=root, env=env, check=True)
        live = subprocess.check_output([
            sys.executable, "-m", "ros3_limassol.replay", "live.jsonl", "--json",
        ], cwd=root, env=env, text=True)
        live_events = [json.loads(line) for line in live.splitlines()]
        if live_events[-1]["state"] != "STALE" or live_events[-1]["accepted"] != 1:
            raise RuntimeError("installed live recorder did not preserve silence")
        print("Installed wheel: demo replay matched; live recording preserved silence")


if __name__ == "__main__":
    main()
