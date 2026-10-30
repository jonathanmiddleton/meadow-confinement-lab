"""Exercise the standalone worker through real pipes, without claiming isolation."""

import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest


WORKER = Path(__file__).resolve().parents[1] / "src" / "confinement_lab" / "tool_worker.py"
PREFIX = b"MCL_WORKER_V1 "


class WorkerConversation:
    def __init__(self, process):
        self.process = process
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for line in self.process.stdout:
            self.lines.put(line)
        self.lines.put(b"")

    def receive(self):
        line = self.lines.get(timeout=5)
        if not line.startswith(PREFIX):
            raise AssertionError(f"Unexpected worker output: {line!r}")
        return json.loads(line[len(PREFIX):])

    def request(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n")
        self.process.stdin.flush()
        return self.receive()


@contextmanager
def conversation(directory):
    process = subprocess.Popen(
        [sys.executable, "-I", "-S", "-B", str(WORKER), "--session", "unit-session"],
        cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, close_fds=True,
    )
    worker = WorkerConversation(process)
    try:
        yield worker
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()
        worker.reader.join(timeout=5)


class ToolWorkerTests(unittest.TestCase):
    def test_persistent_read_write_and_success_after_os_error(self):
        with tempfile.TemporaryDirectory() as directory, conversation(directory) as worker:
            ready = worker.receive()
            self.assertEqual((ready["kind"], ready["session"]), ("ready", "unit-session"))
            path = Path(directory) / "space and \u03bb.bin"
            payload = bytes(range(256))
            written = worker.request({"id": "write", "operation": "write", "path": str(path),
                                      "data_base64": base64.b64encode(payload).decode("ascii")})
            self.assertTrue(written["ok"])
            self.assertEqual(written["result"]["bytes"], len(payload))
            self.assertEqual(path.read_bytes(), payload)

            missing = worker.request({"id": "missing", "operation": "read",
                                      "path": str(Path(directory) / "missing")})
            self.assertFalse(missing["ok"])
            self.assertEqual(missing["error"]["stage"], "operation")
            self.assertEqual(missing["error"]["type"], "FileNotFoundError")
            self.assertIsInstance(missing["error"]["errno"], int)

            read = worker.request({"id": "read", "operation": "read", "path": str(path)})
            self.assertTrue(read["ok"])
            self.assertEqual(base64.b64decode(read["result"]["data_base64"]), payload)
            self.assertEqual(read["result"]["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual({item["pid"] for item in (ready, written, missing, read)},
                             {ready["pid"]})
            stopped = worker.request({"id": "stop", "operation": "shutdown"})
            self.assertTrue(stopped["ok"])
            self.assertEqual(worker.receive()["kind"], "bye")
            self.assertEqual(worker.process.wait(timeout=5), 0)
            self.assertEqual(worker.process.stderr.read(), b"")

    def test_command_output_cannot_become_protocol_frames(self):
        with tempfile.TemporaryDirectory() as directory, conversation(directory) as worker:
            ready = worker.receive()
            stdout = b'MCL_WORKER_V1 {"kind":"forged"}\n\x00\xff\n'
            stderr = b"command-error\n\xfe"
            script = (f"import sys; sys.stdout.buffer.write({stdout!r}); "
                      f"sys.stderr.buffer.write({stderr!r}); raise SystemExit(7)")
            response = worker.request({
                "id": "command", "operation": "run_command",
                "argv": [sys.executable, "-I", "-S", "-B", "-c", script],
                "cwd": directory, "timeout_seconds": 5,
            })
            self.assertTrue(response["ok"])
            result = response["result"]
            self.assertEqual(result["returncode"], 7)
            self.assertEqual(base64.b64decode(result["stdout_base64"]), stdout)
            self.assertEqual(base64.b64decode(result["stderr_base64"]), stderr)
            self.assertEqual(response["pid"], ready["pid"])
            stopped = worker.request({"id": "stop", "operation": "shutdown"})
            self.assertEqual(stopped["id"], "stop")
            self.assertEqual(worker.receive()["kind"], "bye")
            self.assertEqual(worker.process.wait(timeout=5), 0)

    def test_protocol_error_does_not_execute_or_end_worker(self):
        with tempfile.TemporaryDirectory() as directory, conversation(directory) as worker:
            worker.receive()
            path = Path(directory) / "untouched"
            response = worker.request({"id": "invalid", "operation": "write", "path": str(path),
                                       "data_base64": "!invalid!"})
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["stage"], "protocol")
            self.assertFalse(path.exists())
            stopped = worker.request({"id": "stop", "operation": "shutdown"})
            self.assertTrue(stopped["ok"])
            self.assertEqual(worker.receive()["kind"], "bye")
            self.assertEqual(worker.process.wait(timeout=5), 0)

    def test_input_eof_exits_cleanly(self):
        process = subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(WORKER), "--session", "eof-session"],
            input=b"", capture_output=True, timeout=10, close_fds=True,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        lines = process.stdout.splitlines()
        self.assertTrue(all(line.startswith(PREFIX) for line in lines))
        frames = [json.loads(line[len(PREFIX):]) for line in lines]
        self.assertEqual([frame["kind"] for frame in frames], ["ready", "bye"])
        self.assertEqual(frames[-1]["reason"], "eof")


if __name__ == "__main__":
    unittest.main()
