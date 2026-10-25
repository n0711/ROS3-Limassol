"""Offline smoke checks for the optional GitLab mirror pipeline.

This does not replace GitLab CI Lint, GitLab project-context validation, or
execution on a GitLab Runner. Run with: python tools/validate_gitlab_ci.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]

# The jobs below form the cross-project CI coverage contract. If the pipeline
# is refactored, update this contract and its tests in the same change.
REQUIRED_JOBS = {
    "ros3-python-310": ("verify", ("unittest discover", "check_wheel.py")),
    "ros3-python-312": ("verify", ("unittest discover", "check_wheel.py")),
    "ros3-rust": ("verify", ("cargo fmt", "cargo clippy", "cargo test", "parity.py")),
    "academic-python": ("verify", ("python -m pytest",)),
    "academic-rust": ("verify", ("cargo test",)),
    "learntwin-frontend": ("verify", ("npm ci", "npm test", "npm run lint", "npm run build")),
    "ros2-humble": ("integration", ("/opt/ros/humble/setup.bash", "colcon test", "colcon test-result")),
    "ros2-jazzy": ("integration", ("/opt/ros/jazzy/setup.bash", "colcon test", "colcon test-result")),
}


class CIConfigurationError(ValueError):
    """Raised for invalid YAML or CI coverage contracts."""


class UniqueKeysLoader(yaml.SafeLoader):
    """Load YAML while rejecting duplicate mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected mapping", node.start_mark)
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                repeated = key in result
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(None, None, "unhashable YAML key", key_node.start_mark) from exc
            if repeated:
                raise yaml.constructor.ConstructorError(None, node.start_mark, f"duplicate YAML key: {key!r}", key_node.start_mark)
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def validate_config(source: str) -> int:
    """Return number of checked jobs or raise CIConfigurationError."""
    try:
        config = yaml.load(source, Loader=UniqueKeysLoader)
    except yaml.YAMLError as exc:
        raise CIConfigurationError(f"invalid YAML: {exc}") from exc
    if not isinstance(config, dict):
        raise CIConfigurationError("CI document must be a YAML mapping")

    stages = config.get("stages")
    if not isinstance(stages, list) or not stages or not all(isinstance(s, str) and s for s in stages):
        raise CIConfigurationError("stages must be a non-empty list of strings")
    if len(stages) != len(set(stages)):
        raise CIConfigurationError("stages must not contain duplicates")

    workflow = config.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("rules"), list) or not workflow["rules"]:
        raise CIConfigurationError("workflow.rules must contain at least one rule")

    for job_name, (expected_stage, commands) in REQUIRED_JOBS.items():
        job = config.get(job_name)
        if not isinstance(job, dict):
            raise CIConfigurationError(f"required CI job missing: {job_name}")
        stage = job.get("stage")
        if stage not in stages or stage != expected_stage:
            raise CIConfigurationError(f"{job_name} must run in {expected_stage!r} stage")
        image = job.get("image")
        if not isinstance(image, str) or not image.strip():
            raise CIConfigurationError(f"{job_name}.image must be a non-empty image name")
        script = job.get("script")
        if not isinstance(script, list) or not script or not all(isinstance(command, str) and command.strip() for command in script):
            raise CIConfigurationError(f"{job_name}.script must be a non-empty list of command strings")
        all_commands = "\n".join(script)
        for command in commands:
            if command not in all_commands:
                raise CIConfigurationError(f"{job_name} is missing coverage command: {command}")
    return len(REQUIRED_JOBS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=ROOT / ".gitlab-ci.yml")
    args = parser.parse_args()
    try:
        checked = validate_config(args.path.read_text(encoding="utf-8"))
    except (CIConfigurationError, OSError) as exc:
        print(f"GitLab CI offline smoke check FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"GitLab CI offline smoke check passed: {checked} required jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
