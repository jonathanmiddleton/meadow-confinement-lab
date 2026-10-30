"""Evaluator correctness tests; synthetic child output is not sandbox evidence."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confinement_lab.witnesses import evaluate_fixture, prepare_fixture


class WitnessEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="witness-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.fixture = prepare_fixture(Path(self.temporary.name) / "case")

    def output(self, outside_status="access_denied", nonce=None):
        nonce = nonce or self.fixture.nonce
        start = {"event": "start", "nonce": nonce, "schema_version": 1}
        finish = {
            "event": "end", "nonce": nonce, "schema_version": 1,
            "inside": {"reached": True, "status": "succeeded"},
            "outside_overwrite": {"reached": True, "status": outside_status,
                                  "error": {"type": "PermissionError", "errno": 13}},
            "outside_create": {"reached": True, "status": outside_status,
                               "error": {"type": "PermissionError", "errno": 13}},
        }
        return json.dumps(start) + "\n" + json.dumps(finish) + "\n"

    def test_enforcement_needs_inside_effect_and_both_observed_denials(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=self.output())
        self.assertEqual(result["status"], "pass")
        self.fixture.outside_new.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=self.output())
        self.assertEqual(result["status"], "fail")

    def test_a_report_cannot_substitute_for_the_inside_write(self):
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=self.output())
        self.assertFalse(result["passed"])

    def test_startup_failure_is_not_a_confinement_pass(self):
        result = evaluate_fixture(
            self.fixture, mode="enforce", returncode=1, stdout="",
            stderr="Starting the CLR failed with HRESULT 80070005.",
        )
        self.assertEqual(result["status"], "not_reached")
        self.assertFalse(result["passed"])

    def test_unexpected_exception_is_not_treated_as_access_denied(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=self.output("error"))
        self.assertEqual(result["status"], "fail")

    def test_denial_label_without_os_denial_evidence_does_not_pass(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        output = self.output().replace('"PermissionError"', '"FileNotFoundError"')
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=output)
        self.assertEqual(result["status"], "fail")

    def test_shell_denial_requires_nonzero_exit_and_exact_target_diagnostic(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        start, end = self.output().splitlines()
        report = json.loads(end)
        targets = {"outside_overwrite": self.fixture.outside_sentinel,
                   "outside_create": self.fixture.outside_new}
        for message, code, expected in (("Operation not permitted", 1, "pass"),
                                        ("Permission denied", 2, "pass"),
                                        ("Permission denied", 0, "fail"),
                                        ("No such file or directory", 1, "fail")):
            with self.subTest(message=message, code=code):
                for operation, target in targets.items():
                    diagnostic = f"probe.sh: line 12: {target}: {message}\n"
                    report[operation]["error"] = {
                        "type": "ShellRedirectionError", "returncode": code,
                        "stderr_base64": base64.b64encode(diagnostic.encode()).decode("ascii"),
                    }
                result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                          stdout=start + "\n" + json.dumps(report))
                self.assertEqual(result["status"], expected)
        for operation in targets:
            report[operation]["error"]["stderr_base64"] = base64.b64encode(
                b"probe.sh: Permission denied: Is a directory\n").decode("ascii")
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=start + "\n" + json.dumps(report))
        self.assertEqual(result["status"], "fail")

    @unittest.skipUnless(os.name == "posix" and Path("/bin/sh").is_file(),
                         "native POSIX shell is unavailable")
    def test_shell_control_writes_exact_binary_bytes_and_reports_environment(self):
        fixture = prepare_fixture(Path(self.temporary.name) / "shell 'quote' \\ ü\ncase",
                                  nonce="nonce 'quote' \\ ü\nend")
        environment = {"HOME": str(fixture.workspace / "home 'quote' ü\n"),
                       "TMPDIR": str(fixture.workspace / "tmp"), "LC_ALL": "C"}
        completed = subprocess.run(["/bin/sh", str(fixture.shell_payload)],
                                   cwd=fixture.workspace, env=environment,
                                   capture_output=True, text=True, timeout=10)
        result = evaluate_fixture(fixture, mode="control", returncode=completed.returncode,
                                  stdout=completed.stdout, stderr=completed.stderr)
        self.assertEqual(result["status"], "pass", (result, completed.stderr))
        self.assertEqual(result["child_report"]["effective_environment_paths"],
                         {name: environment[name] for name in ("HOME", "TMPDIR")})
        for operation in ("inside", "outside_overwrite", "outside_create"):
            self.assertEqual(result["child_report"][operation]["returncode"], 0)

    @unittest.skipUnless(os.name == "posix" and Path("/bin/sh").is_file(),
                         "native POSIX shell is unavailable")
    def test_shell_does_not_classify_a_directory_error_as_denial(self):
        fixture = prepare_fixture(Path(self.temporary.name) / "Permission denied")
        fixture.outside_new.mkdir()
        completed = subprocess.run(["/bin/sh", str(fixture.shell_payload)],
                                   cwd=fixture.workspace, env={"LC_ALL": "C"},
                                   capture_output=True, text=True, timeout=10)
        result = evaluate_fixture(fixture, mode="control", returncode=completed.returncode,
                                  stdout=completed.stdout, stderr=completed.stderr)
        self.assertEqual(result["status"], "fail")
        attempt = result["child_report"]["outside_create"]
        self.assertEqual(attempt["status"], "error")
        self.assertNotEqual(attempt["error"]["returncode"], 0)
        diagnostic = base64.b64decode(attempt["error"]["stderr_base64"])
        self.assertEqual(diagnostic,
                         (fixture.workspace / "shell-outside_create.stderr.bin").read_bytes())

    def test_missing_attempt_is_not_reached(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        start, end = self.output().splitlines()
        report = json.loads(end)
        del report["outside_create"]
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                  stdout=start + "\n" + json.dumps(report))
        self.assertEqual(result["status"], "not_reached")

    def test_nonzero_exit_rejects_otherwise_complete_evidence(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=1,
                                  stdout=self.output())
        self.assertEqual(result["status"], "fail")

    def test_control_requires_actual_outside_writes(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="control", returncode=0,
                                  stdout=self.output("succeeded"))
        self.assertFalse(result["passed"])
        self.fixture.outside_sentinel.write_bytes(self.fixture.written_bytes)
        self.fixture.outside_new.write_bytes(self.fixture.written_bytes)
        result = evaluate_fixture(self.fixture, mode="control", returncode=0,
                                  stdout=self.output("succeeded"))
        self.assertEqual(result["status"], "pass")

    def test_uncorrelated_or_duplicate_report_is_not_accepted(self):
        self.fixture.inside_file.write_bytes(self.fixture.written_bytes)
        for output in (self.output(nonce="different"), self.output() * 2):
            with self.subTest(output=output):
                result = evaluate_fixture(self.fixture, mode="enforce", returncode=0,
                                          stdout=output)
                self.assertFalse(result["passed"])

    def test_outside_change_is_failure_even_without_child_report(self):
        self.fixture.outside_sentinel.write_bytes(b"unexpected mutation")
        result = evaluate_fixture(self.fixture, mode="enforce", returncode=1,
                                  stdout="")
        self.assertEqual(result["status"], "fail")

    def test_prepare_refuses_to_reuse_existing_files(self):
        self.fixture.outside_sentinel.write_bytes(b"retain previous evidence")
        with self.assertRaises(FileExistsError):
            prepare_fixture(self.fixture.root)
        self.assertEqual(self.fixture.outside_sentinel.read_bytes(),
                         b"retain previous evidence")


if __name__ == "__main__":
    unittest.main()
