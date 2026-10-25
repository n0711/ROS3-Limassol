"""Regression tests for the optional GitLab CI configuration."""

from pathlib import Path
import unittest

from tools.validate_gitlab_ci import CIConfigurationError, REQUIRED_JOBS, validate_config

ROOT = Path(__file__).resolve().parents[1]


class GitLabCIConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")

    def test_committed_pipeline_has_all_required_jobs(self) -> None:
        self.assertEqual(validate_config(self.pipeline), len(REQUIRED_JOBS))

    def test_duplicate_mapping_key_is_rejected(self) -> None:
        with self.assertRaisesRegex(CIConfigurationError, "duplicate YAML key"):
            validate_config(self.pipeline + "\nstages: [verify]\n")

    def test_missing_ros_distro_job_is_rejected(self) -> None:
        altered = self.pipeline.replace("ros2-jazzy:\n", "ros2-other:\n", 1)
        self.assertNotEqual(altered, self.pipeline)
        with self.assertRaisesRegex(CIConfigurationError, "required CI job missing: ros2-jazzy"):
            validate_config(altered)

    def test_loss_of_rust_parity_coverage_is_rejected(self) -> None:
        altered = self.pipeline.replace("python3 robotics/ros3_core/tests/parity.py", "echo skipped-parity", 1)
        self.assertNotEqual(altered, self.pipeline)
        with self.assertRaisesRegex(CIConfigurationError, "missing coverage command: parity.py"):
            validate_config(altered)

    def test_non_string_script_entry_is_rejected(self) -> None:
        altered = self.pipeline.replace("- npm ci", "- {run: npm ci}", 1)
        self.assertNotEqual(altered, self.pipeline)
        with self.assertRaisesRegex(CIConfigurationError, "script must be a non-empty list"):
            validate_config(altered)

    def test_invalid_stage_is_rejected(self) -> None:
        altered = self.pipeline.replace("stage: integration", "stage: deployment", 1)
        self.assertNotEqual(altered, self.pipeline)
        with self.assertRaisesRegex(CIConfigurationError, "must run in 'integration' stage"):
            validate_config(altered)


if __name__ == "__main__":
    unittest.main()
