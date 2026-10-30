"""Real unconfined worker controls exercise the controller and its oracle."""

import copy
from pathlib import Path
import platform
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confinement_lab.experiment import _environment
from confinement_lab.worker_experiment import (
    evaluate_worker_case, prepare_worker_fixture, run_worker_case, worker_policy,
)

SOURCE = Path(__file__).resolve().parents[1] / "src" / "confinement_lab"


class WorkerExperimentTests(unittest.TestCase):
    def test_real_control_completes_requests_and_is_not_misclassified_as_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = prepare_worker_fixture(Path(directory) / "space and 'quote", SOURCE)
            case = run_worker_case(fixture, "control", platform.system(), None)
            self.assertTrue(case["qualifies"], case["evaluation"])
            self.assertEqual(case["evaluation"]["completed_requests"], 11)
            mistaken = evaluate_worker_case(fixture, "enforce", case["transcript"], case["execution"], None)
            self.assertFalse(mistaken["passed"])
            self.assertIn("read-private: no reached OS permission denial", mistaken["failures"])
            self.assertIn("private file creation escaped", mistaken["failures"])
            # An outside effect stays a failure even when a tool receipt claims otherwise.
            altered = copy.deepcopy(case["transcript"])
            for frame in altered:
                if frame.get("id") in {"write-reference", "write-private", "create-private", "read-private"}:
                    frame.update(ok=False, error={"stage": "operation", "type": "PermissionError", "errno": 13})
            mistaken = evaluate_worker_case(fixture, "enforce", altered, case["execution"], None)
            self.assertFalse(mistaken["passed"])
            self.assertIn("private/mutable.bin: independent bytes mismatch", mistaken["failures"])
            duplicate = evaluate_worker_case(fixture, "control", [*case["transcript"], case["transcript"][1]], case["execution"], None)
            self.assertFalse(duplicate["passed"])
            self.assertIn("duplicate response identities", duplicate["failures"])

    def test_startup_failure_and_unchanged_fixtures_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = prepare_worker_fixture(Path(directory) / "case", SOURCE)
            (fixture.private / "controller.log").write_text("controller-start\ncontroller-finish\n")
            outcome = evaluate_worker_case(fixture, "enforce", [], {"returncode": 1}, "not started")
            self.assertFalse(outcome["passed"])
            self.assertIn("worker readiness absent", outcome["failures"])

    def test_fixture_inside_interpreter_read_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = prepare_worker_fixture(Path(directory) / "case", SOURCE)
            environment = _environment(fixture, platform.system())
            with self.assertRaisesRegex(ValueError, "overlaps a worker read grant"):
                worker_policy(fixture, [str(fixture.root / "python")], environment, platform.system())


if __name__ == "__main__":
    unittest.main()
