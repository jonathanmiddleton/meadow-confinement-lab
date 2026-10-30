"""Disposable write witnesses and independent evaluation of their effects.

The nonce correlates controlled payload output with its fixture. It is not an
authentication boundary against malicious code. These cases measure direct
create/overwrite behavior, not general containment or every possible escape.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Literal


@dataclass(frozen=True)
class Fixture:
    root: Path
    workspace: Path
    inside_file: Path
    outside_sentinel: Path
    outside_new: Path
    python_payload: Path
    powershell_payload: Path
    nonce: str
    sentinel_before: bytes
    written_bytes: bytes

    def as_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root), "workspace": str(self.workspace),
            "inside_file": str(self.inside_file),
            "outside_sentinel": str(self.outside_sentinel),
            "outside_new": str(self.outside_new),
            "python_payload": str(self.python_payload),
            "powershell_payload": str(self.powershell_payload), "nonce": self.nonce,
            "sentinel_before_base64": _b64(self.sentinel_before),
            "written_bytes_base64": _b64(self.written_bytes),
        }


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def prepare_fixture(root: Path, nonce: str | None = None) -> Fixture:
    """Create a fresh case under an existing, caller-owned disposable directory.

    No existing case is reused or cleaned. All outside targets are siblings of
    the workspace under this new case root; no real user files are targets.
    """
    nonce = secrets.token_hex(16) if nonce is None else nonce
    if not isinstance(nonce, str) or not nonce:
        raise ValueError("nonce must be a nonempty string")
    root = Path(root).absolute()
    root.mkdir()
    workspace = root / "workspace"
    workspace.mkdir()
    outside = root / "outside"
    outside.mkdir()
    fixture = Fixture(
        root=root, workspace=workspace, inside_file=workspace / "inside.bin",
        outside_sentinel=outside / "sentinel.bin", outside_new=outside / "new.bin",
        python_payload=workspace / "probe.py", powershell_payload=workspace / "probe.ps1",
        nonce=nonce,
        sentinel_before=b"confinement-lab original sentinel\x00" + nonce.encode("utf-8"),
        written_bytes=b"confinement-lab write witness\x00\xff\n" + nonce.encode("utf-8"),
    )
    fixture.outside_sentinel.write_bytes(fixture.sentinel_before)
    fixture.python_payload.write_text(_python_payload(fixture), encoding="utf-8")
    # A BOM lets Windows PowerShell 5 read non-ASCII paths correctly.
    fixture.powershell_payload.write_text(_powershell_payload(fixture), encoding="utf-8-sig")
    return fixture


def _python_payload(fixture: Fixture) -> str:
    config = {
        "nonce": fixture.nonce, "data": _b64(fixture.written_bytes),
        "inside": str(fixture.inside_file),
        "outside_overwrite": str(fixture.outside_sentinel),
        "outside_create": str(fixture.outside_new),
    }
    return '''import base64
import json
import os
from pathlib import Path

config = json.loads(CONFIG_LITERAL)
report = {"schema_version": 1, "event": "end", "nonce": config["nonce"], "language": "python"}
print(json.dumps({"schema_version": 1, "event": "start", "nonce": config["nonce"]}), flush=True)
report["effective_environment_paths"] = {
    name: os.environ.get(name)
    for name in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "USERPROFILE")
}
data = base64.b64decode(config["data"])
for operation in ("inside", "outside_overwrite", "outside_create"):
    try:
        Path(config[operation]).write_bytes(data)
        report[operation] = {"reached": True, "status": "succeeded"}
    except Exception as exc:
        denied = isinstance(exc, PermissionError) and (
            getattr(exc, "errno", None) in (1, 13) or getattr(exc, "winerror", None) == 5
        )
        report[operation] = {
            "reached": True, "status": "access_denied" if denied else "error",
            "error": {"type": type(exc).__name__, "errno": getattr(exc, "errno", None),
                      "winerror": getattr(exc, "winerror", None)},
        }
print(json.dumps(report), flush=True)
'''.replace("CONFIG_LITERAL", repr(json.dumps(config, ensure_ascii=True)))


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell_payload(fixture: Fixture) -> str:
    entries = {
        "NONCE_LITERAL": _ps_literal(fixture.nonce),
        "DATA_LITERAL": _ps_literal(_b64(fixture.written_bytes)),
        "INSIDE_LITERAL": _ps_literal(str(fixture.inside_file)),
        "OVERWRITE_LITERAL": _ps_literal(str(fixture.outside_sentinel)),
        "CREATE_LITERAL": _ps_literal(str(fixture.outside_new)),
    }
    payload = r'''$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$nonce = NONCE_LITERAL
$start = @{schema_version = 1; event = 'start'; nonce = $nonce}
[Console]::Out.WriteLine(($start | ConvertTo-Json -Compress))
$report = [ordered]@{schema_version = 1; event = 'end'; nonce = $nonce; language = 'powershell'}
$report['effective_environment_paths'] = [ordered]@{}
foreach ($name in @('LOCALAPPDATA', 'APPDATA', 'TEMP', 'TMP', 'USERPROFILE')) {
    $report['effective_environment_paths'][$name] = [Environment]::GetEnvironmentVariable($name)
}
$data = [Convert]::FromBase64String(DATA_LITERAL)
$targets = [ordered]@{
    inside = INSIDE_LITERAL
    outside_overwrite = OVERWRITE_LITERAL
    outside_create = CREATE_LITERAL
}
foreach ($operation in $targets.Keys) {
    try {
        [System.IO.File]::WriteAllBytes($targets[$operation], $data)
        $report[$operation] = @{reached = $true; status = 'succeeded'}
    } catch {
        $failure = $_.Exception.GetBaseException()
        $denied = ($failure -is [System.UnauthorizedAccessException]) -and ($failure.HResult -eq -2147024891)
        $outcome = if ($denied) { 'access_denied' } else { 'error' }
        $report[$operation] = @{
            reached = $true; status = $outcome
            error = @{type = $failure.GetType().FullName; hresult = [int]$failure.HResult}
        }
    }
}
[Console]::Out.WriteLine(($report | ConvertTo-Json -Depth 6 -Compress))
'''
    return re.sub("|".join(entries), lambda match: entries[match.group()], payload)


def _observe(path: Path, expected: bytes) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"exists": False, "matches_expected": False}
    except OSError as exc:
        return {"exists": None, "matches_expected": False,
                "error": type(exc).__name__}
    observation: dict[str, Any] = {
        "exists": True, "regular_file": stat.S_ISREG(metadata.st_mode),
        "size": metadata.st_size, "matches_expected": False,
    }
    if not observation["regular_file"]:
        return observation
    try:
        with path.open("rb") as stream:
            content = stream.read(len(expected) + 1)
    except OSError as exc:
        observation["error"] = type(exc).__name__
        return observation
    observation["matches_expected"] = content == expected
    if len(content) == metadata.st_size:
        observation["sha256"] = hashlib.sha256(content).hexdigest()
    return observation


def _denial_has_os_evidence(attempt: dict[str, Any]) -> bool:
    error = attempt.get("error")
    if not isinstance(error, dict):
        return False
    if error.get("type") == "PermissionError":
        return error.get("errno") in (1, 13) or error.get("winerror") == 5
    return (error.get("type") == "System.UnauthorizedAccessException"
            and error.get("hresult") == -2147024891)


def evaluate_fixture(
    fixture: Fixture, *, mode: Literal["enforce", "control"],
    returncode: int | None, stdout: str, stderr: str = "",
) -> dict[str, Any]:
    """Check completed child evidence and actual files after process settlement.

    Callers own launch, timeout and descendant settlement. This function neither
    executes nor kills a process. A control pass proves the witness can write the
    targets unconfined; an enforcement pass covers only these direct operations.
    """
    if mode not in ("enforce", "control"):
        raise ValueError("mode must be 'enforce' or 'control'")
    reasons: list[str] = []
    expected_outside = fixture.sentinel_before if mode == "enforce" else fixture.written_bytes
    observations = {
        "inside": _observe(fixture.inside_file, fixture.written_bytes),
        "outside_sentinel": _observe(fixture.outside_sentinel, expected_outside),
        "outside_new": _observe(fixture.outside_new, fixture.written_bytes),
    }
    if not observations["inside"]["matches_expected"]:
        reasons.append("inside_bytes_do_not_match")
    if not observations["outside_sentinel"]["matches_expected"]:
        reasons.append("outside_sentinel_bytes_do_not_match")
    if mode == "enforce":
        if observations["outside_new"]["exists"] is not False:
            reasons.append("outside_new_not_confirmed_absent")
    elif not observations["outside_new"]["matches_expected"]:
        reasons.append("outside_new_bytes_do_not_match")

    records: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            record = json.loads(line.lstrip("\ufeff"))
        except (ValueError, TypeError):
            continue
        if isinstance(record, dict) and record.get("nonce") == fixture.nonce:
            records.append(record)
    starts = [r for r in records if r.get("event") == "start" and r.get("schema_version") == 1]
    ends = [r for r in records if r.get("event") == "end" and r.get("schema_version") == 1]
    complete = len(starts) == len(ends) == 1 and records.index(starts[0]) < records.index(ends[0])
    child_report = ends[0] if len(ends) == 1 else None
    if not complete:
        reasons.append("missing_or_ambiguous_correlated_start_end")
    if returncode != 0:
        reasons.append("process_did_not_exit_zero")

    all_reached = complete
    if complete and child_report is not None:
        for name in ("inside", "outside_overwrite", "outside_create"):
            attempt = child_report.get(name)
            if not isinstance(attempt, dict) or attempt.get("reached") is not True:
                reasons.append(name + "_not_reached")
                all_reached = False
                continue
            expected_status = "succeeded" if name == "inside" or mode == "control" else "access_denied"
            if attempt.get("status") != expected_status:
                reasons.append(name + "_unexpected_status")
            elif expected_status == "access_denied" and not _denial_has_os_evidence(attempt):
                reasons.append(name + "_missing_os_denial_evidence")

    outside_violation = mode == "enforce" and (
        not observations["outside_sentinel"]["matches_expected"]
        or observations["outside_new"]["exists"] is not False
    )
    passed = not reasons
    status = "pass" if passed else ("fail" if all_reached or outside_violation else "not_reached")
    return {
        "schema_version": 1, "mode": mode, "status": status, "passed": passed,
        "reasons": reasons, "observations": observations, "child_report": child_report,
        "payload_reached": all_reached, "returncode": returncode, "stderr": stderr,
    }
