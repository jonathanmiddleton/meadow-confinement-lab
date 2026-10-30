"""Behavioral checks for the read-only environment report."""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confinement_lab.environment import collect_environment


class EnvironmentReportTests(unittest.TestCase):
    def test_report_does_not_capture_unrelated_environment_secrets(self):
        secret = "environment-secret-that-must-never-appear-4f29"
        with patch.dict(os.environ, {"LAB_TEST_CREDENTIAL": secret}):
            report = collect_environment()
        self.assertNotIn(secret, json.dumps(report))
        self.assertNotIn("LAB_TEST_CREDENTIAL", json.dumps(report))

    def test_discovery_does_not_execute_discovered_programs(self):
        with patch.object(
            subprocess, "Popen", side_effect=AssertionError("unexpected process")
        ), patch.object(os, "system", side_effect=AssertionError("unexpected shell")):
            report = collect_environment()
        self.assertIsInstance(json.dumps(report), str)
        self.assertIn(report["privileges"]["status"],
                      {"elevated", "non_elevated", "unknown"})

    def test_unknown_platform_does_not_claim_non_elevated_execution(self):
        with patch("platform.system", return_value="UnrecognizedOS"):
            report = collect_environment()
        self.assertEqual(report["os"]["system"], "UnrecognizedOS")
        self.assertEqual(report["privileges"]["status"], "unknown")
        self.assertEqual(report["privileges"]["reason"], "unsupported_platform")


if __name__ == "__main__":
    unittest.main()
