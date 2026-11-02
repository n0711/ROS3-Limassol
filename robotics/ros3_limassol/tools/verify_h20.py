#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""H20: verify local evidence bundle hashes and synthetic report contracts.

SHA-256 detects accidental modification but does not authenticate authorship,
hardware identity, execution environment or physical-link validation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re

from capture_h20 import QUICK_RUNS, RUNS, validate_report

MAX_MANIFEST_BYTES = 128_000
MAX_REPORT_BYTES = 2_000_000


def _unique(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate manifest key: {key}")
        data[key] = value
    return data


def verify(directory):
    location = Path(directory)
    with (location / "manifest.json").open("rb") as stream:
        raw_manifest = stream.read(MAX_MANIFEST_BYTES + 1)
    if len(raw_manifest) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds 128000 bytes")
    try:
        manifest = json.loads(raw_manifest.decode("utf-8"),
                              object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("invalid UTF-8 manifest JSON") from exc
    if not isinstance(manifest, dict) or (
            type(manifest.get("schema_version")) is not int or
            manifest["schema_version"] != 1 or
            manifest.get("completed") is not True or
            manifest.get("source") != "synthetic_offline"):
        raise ValueError("bundle is not a completed H20 synthetic bundle")
    preset = {
        "quick_ci_smoke": QUICK_RUNS,
        "target_offline": RUNS,
    }.get(manifest.get("run_mode"))
    if preset is None:
        raise ValueError("unrecognized H20 run mode")
    claims = manifest.get("claims")
    if not isinstance(claims, dict) or not claims or any(
            value is not False for value in claims.values()):
        raise ValueError("H20 manifest has unsupported validation claim")
    reports = manifest.get("reports")
    if not isinstance(reports, dict) or set(reports) != set(preset):
        raise ValueError("H20 manifest is missing expected reports")
    for name, (script, args) in preset.items():
        entry = reports[name]
        if not isinstance(entry, dict) or entry.get("file") != f"{name}.json":
            raise ValueError(f"{name}: invalid or unsafe report filename")
        if entry.get("command") != [script, *args]:
            raise ValueError(f"{name}: command does not match preset")
        digest = entry.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(
                r"[a-f0-9]{64}", digest):
            raise ValueError(f"{name}: malformed hash")
        with (location / f"{name}.json").open("rb") as stream:
            data = stream.read(MAX_REPORT_BYTES + 1)
        if len(data) > MAX_REPORT_BYTES:
            raise ValueError(f"{name}: report exceeds 2 million bytes")
        if type(entry.get("bytes")) is not int or entry["bytes"] != len(data):
            raise ValueError(f"{name}: byte count mismatch")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"{name}: SHA-256 mismatch")
        try:
            validate_report(name, data.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise ValueError(f"{name}: invalid recorded report") from exc
    return {
        "schema_version": 1,
        "bundle_integrity_verified": True,
        "reports_checked": len(preset),
        "host_identity_authenticated": False,
        "hardware_measured": False if manifest["run_mode"] == "quick_ci_smoke"
                             else None,
        "physical_link_validated": False,
        "interpretation": (
            "Exact file hashes and report contracts verified, not benchmark "
            "reproducibility or hardware identity. Target_offline measurements "
            "must still be attributed to the machine that actually ran them."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    options = parser.parse_args(argv)
    try:
        result = verify(options.directory)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
