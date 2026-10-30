"""Controlled child/grandchild file operations; never use real user files."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys


def probe(root: Path, level: str, token: str) -> dict:
    operations = []
    for area in ("workspace", "reference", "private"):
        for operation in ("read", "write"):
            path = root / area / ("input.bin" if operation == "read" else f"{level}.bin")
            row = {"area": area, "operation": operation, "path": str(path)}
            try:
                if operation == "read":
                    row["data_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")
                else:
                    row["bytes"] = path.write_bytes(f"{token}:{level}:{area}".encode())
                row["ok"] = True
            except OSError as error:
                row.update(ok=False, error={"type": type(error).__name__, "errno": error.errno,
                                           "winerror": getattr(error, "winerror", None),
                                           "message": str(error), "stage": "operation"})
            operations.append(row)
    result = {"level": level, "pid": os.getpid(), "operations": operations}
    if level == "child":
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-B", __file__, str(root), "grandchild", token],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, close_fds=True,
        )
        result["grandchild_returncode"] = completed.returncode
        result["grandchild_stderr_base64"] = base64.b64encode(completed.stderr).decode("ascii")
        result["grandchild"] = json.loads(completed.stdout)
    return result


if __name__ == "__main__":
    print(json.dumps(probe(Path(sys.argv[1]), sys.argv[2], sys.argv[3]), ensure_ascii=True), flush=True)
