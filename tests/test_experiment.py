"""Policy construction is separate from native confinement evidence."""

from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confinement_lab.experiment import _environment, _policy, default_executor
from confinement_lab.witnesses import prepare_fixture


class ExperimentPolicyTests(unittest.TestCase):
    def test_macos_policy_preserves_argv_and_only_grants_workspace_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = prepare_fixture(Path(temporary) / "space and 'quote")
            environment = _environment(fixture, "Darwin")
            command = ["/bin/sh", str(fixture.workspace / "probe.sh")]
            policy = _policy(fixture, command, environment, "shell", "Darwin")
            self.assertEqual(shlex.split(policy["process"]["commandLine"]), ["exec", *command])
            self.assertEqual(policy["filesystem"]["readwritePaths"], [str(fixture.workspace)])
            self.assertFalse(policy["process"]["inheritDefaultEnv"])
            for name in ("HOME", "TMPDIR", "TMP", "TEMP"):
                self.assertTrue(Path(environment[name]).is_relative_to(fixture.workspace))
            self.assertFalse(policy["seatbelt"]["nestedPty"])
            self.assertNotIn("profileOverride", policy["seatbelt"])
            self.assertEqual(policy["network"]["egress"]["default"], "deny")

    def test_executor_selection_never_substitutes_another_platform_or_architecture(self):
        root = Path("lab")
        for system, machine, expected in (
            ("Windows", "AMD64", "windows-x64/wxc-exec.exe"),
            ("Windows", "ARM64", "windows-arm64/wxc-exec.exe"),
            ("Darwin", "arm64", "macos-arm64/mxc-exec-mac"),
            ("Darwin", "x86_64", "macos-x64/mxc-exec-mac"),
        ):
            with self.subTest(system=system, machine=machine), patch(
                "confinement_lab.experiment.platform.system", return_value=system
            ), patch("confinement_lab.experiment.platform.machine", return_value=machine):
                self.assertEqual(default_executor(root), root / "native" / expected)
        with patch("confinement_lab.experiment.platform.machine", return_value="unknown"):
            with self.assertRaises(ValueError):
                default_executor(root)


if __name__ == "__main__":
    unittest.main()
