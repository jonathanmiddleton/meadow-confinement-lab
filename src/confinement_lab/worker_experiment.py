"""Persistent process-boundary witness, independent of model tool selection.

The worker and command payloads are controlled probes, not hostile peers. Their
nonces correlate receipts; they do not authenticate adversarial IPC. Independent
file observations and paired controls supplement actual OS denial results.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any
from uuid import uuid4

from confinement_lab.bundle import verify_executor
from confinement_lab.environment import collect_environment
from confinement_lab.experiment import (
    _backend_events, _environment, _policy, _source_hashes, _write_json, default_executor,
)

PREFIX = b"MCL_WORKER_V1 "


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@dataclass(frozen=True)
class WorkerFixture:
    root: Path
    workspace: Path
    reference: Path
    private: Path
    code: Path
    token: str
    initial: dict[str, bytes]


def prepare_worker_fixture(root: Path, source: Path) -> WorkerFixture:
    root.mkdir(parents=True, exist_ok=False)
    initial = {}
    for area in ("workspace", "reference", "private"):
        (root / area).mkdir()
        for name in ("input.bin", "mutable.bin", "child.bin", "grandchild.bin"):
            data = f"fixture:{area}:{name}:{uuid4().hex}".encode()
            (root / area / name).write_bytes(data)
            initial[f"{area}/{name}"] = data
    code = root / "executor-code"
    code.mkdir()
    for name in ("tool_worker.py", "worker_descendant.py"):
        shutil.copyfile(source / name, code / name)
    fixture = WorkerFixture(root, root / "workspace", root / "reference", root / "private",
                            code, uuid4().hex, initial)
    _write_json(root / "fixture.json", {
        "root": str(root), "session": fixture.token,
        "initial_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in initial.items()},
        "payload_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in code.glob("*.py")},
    })
    return fixture


def worker_policy(fixture: WorkerFixture, command: list[str], environment: dict[str, str],
                  system: str) -> dict:
    policy = _policy(fixture, command, environment, "python", system)
    policy["process"]["timeout"] = 60000
    policy["filesystem"]["readonlyPaths"].extend([str(fixture.reference), str(fixture.code)])
    # Private fixtures must not sit inside a broad interpreter/code read grant.
    for root in policy["filesystem"]["readonlyPaths"]:
        if fixture.private.is_relative_to(Path(root).resolve()):
            raise ValueError("Private fixture overlaps a worker read grant: " + root)
    policy["network"] = {"egress": {"default": "allow"},
                         "ingress": {"default": "allow", "hostLoopback": "allow"}}
    return policy


def requests_for(f: WorkerFixture) -> list[dict]:
    def request(identifier: str, operation: str, **arguments: Any) -> dict:
        return {"id": identifier, "operation": operation, **arguments}
    data = _b64(f"{f.token}:worker-write".encode())
    return [
        request("read-workspace", "read", path=str(f.workspace / "input.bin")),
        request("read-reference", "read", path=str(f.reference / "input.bin")),
        request("write-workspace", "write", path=str(f.workspace / "created.bin"), data_base64=data),
        request("write-reference", "write", path=str(f.reference / "mutable.bin"), data_base64=data),
        request("read-private", "read", path=str(f.private / "input.bin")),
        request("write-private", "write", path=str(f.private / "mutable.bin"), data_base64=data),
        request("create-private", "write", path=str(f.private / "created.bin"), data_base64=data),
        request("after-denial", "write", path=str(f.workspace / "recovery.bin"), data_base64=data),
        request("descendants", "run_command", argv=[sys.executable, "-I", "-S", "-B",
                str(f.code / "worker_descendant.py"), str(f.root), "child", f.token],
                cwd=str(f.workspace), timeout_seconds=15),
        request("read-after-command", "read", path=str(f.workspace / "recovery.bin")),
        request("shutdown", "shutdown"),
    ]


class WorkerChannel:
    """Drain both OS pipes while delivering only correlated worker frames."""

    def __init__(self, command: list[str], fixture: WorkerFixture, env: dict[str, str]):
        self.fixture = fixture
        self.frames: queue.Queue[dict | BaseException | None] = queue.Queue()
        self.started = time.monotonic()
        self.process = subprocess.Popen(command, cwd=fixture.workspace, env=env,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, close_fds=True)
        self.threads = []
        for name in ("stdout", "stderr"):
            thread = threading.Thread(target=self._drain, args=(name,), daemon=True)
            thread.start()
            self.threads.append(thread)

    def _drain(self, name: str) -> None:
        stream = getattr(self.process, name)
        try:
            with (self.fixture.root / f"execution.{name}.bin").open("wb") as output:
                for line in iter(stream.readline, b""):
                    output.write(line)
                    output.flush()
                    if name == "stdout" and line.startswith(PREFIX):
                        self.frames.put(json.loads(line[len(PREFIX):]))
        except BaseException as error:
            self.frames.put(error)
        finally:
            stream.close()
            if name == "stdout":
                self.frames.put(None)

    def receive(self, kind: str, identifier: str | None = None) -> dict:
        timeout = min(25, max(0.01, 70 - (time.monotonic() - self.started)))
        try:
            frame = self.frames.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("Worker response deadline exceeded") from None
        if isinstance(frame, BaseException):
            raise RuntimeError("Worker output could not be decoded") from frame
        if not isinstance(frame, dict):
            raise RuntimeError("Worker exited before the required response")
        if (frame.get("version") != 1 or frame.get("session") != self.fixture.token
                or frame.get("kind") != kind or (identifier is not None and frame.get("id") != identifier)):
            raise RuntimeError("Unexpected or uncorrelated worker frame")
        return frame

    def request(self, request: dict) -> dict:
        self.process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode())
        self.process.stdin.flush()
        return self.receive("response", request["id"])

    def finish(self) -> dict:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        forced = False
        try:
            # Let native policy timeout own its group cleanup before force-killing
            # the helper; killing just the helper is not descendant-cleanup proof.
            self.process.wait(timeout=max(5, 70 - (time.monotonic() - self.started)))
        except subprocess.TimeoutExpired:
            forced = True
            self.process.kill()
            self.process.wait(timeout=5)
        for thread in self.threads:
            thread.join(timeout=2)
        return {"returncode": self.process.returncode, "forced_helper_termination": forced,
                "pipe_readers_finished": all(not thread.is_alive() for thread in self.threads),
                "duration_seconds": time.monotonic() - self.started}


def _denied(response: dict) -> bool:
    error = response.get("error", {})
    return (response.get("ok") is False and error.get("stage") == "operation"
            and error.get("type") == "PermissionError"
            and (error.get("errno") in (1, 13) or error.get("winerror") == 5))


def evaluate_worker_case(f: WorkerFixture, mode: str, transcript: list[dict],
                         execution: dict, protocol_error: str | None) -> dict:
    failures = []
    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)
    frames = {frame.get("id"): frame for frame in transcript if frame.get("kind") == "response"}
    check(protocol_error is None, "protocol/startup failure: " + str(protocol_error))
    check(execution.get("returncode") == 0 and not execution.get("forced_helper_termination"),
          "native invocation did not exit normally with zero")
    check(execution.get("pipe_readers_finished") is True, "output pipes did not settle")
    check(len(frames) == len(requests_for(f)), "not every request completed exactly once")
    check(len([frame for frame in transcript if frame.get("kind") == "response"]) == len(frames),
          "duplicate response identities")
    pids = {frame.get("pid") for frame in transcript}
    check(len(pids) == 1 and all(type(pid) is int and pid > 0 for pid in pids),
          "requests did not come from one persistent worker")
    check(any(frame.get("kind") == "ready" for frame in transcript), "worker readiness absent")
    check(any(frame.get("kind") == "bye" for frame in transcript), "worker shutdown absent")
    write_data = f"{f.token}:worker-write".encode()
    denied_ids = {"write-reference", "read-private", "write-private", "create-private"}
    for request in requests_for(f):
        identifier = request["id"]
        response = frames.get(identifier, {})
        check(response.get("operation") == request["operation"], identifier + ": wrong operation")
        if mode == "enforce" and identifier in denied_ids:
            check(_denied(response), identifier + ": no reached OS permission denial")
        else:
            check(response.get("ok") is True, identifier + ": useful operation failed")
        if request["operation"] == "read" and not (mode == "enforce" and identifier == "read-private"):
            path = Path(request["path"])
            expected = write_data if identifier == "read-after-command" else f.initial[path.relative_to(f.root).as_posix()]
            check(response.get("result", {}).get("data_base64") == _b64(expected), identifier + ": wrong read bytes")
    descendants = {}
    command_result = frames.get("descendants", {}).get("result", {})
    try:
        check(command_result.get("returncode") == 0, "command did not exit zero")
        descendants = json.loads(base64.b64decode(command_result.get("stdout_base64", ""), validate=True))
        child = descendants
        grandchild = descendants["grandchild"]
        check(child["grandchild_returncode"] == 0, "grandchild did not exit zero")
        check(len({child["pid"], grandchild["pid"], next(iter(pids))}) == 3,
              "child/grandchild did not have distinct process identities")
        for level, payload in (("child", child), ("grandchild", grandchild)):
            check(payload.get("level") == level, "descendant level mismatch")
            rows = payload.get("operations", [])
            check([(row.get("area"), row.get("operation")) for row in rows]
                  == [(area, op) for area in ("workspace", "reference", "private") for op in ("read", "write")],
                  level + ": missing or duplicate operations")
            for row in rows:
                area, op = row["area"], row["operation"]
                denied = mode == "enforce" and (area == "private" or (area == "reference" and op == "write"))
                check(_denied(row) if denied else row.get("ok") is True, f"{level}:{area}:{op}: unexpected outcome")
                if op == "read" and not denied:
                    check(row.get("data_base64") == _b64(f.initial[f"{area}/input.bin"]),
                          f"{level}:{area}: wrong read bytes")
    except (ValueError, KeyError, TypeError, StopIteration):
        check(False, "child/grandchild receipt absent or malformed")
    observations = {}
    expected_files = dict(f.initial)
    expected_files["workspace/created.bin"] = write_data
    expected_files["workspace/recovery.bin"] = write_data
    if mode == "control":
        expected_files.update({"reference/mutable.bin": write_data, "private/mutable.bin": write_data,
                               "private/created.bin": write_data})
    for level in ("child", "grandchild"):
        for area in ("workspace", "reference", "private"):
            if mode == "control" or area == "workspace":
                expected_files[f"{area}/{level}.bin"] = f"{f.token}:{level}:{area}".encode()
    for name, expected in expected_files.items():
        path = f.root / name
        actual = path.read_bytes() if path.is_file() else None
        observations[name] = {"exists": actual is not None,
                              "sha256": hashlib.sha256(actual).hexdigest() if actual is not None else None,
                              "matches_expected": actual == expected}
        check(actual == expected, name + ": independent bytes mismatch")
    if mode == "enforce":
        exists = (f.private / "created.bin").exists()
        observations["private/created.bin"] = {"exists": exists, "expected_absent": True,
                                                "matches_expected": not exists}
        check(not exists, "private file creation escaped")
    expected_log = ["controller-start", *[request["id"] for request in requests_for(f)], "controller-finish"]
    observed_log = (f.private / "controller.log").read_text().splitlines()
    check(observed_log == expected_log, "controller did not retain private logging authority")
    return {"status": "pass" if not failures else "fail", "passed": not failures,
            "failures": failures, "worker_pid": next(iter(pids)) if len(pids) == 1 else None,
            "completed_requests": len(frames), "filesystem_observations": observations,
            "descendants": descendants, "controller_log_matches": observed_log == expected_log}


def run_worker_case(f: WorkerFixture, mode: str, system: str, executor: Path | None) -> dict:
    environment = _environment(f, system)
    command = [sys.executable, "-I", "-S", "-B", "-u", str(f.code / "tool_worker.py"), "--session", f.token]
    policy = worker_policy(f, command, environment, system)
    _write_json(f.root / "policy.json", policy)
    if mode == "enforce":
        command = [str(executor), "--config", str(f.root / "policy.json"), "--log-file", str(f.root / "mxc.log")]
    requests = requests_for(f)
    _write_json(f.root / "requests.json", requests)
    case = {"name": "worker-" + mode, "mode": mode, "command": command,
            "environment": environment, "policy": policy, "transcript": [], "qualifies": False}
    log = f.private / "controller.log"
    log.write_text("controller-start\n")
    channel = None
    protocol_error = None
    execution = {}
    try:
        channel = WorkerChannel(command, f, environment)
        case["transcript"].append(channel.receive("ready"))
        for request in requests:
            case["transcript"].append(channel.request(request))
            _write_json(f.root / "transcript.json", case["transcript"])
            with log.open("a") as output:
                output.write(request["id"] + "\n")
        case["transcript"].append(channel.receive("bye"))
    except (OSError, RuntimeError, ValueError) as error:
        protocol_error = str(error)
    finally:
        if channel is not None:
            execution = channel.finish()
        with log.open("a") as output:
            output.write("controller-finish\n")
        _write_json(f.root / "transcript.json", case["transcript"])
    case.update(execution=execution, protocol_error=protocol_error)
    case["evaluation"] = evaluate_worker_case(f, mode, case["transcript"], execution, protocol_error)
    if mode == "enforce":
        if system == "Windows":
            events = _backend_events(f.root / "mxc.log")
            case["backend_events"] = events
            case["native_backend_observed"] = any(event.get("event") == "mxc.ProcessExited"
                and event.get("backend") == "processcontainer" and event.get("tier") == "base-container"
                and event.get("exit_code") == 0 and event.get("pid") == case["evaluation"]["worker_pid"]
                for event in events)
        else:
            native_log = (f.root / "mxc.log").read_text(errors="replace") if (f.root / "mxc.log").is_file() else ""
            case["native_backend_observed"] = ("Seatbelt: --- end generated profile ---" in native_log
                and "Seatbelt: applying sandbox via sandbox_init" in native_log
                and execution.get("returncode") == 0 and bool(case["transcript"]))
    else:
        case["native_backend_observed"] = None
    case["qualifies"] = case["evaluation"]["passed"] and (mode == "control" or case["native_backend_observed"])
    _write_json(f.root / "case.json", case)
    return case


def run_worker_experiment(repo_root: Path, output_root: Path, executor: Path | None = None) -> dict:
    inventory = collect_environment()
    system = inventory["os"]["system"]
    if system not in ("Windows", "Darwin") or inventory["privileges"]["status"] != "non_elevated":
        raise ValueError("Worker experiment requires ordinary-user native Windows or macOS")
    executor = (executor or default_executor(repo_root)).resolve(strict=True)
    lock = json.loads((repo_root / "upstream.lock.json").read_text())
    provenance = verify_executor(executor, lock["revision"])
    if system == "Darwin" and not os.access(executor, os.X_OK):
        raise ValueError("Native helper is not executable; use mode-preserving extraction")
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "persistent_worker_experiment", "status": "running",
              "full_confinement": "not_established", "environment": inventory, "provenance": provenance,
              "scope": "Controlled persistent worker read/write/command requests and synchronous descendants",
              "started_at": datetime.now(timezone.utc).isoformat(), "harness_source_sha256": _source_hashes(repo_root),
              "cases": [], "network_policy": "allow; networking is not an acceptance property",
              "limits": ["Not a production Bridge integration or hostile IPC authentication test",
                         "Ordinary file contents only; aliases, inherited file handles, metadata, devices and registry unqualified",
                         "Python/OS read baselines remain; normal completion is not arbitrary descendant cleanup proof"]}
    path = output_root / "report.json"
    _write_json(path, report)
    try:
        for mode in ("control", "enforce"):
            fixture = prepare_worker_fixture(output_root / mode, repo_root / "src" / "confinement_lab")
            case = run_worker_case(fixture, mode, system, executor)
            if mode == "enforce":
                case["qualifies"] = case["qualifies"] and report["cases"][0]["qualifies"]
                _write_json(fixture.root / "case.json", case)
            report["cases"].append(case)
            _write_json(path, report)
            if case["protocol_error"] or case["execution"].get("forced_helper_termination"):
                break
        report["status"] = "pass" if len(report["cases"]) == 2 and all(c["qualifies"] for c in report["cases"]) else "fail"
    except BaseException as error:
        report.update(status="error", error=str(error))
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(path, report)
    return report
