"""Controlled tool payload for the persistent-worker experiment.

Run this file directly with isolated Python. It deliberately applies no pathname
permission checks: read/write denial evidence must come from the operating
system. This small protocol is an experiment payload, not a production service
or an authenticated boundary against hostile command output.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys


PREFIX = b"MCL_WORKER_V1 "
MAX_FILE_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024


class ProtocolError(ValueError):
    """The request was rejected before its filesystem operation."""


def _text(value, name):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ProtocolError(f"{name} must be a nonempty string without NUL")
    return value


def _decode(request):
    if not isinstance(request, dict):
        raise ProtocolError("request must be an object")
    _text(request.get("id"), "id")
    operation = request.get("operation")
    fields = {
        "read": {"id", "operation", "path"},
        "write": {"id", "operation", "path", "data_base64"},
        "run_command": {"id", "operation", "argv", "cwd", "timeout_seconds"},
        "shutdown": {"id", "operation"},
    }
    if not isinstance(operation, str) or operation not in fields:
        raise ProtocolError("unsupported operation")
    if set(request) != fields[operation]:
        raise ProtocolError("request fields do not match the operation")
    if operation in {"read", "write"}:
        _text(request["path"], "path")
    if operation == "write":
        encoded = request["data_base64"]
        if not isinstance(encoded, str):
            raise ProtocolError("data_base64 must be a string")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProtocolError("invalid data_base64") from error
        if len(data) > MAX_FILE_BYTES:
            raise ProtocolError("write exceeds the experiment's byte limit")
        return data
    if operation == "run_command":
        argv = request["argv"]
        if not isinstance(argv, list) or not 1 <= len(argv) <= 128:
            raise ProtocolError("argv must contain 1 to 128 strings")
        for argument in argv:
            if not isinstance(argument, str) or "\0" in argument:
                raise ProtocolError("argv values must be strings without NUL")
        _text(argv[0], "executable")
        _text(request["cwd"], "cwd")
        timeout = request["timeout_seconds"]
        if (type(timeout) not in (int, float) or not math.isfinite(timeout)
                or not 0 < timeout <= 30):
            raise ProtocolError("timeout_seconds must be finite, positive and at most 30")
    return None


def _execute(request, data):
    operation = request["operation"]
    if operation == "read":
        with Path(request["path"]).open("rb") as source:
            content = source.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("read exceeds the experiment's byte limit")
        return {"data_base64": base64.b64encode(content).decode("ascii"),
                "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    if operation == "write":
        written = Path(request["path"]).write_bytes(data)
        return {"bytes": written, "sha256": hashlib.sha256(data).hexdigest()}
    if operation == "run_command":
        completed = subprocess.run(
            request["argv"], cwd=request["cwd"], stdin=subprocess.DEVNULL,
            capture_output=True, close_fds=True, timeout=request["timeout_seconds"],
        )
        return {
            "returncode": completed.returncode,
            "stdout_base64": base64.b64encode(completed.stdout).decode("ascii"),
            "stderr_base64": base64.b64encode(completed.stderr).decode("ascii"),
        }
    return {"shutdown": True}


def _error(error, stage):
    result = {"type": type(error).__name__, "errno": getattr(error, "errno", None),
              "winerror": getattr(error, "winerror", None), "message": str(error),
              "stage": stage}
    if isinstance(error, subprocess.TimeoutExpired):
        result["stdout_base64"] = base64.b64encode(error.stdout or b"").decode("ascii")
        result["stderr_base64"] = base64.b64encode(error.stderr or b"").decode("ascii")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    args = parser.parse_args(argv)
    common = {"version": 1, "session": args.session, "pid": os.getpid()}

    def emit(kind, **fields):
        encoded = json.dumps({**common, "kind": kind, **fields}, ensure_ascii=True).encode("ascii")
        sys.stdout.buffer.write(PREFIX + encoded + b"\n")
        sys.stdout.buffer.flush()

    emit("ready")
    seen = set()
    reason = "eof"
    while True:
        line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not line:
            break
        request = None
        try:
            if len(line) > MAX_REQUEST_BYTES:
                while line and not line.endswith(b"\n"):
                    line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
                raise ProtocolError("request exceeds the experiment's byte limit")
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeError, ValueError) as error:
                raise ProtocolError("request must be UTF-8 JSON") from error
            data = _decode(request)
            if request["id"] in seen:
                raise ProtocolError("request id was already used")
            seen.add(request["id"])
        except ProtocolError as error:
            emit("response", id=request.get("id") if isinstance(request, dict) else None,
                 operation=request.get("operation") if isinstance(request, dict) else None,
                 ok=False, error=_error(error, "protocol"))
            continue
        try:
            result = _execute(request, data)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            emit("response", id=request["id"], operation=request["operation"],
                 ok=False, error=_error(error, "operation"))
            continue
        emit("response", id=request["id"], operation=request["operation"], ok=True, result=result)
        if request["operation"] == "shutdown":
            reason = "shutdown"
            break
    emit("bye", reason=reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
