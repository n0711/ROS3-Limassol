#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H20: collect a versioned, checksummed bundle of offline synthetic evidence.

Run this on a target computer to obtain *that computer's* measurements.
CI smoke tests are NOT measurements from a Raspberry Pi 3B.
The collector does not access USB devices, serial ports or radio links.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


# Each subprocess retains its own bounded workload and input validation.
# The normal preset is designed for an unmodified Raspberry Pi 3B.
RUNS = {
    "h14": ("benchmark_h14.py",
            ["--sizes", "1024", "2048", "4096", "8192",
             "--repeats", "3"]),
    "h16": ("benchmark_h16.py",
            ["--robots", "1", "2", "4", "8", "16",
             "--ticks", "24", "--repeats", "3", "--window", "32"]),
    "h17": ("benchmark_h17.py",
            ["--windows", "8", "64", "256",
             "--samples", "256", "--repeats", "3"]),
    "h18": ("benchmark_ring_h18.py",
            ["--windows", "8", "32", "128", "512",
             "--samples", "1024", "--repeats", "3"]),
    "h19": ("exhaustive_ring_h19.py",
            ["--depth", "4", "--windows", "1", "2", "4"]),
}
QUICK_RUNS = {
    "h14": ("benchmark_h14.py",
            ["--sizes", "8", "16", "--repeats", "1"]),
    "h16": ("benchmark_h16.py",
            ["--robots", "1", "2", "--ticks", "8", "--repeats", "1"]),
    "h17": ("benchmark_h17.py",
            ["--windows", "2", "8", "--samples", "16", "--repeats", "1"]),
    "h18": ("benchmark_ring_h18.py",
            ["--windows", "2", "8", "--samples", "24", "--repeats", "1"]),
    "h19": ("exhaustive_ring_h19.py",
            ["--depth", "2", "--windows", "1", "2"]),
}
TIMEOUT_SECONDS = 420


def _read_git(root, args):
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _device_model():
    path = Path("/proc/device-tree/model")
    try:
        # Read at most 256 bytes; this is a hardware label, not a unique ID.
        return path.open("rb").read(256).decode(
            "utf-8", errors="replace").rstrip("\x00")
    except OSError:
        return None


def _reject_constant(value):
    raise ValueError(f"nonfinite JSON constant {value}")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def validate_report(name, text):
    """Reject unexpected source data and any new validation claim."""
    report = json.loads(
        text, parse_constant=_reject_constant, object_pairs_hook=_unique_object,
    )
    if not isinstance(report, dict) or type(report.get("schema_version")) is not int:
        raise ValueError(f"{name}: invalid report envelope")
    if report["schema_version"] != 1:
        raise ValueError(f"{name}: unsupported report schema")
    expected = ("synthetic_exhaustive_bounded" if name == "h19"
                else "synthetic_offline")
    if report.get("source") != expected:
        raise ValueError(f"{name}: source is not the declared synthetic mode")
    claims = report.get("claims")
    if not isinstance(claims, dict) or not claims:
        raise ValueError(f"{name}: missing explicit claim boundaries")
    if any(value is not False for value in claims.values()):
        raise ValueError(f"{name}: unexpected affirmative validation claim")
    if name == "h19":
        if report.get("mismatches") != 0:
            raise ValueError("H19 sequence equivalence mismatches")
    elif not isinstance(report.get("measurements"), list) or not report["measurements"]:
        raise ValueError(f"{name}: missing measurements")
    return report


def collect(output_dir, *, quick=False):
    """Write an exclusive evidence directory; manifest marks complete bundles."""
    root = Path(__file__).resolve().parents[1]
    tools = root / "tools"
    presets = QUICK_RUNS if quick else RUNS

    # Deliberately refuse existing paths to preserve prior experiment evidence.
    output_dir.mkdir(parents=False, exist_ok=False)
    commit = _read_git(root, ["rev-parse", "--verify", "HEAD"])
    tracked_changes = _read_git(
        root, ["status", "--porcelain", "--untracked-files=no"])
    manifest = {
        "schema_version": 1,
        "experiment": "H20 offline evidence capture",
        "completed": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "synthetic_offline",
        "run_mode": "quick_ci_smoke" if quick else "target_offline",
        "git_commit": commit,
        "tracked_repository_clean": (
            tracked_changes == "" if tracked_changes is not None else None),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
            "platform": platform.platform(),
            "cpu_count_reported": os.cpu_count(),
            "device_model_label": _device_model(),
        },
        "reports": {},
        "claims": {
            "pi_3b_verified_by_collector": False,
            "hard_realtime_guarantee": False,
            "physical_link_validated": False,
            "production_ring_migrated": False,
            "asymptotic_complexity_proven_by_timing": False,
        },
        "interpretation": (
            "Measurements describe only the environment that executed this "
            "tool. Device model is a label, not authenticated identity. "
            "An intact manifest shows the five synthetic commands succeeded, "
            "not that real-time or physical-link performance is established."
        ),
    }
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    for name, (script, arguments) in presets.items():
        command = [sys.executable, str(tools / script), *arguments]
        try:
            result = subprocess.run(
                command, cwd=root, env=env, capture_output=True, text=True,
                timeout=TIMEOUT_SECONDS, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{name} execution failed: {exc}") from exc
        if result.returncode != 0:
            # A missing manifest means an incomplete bundle. Preserve the
            # failure output for diagnosis without claiming successful data.
            (output_dir / "FAILED.txt").write_text(
                f"{name}: exit code {result.returncode}\n" +
                result.stderr[:8192], encoding="utf-8")
            raise RuntimeError(f"{name}: benchmark failed (see FAILED.txt)")
        if len(result.stdout.encode("utf-8")) > 2_000_000:
            raise ValueError(f"{name}: report is unexpectedly large")
        validate_report(name, result.stdout)
        raw = result.stdout.encode("utf-8")
        with (output_dir / f"{name}.json").open("xb") as handle:
            handle.write(raw)
        manifest["reports"][name] = {
            "file": f"{name}.json",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "command": [script, *arguments],
        }
    with (output_dir / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, allow_nan=False, indent=2)
        handle.write("\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="new directory; existing paths are refused")
    parser.add_argument("--quick", action="store_true",
                        help="tiny workloads for automated test smoke checks")
    options = parser.parse_args(argv)
    try:
        result = collect(options.output_dir, quick=options.quick)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Captured {len(result['reports'])} synthetic reports in "
          f"{options.output_dir} (manifest.json).")


if __name__ == "__main__":
    main()
