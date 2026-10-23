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
        for suffix in ("ros3_limassol/replay.py", "ros3_limassol/recording.py",
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
        events = [json.loads(line) for line in demo.splitlines()]
        if events[-1]["accepted"] != 51 or events[-1]["rejected"] != 0:
            raise RuntimeError("installed demo did not reproduce the paper's counts")
        print("Installed wheel: record/replay matched; 51 accepted, 0 rejected")


if __name__ == "__main__":
    main()
