# SPDX-License-Identifier: Apache-2.0
"""Report conditional timestamp quality for a declared offline sensor inventory."""

import argparse
import json
from pathlib import Path

from .clock_bounds import MAX_INPUT_BYTES, SAMPLE_ID, _constant, _object, evaluate_report


def summarize(manifest):
    """Assess one H21 batch per expected sensor, retaining absent observations."""
    if not isinstance(manifest, dict) or set(manifest) != {"version", "expected", "reports"}:
        raise ValueError("manifest requires version, expected and reports")
    if type(manifest["version"]) is not int or manifest["version"] != 1:
        raise ValueError("unsupported manifest version")
    expected = manifest["expected"]
    if type(expected) is not list or not 1 <= len(expected) <= 16:
        raise ValueError("expected must contain 1 to 16 sensor IDs")
    if any(type(name) is not str or not SAMPLE_ID.fullmatch(name) for name in expected):
        raise ValueError("invalid sensor ID")
    if len(set(expected)) != len(expected):
        raise ValueError("duplicate expected sensor")
    reports = manifest["reports"]
    if type(reports) is not dict or set(reports) - set(expected):
        raise ValueError("reports must map expected sensor IDs to H21 batches")

    sensors = {}
    for name in expected:
        if name not in reports:
            sensors[name] = {"status": "missing_observations", "samples": []}
            continue
        batch = reports[name]
        assessment = evaluate_report(batch)
        samples = [
            {**observation, **result}
            for observation, result in zip(batch["samples"], assessment["results"])
        ]
        sensors[name] = {
            "status": "observed",
            "calibration": batch["calibration"],
            "freshness_limit_s": batch["freshness_limit_s"],
            "samples": samples,
        }
    return {"version": 1, "alignment_verified": False, "sensors": sensors}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.manifest.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError("manifest exceeds 65536 bytes")
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                              parse_constant=_constant)
        print(json.dumps(summarize(manifest), sort_keys=True, allow_nan=False, indent=2))
    except (ValueError, OSError, RecursionError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
