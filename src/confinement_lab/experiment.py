"""Run controlled direct-write witnesses with and without native MXC enforcement."""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

from confinement_lab.bundle import verify_executor
from confinement_lab.environment import collect_environment
from confinement_lab.witnesses import Fixture, evaluate_fixture, prepare_fixture


def default_executor(repo_root: Path) -> Path:
    machine = platform.machine().lower()
    if machine not in ("arm64", "aarch64", "x86_64", "amd64"):
        raise ValueError("No bundled executor for architecture: " + machine)
    architecture = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if platform.system() == "Darwin":
        return repo_root / "native" / f"macos-{architecture}" / "mxc-exec-mac"
    if platform.system() == "Windows":
        return repo_root / "native" / f"windows-{architecture}" / "wxc-exec.exe"
    raise ValueError("Native experiments support Windows and macOS only")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _source_hashes(repo_root: Path) -> dict[str, str]:
    files = [repo_root / "investigate.py", repo_root / "upstream.lock.json"]
    files.extend(sorted((repo_root / "src" / "confinement_lab").glob("*.py")))
    return {path.relative_to(repo_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def _backend_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    events = []
    for line in log_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        start = line.find('{"event":')
        if start < 0:
            continue
        try:
            event = json.loads(line[start:])
        except ValueError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _environment(fixture: Fixture, system: str = "Windows") -> dict[str, str]:
    if system == "Darwin":
        profile, temporary = fixture.workspace / "profile", fixture.workspace / "tmp"
        profile.mkdir()
        temporary.mkdir()
        return {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(profile),
            "TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary),
            "LC_ALL": "C",
        }
    windows = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
    profile = fixture.workspace / "profile"
    local = profile / "AppData" / "Local"
    roaming = profile / "AppData" / "Roaming"
    temporary = fixture.workspace / "tmp"
    for directory in (local, roaming, temporary):
        directory.mkdir(parents=True)
    return {
        "SYSTEMROOT": str(windows), "WINDIR": str(windows),
        "SYSTEMDRIVE": windows.drive, "COMSPEC": str(windows / "System32" / "cmd.exe"),
        "PATH": str(windows / "System32"), "USERPROFILE": str(profile), "HOME": str(profile),
        "APPDATA": str(roaming), "LOCALAPPDATA": str(local),
        "TEMP": str(temporary), "TMP": str(temporary),
    }


def _capture(command: list[str], *, cwd: Path, env: dict[str, str], output: Path) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    timer = time.monotonic()
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=45)
        stdout, stderr = result.stdout, result.stderr
        returncode, error = result.returncode, None
    except subprocess.TimeoutExpired as failure:
        stdout, stderr = failure.stdout or b"", failure.stderr or b""
        returncode, error = None, "controller_timeout"
    except OSError as failure:
        stdout, stderr = b"", str(failure).encode("utf-8")
        returncode, error = None, type(failure).__name__
    output.with_suffix(".stdout.bin").write_bytes(stdout)
    output.with_suffix(".stderr.bin").write_bytes(stderr)
    receipt = {
        "command": command, "cwd": str(cwd), "environment": env,
        "started_at": started, "duration_seconds": time.monotonic() - timer,
        "returncode": returncode, "error": error,
        "stdout": stdout.decode("utf-8-sig", errors="replace"),
        "stderr": stderr.decode("utf-8-sig", errors="replace"),
    }
    _write_json(output.with_suffix(".json"), receipt)
    return receipt


def _policy(fixture: Fixture, command: list[str], environment: dict[str, str], language: str,
            system: str = "Windows") -> dict[str, Any]:
    if system == "Darwin":
        reads = ([str(Path(sys.base_prefix).resolve()), str(Path(sys.prefix).resolve()),
                  str(Path(command[0]).resolve().parent)] if language == "python" else [])
        return {
            "version": "1.0.0", "containment": "seatbelt",
            "process": {
                "commandLine": "exec " + shlex.join(command), "cwd": str(fixture.workspace),
                "timeout": 30000, "inheritDefaultEnv": False,
                "env": [f"{name}={value}" for name, value in environment.items()],
            },
            "filesystem": {"readwritePaths": [str(fixture.workspace)],
                           "readonlyPaths": list(dict.fromkeys(reads))},
            "network": {"egress": {"default": "deny"},
                        "ingress": {"default": "deny", "hostLoopback": "deny"}},
            "ui": {"disable": True, "clipboard": "none", "injection": False},
            "seatbelt": {"nestedPty": False, "guiAccess": False, "keychainAccess": False},
            "telemetry": {"enabled": False},
        }
    reads = [environment["SYSTEMROOT"]]
    if language == "python":
        reads.extend([str(Path(sys.base_prefix).resolve()), str(Path(sys.prefix).resolve()),
                      str(Path(command[0]).resolve().parent)])
    return {
        "version": "1.0.0", "containment": "processcontainer",
        "process": {
            "commandLine": subprocess.list2cmdline(command), "cwd": str(fixture.workspace),
            "timeout": 30000, "inheritDefaultEnv": False,
            "env": [f"{name}={value}" for name, value in environment.items()],
        },
        "filesystem": {"readwritePaths": [str(fixture.workspace)], "readonlyPaths": list(dict.fromkeys(reads))},
        "network": {"egress": {"default": "deny"}, "ingress": {"default": "deny", "hostLoopback": "deny"}},
        "ui": {"disable": False, "clipboard": "none", "injection": False},
        "processContainer": {"ui": {"isolation": "container", "desktopSystemControl": False,
                                     "systemSettings": "none", "ime": False}},
        "lifecycle": {"destroyOnExit": True, "preservePolicy": False},
        "telemetry": {"enabled": False},
    }


def run_experiment(repo_root: Path, output_root: Path, executor: Path | None = None) -> dict[str, Any]:
    """Preserve every case and report a pass only after matching controls pass.

    This tests two direct file operations in each interpreter. It does not
    establish a complete Meadow confinement guarantee.
    """
    inventory = collect_environment()
    system = inventory["os"]["system"]
    if system not in ("Windows", "Darwin"):
        raise ValueError("This experiment supports native Windows and macOS only.")
    if inventory["privileges"]["status"] != "non_elevated":
        raise ValueError("Run from a verified non-elevated process; unknown or elevated identity cannot qualify.")
    executor = (executor or default_executor(repo_root)).resolve(strict=True)
    lock = json.loads((repo_root / "upstream.lock.json").read_text(encoding="utf-8"))
    provenance = verify_executor(executor, lock["revision"])
    powershell = shutil.which("powershell.exe") if system == "Windows" else None
    if system == "Windows" and not powershell:
        raise ValueError("Windows PowerShell is required for the .NET write witness.")
    if system == "Darwin" and not os.access(executor, os.X_OK):
        raise ValueError("macOS executor is not executable; extract with a tool that preserves Unix permissions (for example /usr/bin/unzip).")
    # Seatbelt resolves aliases too; report physical fixture roots consistently.
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    report: dict[str, Any] = {
        "schema_version": 1, "kind": "direct_write_experiment",
        "scope": "Python and " + ("Windows PowerShell" if system == "Windows" else "/bin/sh")
                 + " direct create/overwrite of owned sibling fixtures",
        "full_confinement": "not_established", "status": "running",
        "host": platform.node(),
        "environment": inventory, "executor": str(executor), "provenance": provenance,
        "harness_source_sha256": _source_hashes(repo_root),
        "started_at": datetime.now(timezone.utc).isoformat(), "cases": [],
    }
    if system == "Darwin":
        report["policy_limits"] = {
            "explicit_writable_directories": "case workspace only",
            "upstream_writable_device_baseline": ["/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"],
            "upstream_terminal_rules": ["literal /dev/tty", "extension-gated /dev/ttys[0-9]+"],
            "note": "Pinned Seatbelt also grants system reads and baseline Mach lookups; full write boundary is not qualified.",
        }
    report_path = output_root / "report.json"
    _write_json(report_path, report)
    try:
        report["workload_executables"] = {}
        for name, executable in (("python", sys.executable),
                                 ("powershell" if system == "Windows" else "shell",
                                  powershell if system == "Windows" else "/bin/sh")):
            path = Path(executable).resolve(strict=True)
            content = path.read_bytes()
            report["workload_executables"][name] = {
                "path": str(path), "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            }
        for language in ("python", "powershell" if system == "Windows" else "shell"):
            control_passed = False
            for mode in ("control", "enforce"):
                name = f"{language}-{mode}"
                fixture = prepare_fixture(output_root / name)
                environment = _environment(fixture, system)
                command = ([sys.executable, "-I", "-S", "-B", str(fixture.python_payload)]
                           if language == "python" else ["/bin/sh", str(fixture.shell_payload)]
                           if language == "shell" else
                           [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                            base64.b64encode(fixture.powershell_payload.read_text(encoding="utf-8-sig")
                                             .encode("utf-16le")).decode("ascii")])
                _write_json(fixture.root / "fixture.json", fixture.as_dict())
                case: dict[str, Any] = {"name": name, "mode": mode, "language": language}
                if mode == "enforce":
                    policy_path = fixture.root / "policy.json"
                    _write_json(policy_path, _policy(fixture, command, environment, language, system))
                    probe_flag = "--probe" if system == "Windows" else "--dry-run"
                    probe = _capture([str(executor), probe_flag, "--config", str(policy_path)],
                                     cwd=fixture.workspace, env=environment, output=fixture.root / "capabilities")
                    case["capability_probe" if system == "Windows" else "policy_validation"] = probe
                    if probe["error"] == "controller_timeout":
                        report["cases"].append(case)
                        raise RuntimeError("Capability probe timed out; preserve this run and reconcile its processes before retrying.")
                    # Probe success is diagnostic only. A real launch is still required.
                    command = [str(executor), "--config", str(policy_path),
                               "--log-file", str(fixture.root / "mxc.log")]
                captured = _capture(command, cwd=fixture.workspace, env=environment, output=fixture.root / "execution")
                evaluation = evaluate_fixture(fixture, mode=mode, returncode=captured["returncode"],
                                              stdout=captured["stdout"], stderr=captured["stderr"])
                case.update({"execution": captured, "evaluation": evaluation})
                case["qualifies"] = evaluation["passed"] and (mode == "control" or control_passed)
                if mode == "enforce":
                    if system == "Windows":
                        events = _backend_events(fixture.root / "mxc.log")
                        case["backend_events"] = events
                        case["native_backend_observed"] = any(
                            event.get("event") == "mxc.ProcessExited" and event.get("tier") == "base-container"
                            and event.get("exit_code") == 0 for event in events)
                    else:
                        log_path = fixture.root / "mxc.log"
                        log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
                        case["backend_evidence"] = {
                            "backend": "seatbelt", "log": str(log_path),
                            "generated_profile_logged": "Seatbelt: --- end generated profile ---" in log,
                            "sandbox_init_path_logged": "Seatbelt: applying sandbox via sandbox_init" in log,
                            "basis": "Pinned executor fails spawn if sandbox_init fails; completed payload is required separately.",
                        }
                        case["native_backend_observed"] = (
                            case["backend_evidence"]["generated_profile_logged"]
                            and case["backend_evidence"]["sandbox_init_path_logged"]
                            and captured["returncode"] == 0 and evaluation["payload_reached"])
                    case["qualifies"] = case["qualifies"] and case["native_backend_observed"]
                if mode == "control":
                    control_passed = evaluation["passed"]
                child_report = evaluation.get("child_report") or {}
                paths = child_report.get("effective_environment_paths", {})
                case["external_environment_paths"] = {
                    name: value for name, value in paths.items()
                    if value and not Path(value).is_relative_to(fixture.workspace)
                }
                report["cases"].append(case)
                _write_json(report_path, report)
                if captured["error"] == "controller_timeout":
                    raise RuntimeError("Executor timed out; preserve this run and reconcile its processes before retrying.")
        report["status"] = "pass" if all(case["qualifies"] for case in report["cases"]) else "fail"
        report["external_environment_paths_observed"] = any(
            case["external_environment_paths"] for case in report["cases"] if case["mode"] == "enforce")
    except BaseException as failure:
        report["status"] = "error"
        report["error"] = str(failure)
        raise
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(report_path, report)
    return report
