# SPDX-License-Identifier: Apache-2.0
"""H20 offline capture/verification regression; does not probe Pi hardware."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CAPTURE = PACKAGE_ROOT / "tools" / "capture_h20.py"
VERIFY = PACKAGE_ROOT / "tools" / "verify_h20.py"
REPORTS = {"h14", "h16", "h17", "h18", "h19"}


def run_tool(script, *args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(script), *map(str, args)],
        cwd=PACKAGE_ROOT, env=env, capture_output=True, text=True,
        timeout=90, check=False,
    )


class H20EvidenceBundleTests(unittest.TestCase):
    def test_capture_verify_hashes_and_preserve_negative_claims(self):
        with tempfile.TemporaryDirectory() as work:
            destination = Path(work) / "evidence"
            captured = run_tool(
                CAPTURE, "--quick", "--output-dir", destination)
            self.assertEqual(captured.returncode, 0, captured.stderr)
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["completed"])
            self.assertEqual(manifest["run_mode"], "quick_ci_smoke")
            self.assertEqual(set(manifest["reports"]), REPORTS)
            self.assertFalse(manifest["claims"]["pi_3b_verified_by_collector"])
            self.assertFalse(manifest["claims"]["physical_link_validated"])
            self.assertFalse(manifest["claims"]["production_ring_migrated"])

            for name in REPORTS:
                content = (destination / f"{name}.json").read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(),
                                 manifest["reports"][name]["sha256"])
                report = json.loads(content)
                self.assertTrue(all(
                    value is False for value in report["claims"].values()))
            verified = run_tool(VERIFY, destination)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            status = json.loads(verified.stdout)
            self.assertTrue(status["bundle_integrity_verified"])
            self.assertEqual(status["reports_checked"], 5)
            self.assertFalse(status["host_identity_authenticated"])
            self.assertFalse(status["hardware_measured"])

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as work:
            location = Path(work) / "existing"
            location.mkdir()
            sentinel = location / "manifest.json"
            sentinel.write_text("pre-existing evidence", encoding="utf-8")
            result = run_tool(CAPTURE, "--quick", "--output-dir", location)
            self.assertEqual(result.returncode, 2)
            self.assertIn("error:", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"),
                             "pre-existing evidence")

    def test_verifier_detects_modified_report(self):
        with tempfile.TemporaryDirectory() as work:
            destination = Path(work) / "evidence"
            result = run_tool(CAPTURE, "--quick", "--output-dir", destination)
            self.assertEqual(result.returncode, 0, result.stderr)
            location = destination / "h18.json"
            original = location.read_bytes()
            self.assertTrue(original.startswith(b"{"))
            # Preserve file length to exercise the SHA-256 check itself.
            location.write_bytes(b"[" + original[1:])
            checked = run_tool(VERIFY, destination)
            self.assertEqual(checked.returncode, 2)
            self.assertEqual(checked.stdout, "")
            self.assertIn("SHA-256 mismatch", checked.stderr)
            self.assertNotIn("Traceback", checked.stderr)

    def test_verifier_rejects_incomplete_manifest_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as work:
            destination = Path(work) / "evidence"
            destination.mkdir()
            manifest_path = destination / "manifest.json"
            manifest_path.write_text(
                json.dumps({"schema_version": 1, "completed": False}),
                encoding="utf-8",
            )
            incomplete = run_tool(VERIFY, destination)
            self.assertEqual(incomplete.returncode, 2)
            self.assertEqual(incomplete.stdout, "")
            self.assertNotIn("Traceback", incomplete.stderr)

            manifest = {
                "schema_version": 1,
                "completed": True,
                "source": "synthetic_offline",
                "run_mode": "quick_ci_smoke",
                "claims": {"physical_link_validated": False},
                "reports": {name: {"file": "../../leak.json"}
                            for name in REPORTS},
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            unsafe = run_tool(VERIFY, destination)
            self.assertEqual(unsafe.returncode, 2)
            self.assertIn("unsafe report filename", unsafe.stderr)
            self.assertEqual(unsafe.stdout, "")

    def test_cli_requires_output_directory(self):
        result = run_tool(CAPTURE, "--quick")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("required", result.stderr)


if __name__ == "__main__":
    unittest.main()
