"""Portable packaging tests use synthetic artifacts, not a sandbox build."""

import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from confinement_lab.bundle import build_bundle, verify_executor


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bundle-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.output = Path(self.temporary.name) / "portable.zip"
        self.revision = "a" * 40
        (self.repo / "upstream.lock.json").write_text(
            json.dumps({"revision": self.revision}), encoding="utf-8")
        (self.repo / "README.md").write_text("Test fixture", encoding="utf-8")
        source = self.repo / "src" / "confinement_lab"
        source.mkdir(parents=True)
        (source / "__init__.py").write_text("", encoding="utf-8")
        (source / "portable_marker.py").write_text(
            "MESSAGE = 'portable-source-runs'\n", encoding="utf-8")
        (self.repo / "investigate.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent / 'src'))\n"
            "from confinement_lab.portable_marker import MESSAGE\nprint(MESSAGE)\n",
            encoding="utf-8")
        self.native = self.repo / "native" / "windows-x64"
        self.native.mkdir(parents=True)
        self.executor = self.native / "wxc-exec.exe"
        self.executor.write_bytes(b"synthetic build output; never execute")
        (self.native / "LICENSE.md").write_text("Synthetic license", encoding="utf-8")
        self.manifest = {
            "schema_version": 1, "status": "built", "build_exit_code": 0,
            "upstream_revision": self.revision, "architecture": "x64",
            "files": [{"name": "wxc-exec.exe", "bytes": self.executor.stat().st_size,
                       "sha256": hashlib.sha256(self.executor.read_bytes()).hexdigest()}],
        }
        self.write_manifest()

    def write_manifest(self):
        (self.native / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def create_macos_artifact(self, architecture):
        directory = self.repo / "native" / f"macos-{architecture}"
        directory.mkdir()
        executable = directory / "mxc-exec-mac"
        executable.write_bytes(b"synthetic macOS output; never execute: " + architecture.encode("ascii"))
        (directory / "LICENSE.md").write_text("Synthetic license", encoding="utf-8")
        manifest = {
            "schema_version": 1, "status": "built", "build_exit_code": 0,
            "upstream_revision": self.revision, "architecture": architecture,
            "files": [{"name": executable.name, "bytes": executable.stat().st_size,
                       "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return executable

    def test_bundle_excludes_private_and_generated_files_and_runs_after_extract(self):
        secret = b"secret-sentinel-not-for-distribution-957e"
        for relative in (".git/config", "evidence/host.json", "build/compiler.log",
                         "secrets.env", "native/windows-x64/build.log",
                         "src/confinement_lab/__pycache__/secret.pyc"):
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(secret)
        summary = build_bundle(self.repo, self.output)
        self.assertEqual(summary["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest())
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn("native/windows-x64/wxc-exec.exe", archive.namelist())
            self.assertIn("native/windows-x64/manifest.json", archive.namelist())
            self.assertFalse(any(secret in archive.read(name) for name in archive.namelist()))
            extracted = Path(self.temporary.name) / "extracted"
            archive.extractall(extracted)
        result = subprocess.run([sys.executable, "-B", "investigate.py"], cwd=extracted,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "portable-source-runs")

    def test_macos_artifacts_retain_bytes_and_executable_zip_permissions(self):
        executables = [self.create_macos_artifact(architecture)
                       for architecture in ("x64", "arm64")]
        source_modes = [executable.stat().st_mode for executable in executables]
        summary = build_bundle(self.repo, self.output)
        self.assertEqual(len(summary["artifacts"]), 3)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn("native/windows-x64/wxc-exec.exe", archive.namelist())
            for executable, source_mode in zip(executables, source_modes):
                member = executable.relative_to(self.repo).as_posix()
                with self.subTest(member=member):
                    self.assertEqual(archive.read(member), executable.read_bytes())
                    self.assertIn(Path(member).with_name("manifest.json").as_posix(),
                                  archive.namelist())
                    self.assertIn(Path(member).with_name("LICENSE.md").as_posix(),
                                  archive.namelist())
                    info = archive.getinfo(member)
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual(info.external_attr >> 16, stat.S_IFREG | 0o755)
                    self.assertEqual(executable.stat().st_mode, source_mode)
                    receipt = next(artifact for artifact in summary["artifacts"]
                                   if artifact["platform"] == "macos"
                                   and artifact["architecture"] == executable.parent.name.removeprefix("macos-"))
                    self.assertEqual(receipt["sha256"], hashlib.sha256(archive.read(member)).hexdigest())

    def test_changed_macos_helper_is_rejected_before_archive_creation(self):
        executable = self.create_macos_artifact("arm64")
        original = executable.read_bytes()
        executable.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaisesRegex(ValueError, "bytes do not match"):
            build_bundle(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_changed_helper_is_rejected_before_archive_creation(self):
        original = self.executor.read_bytes()
        self.executor.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError):
            build_bundle(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_source_pin_or_failed_build_is_rejected(self):
        for field, bad_value in (("upstream_revision", "b" * 40),
                                 ("status", "not_built"), ("build_exit_code", 1)):
            with self.subTest(field=field):
                original = self.manifest[field]
                self.manifest[field] = bad_value
                self.write_manifest()
                with self.assertRaises(ValueError):
                    verify_executor(self.executor, self.revision)
                self.manifest[field] = original

    def test_missing_helper_cannot_produce_source_only_bundle(self):
        self.executor.unlink()
        with self.assertRaises(ValueError):
            build_bundle(self.repo, self.output)
        self.assertFalse(self.output.exists())

    def test_duplicate_executable_records_are_ambiguous(self):
        self.manifest["files"].append(dict(self.manifest["files"][0]))
        self.write_manifest()
        with self.assertRaises(ValueError):
            verify_executor(self.executor, self.revision)

    def test_existing_bundle_is_preserved(self):
        self.output.write_bytes(b"previous evidence")
        with self.assertRaises(FileExistsError):
            build_bundle(self.repo, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous evidence")


if __name__ == "__main__":
    unittest.main()
