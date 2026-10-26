# SPDX-License-Identifier: Apache-2.0
"""Smoke-check the installed ROS 2 package using its public command interfaces.

Run from the repository root after sourcing one ROS distribution and the colcon
install space. This checks synthetic behavior and package discovery only; it
does not establish real network performance or physical robot reliability.
"""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


PACKAGE = "ros3_limassol"
REQUIRED_EXECUTABLES = {"sim_usv", "link_monitor", "telemetry_recorder", "llm_diagnostics"}


def run(*command, cwd):
    result = subprocess.run(
        command, cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(map(str, command))}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout


def verify():
    # A temporary working directory prevents accidental source-tree imports and
    # ensures recording output does not pollute the repository.
    with tempfile.TemporaryDirectory(prefix="ros3-quickstart-") as directory:
        work = Path(directory)
        entries = run("ros2", "pkg", "executables", PACKAGE, cwd=work)
        available = {
            parts[1]
            for line in entries.splitlines()
            if len(parts := line.split()) == 2 and parts[0] == PACKAGE
        }
        missing = REQUIRED_EXECUTABLES - available
        if missing:
            raise RuntimeError(f"Installed ROS package missing executables: {sorted(missing)}")

        recording = work / "demo.jsonl"
        demo = run(
            sys.executable, "-m", f"{PACKAGE}.demo", "--json", "--record",
            str(recording), cwd=work,
        )
        replay = run(
            sys.executable, "-m", f"{PACKAGE}.replay", str(recording),
            "--json", cwd=work,
        )
        if demo != replay:
            raise RuntimeError("The installed demo and replay outputs do not match")

        events = [json.loads(line) for line in demo.splitlines()]
        if [row.get("state") for row in events[:-1]] != [
            "WAITING", "HEALTHY", "STALE", "HEALTHY"
        ]:
            raise RuntimeError("Unexpected synthetic WAITING/HEALTHY/STALE transitions")
        if events[-1].get("event") != "summary":
            raise RuntimeError("Missing final replay summary")
        if (events[-1]["accepted"], events[-1]["rejected"]) != (51, 0):
            raise RuntimeError("Unexpected default synthetic message counts")

        report = json.loads(
            run(
                sys.executable, "-m", f"{PACKAGE}.evidence", str(recording),
                "--robot-id", "usv01", cwd=work,
            )
        )
        checks = {
            "recording_parsed_to_eof": True,
            "observation_count": 81,
            "payload_observation_count": 51,
            "silence_tick_count": 30,
            "accepted": 51,
            "rejected": 0,
            "final_state": "HEALTHY",
            "observed_stale_to_healthy_recoveries": 1,
        }
        incorrect = {
            key: (report.get(key), expected)
            for key, expected in checks.items()
            if report.get(key) != expected
        }
        if incorrect:
            raise RuntimeError(f"Unexpected synthetic evidence results: {incorrect}")
        if report.get("recording_sha256") != hashlib.sha256(recording.read_bytes()).hexdigest():
            raise RuntimeError("Evidence fingerprint differs from recorded input")

    print(
        "Installed ROS package discovered; demo, replay, and offline evidence matched "
        "(synthetic scenario only)."
    )


if __name__ == "__main__":
    try:
        verify()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"ROS installation smoke check failed: {exc}") from exc
