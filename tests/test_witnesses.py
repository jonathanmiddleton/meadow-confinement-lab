"""Evaluator correctness tests; synthetic child output is not sandbox evidence."""

import json
from pathlib import Path
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
