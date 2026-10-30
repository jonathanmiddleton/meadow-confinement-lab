"""Build a portable source/helper ZIP without a compiler or package install.

Manifest and digest checks bind bytes to the supplied build receipt. They do not
authenticate an untrusted receipt or establish that a helper confines execution.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any
import zipfile


def verify_executor(executor: Path, lock_revision: str) -> dict[str, Any]:
    """Verify a built helper against its adjacent manifest and the source pin."""
    executor = Path(executor).absolute()
    if not isinstance(lock_revision, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", lock_revision):
        raise ValueError("upstream revision must be a full Git commit SHA")
    manifest_path = executor.with_name("manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("unsupported native artifact manifest")
    if (manifest.get("status") != "built"
            or type(manifest.get("build_exit_code")) is not int
            or manifest["build_exit_code"] != 0):
        raise ValueError("native helper has no successful build receipt")
    if manifest.get("upstream_revision") != lock_revision:
        raise ValueError("native helper upstream revision differs from upstream.lock.json")
    if manifest.get("architecture") not in ("x64", "arm64"):
        raise ValueError("native helper architecture must be x64 or arm64")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("native artifact manifest has no files list")
    matches = [entry for entry in files if isinstance(entry, dict)
               and entry.get("name") == executor.name]
    if len(matches) != 1:
        raise ValueError("native artifact manifest must name its executable exactly once")
    expected = matches[0]
    digest = expected.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        raise ValueError("native artifact manifest has no valid executable SHA-256")
    if type(expected.get("bytes")) is not int or expected["bytes"] <= 0:
        raise ValueError("native artifact manifest has no positive executable size")
    content = executor.read_bytes()
    observed_hash = hashlib.sha256(content).hexdigest()
    if len(content) != expected["bytes"] or observed_hash != digest.lower():
        raise ValueError("native helper bytes do not match the build manifest")
    return {
        "path": str(executor), "architecture": manifest["architecture"],
        "upstream_revision": lock_revision, "sha256": observed_hash,
        "size": len(content), "manifest": manifest,
    }


def _read_project_file(repo: Path, path: Path) -> bytes:
    if path.is_symlink() or not path.resolve().is_relative_to(repo):
        raise ValueError("bundle source must be a regular file inside the repository: " + str(path))
    if not path.is_file():
        raise ValueError("required bundle file is missing: " + str(path))
    return path.read_bytes()


def build_bundle(repo_root: Path, output: Path) -> dict[str, Any]:
    """Package an allowlist of project files and verified native helpers.

    Existing output is never overwritten. All input validation happens before
    archive creation. A valid build receipt is required for every included helper.
    """
    repo = Path(repo_root).resolve()
    output = Path(output).absolute()
    if output.exists():
        raise FileExistsError(output)
    content: dict[str, bytes] = {}
    executable_members: set[str] = set()

    def include(path: Path) -> None:
        content[path.relative_to(repo).as_posix()] = _read_project_file(repo, path)

    for name in ("investigate.py", "upstream.lock.json", "README.md"):
        include(repo / name)
    lock = json.loads(content["upstream.lock.json"].decode("utf-8-sig"))
    if not isinstance(lock, dict):
        raise ValueError("upstream.lock.json must be an object")
    revision = lock.get("revision")
    sources = sorted((repo / "src" / "confinement_lab").rglob("*.py"))
    sources = [path for path in sources if not any(
        part == "__pycache__" or part.startswith(".")
        for part in path.relative_to(repo / "src").parts
    )]
    if not sources:
        raise ValueError("no Python package source is available to bundle")
    for path in sources:
        include(path)
    for path in sorted((repo / "docs").glob("*.md")):
        include(path)

    artifacts = []
    for platform, architecture, executable_name in (
        ("windows", "x64", "wxc-exec.exe"),
        ("windows", "arm64", "wxc-exec.exe"),
        ("macos", "x64", "mxc-exec-mac"),
        ("macos", "arm64", "mxc-exec-mac"),
    ):
        directory = repo / "native" / f"{platform}-{architecture}"
        executor = directory / executable_name
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.resolve().is_relative_to(repo):
            raise ValueError("native artifact directory must stay inside the repository")
        if not executor.is_file():
            raise ValueError(f"native artifact directory has no built {executable_name}: " + str(directory))
        verified = verify_executor(executor, revision)
        if verified["architecture"] != architecture:
            raise ValueError("native artifact directory and manifest architectures disagree")
        for name in (executable_name, "LICENSE.md", "manifest.json"):
            include(directory / name)
        # Check the captured bytes, so a change between verification and reading
        # the archive inputs cannot silently substitute a different executable.
        member = executor.relative_to(repo).as_posix()
        captured_hash = hashlib.sha256(content[member]).hexdigest()
        if captured_hash != verified["sha256"]:
            raise ValueError("native helper changed while preparing the bundle")
        if platform == "macos":
            executable_members.add(member)
        artifacts.append({"platform": platform, **{key: verified[key] for key in
                          ("architecture", "upstream_revision", "sha256", "size")}})
    if not artifacts:
        raise ValueError("no built native helper is available; source-only bundles are not supported")

    with zipfile.ZipFile(output, mode="x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(content):
            if name in executable_members:
                # Store executable metadata even when packaging from Windows.
                # This changes the archive member, never the source file mode.
                member_info = zipfile.ZipInfo(name)
                member_info.create_system = 3  # Unix permissions in external_attr.
                member_info.external_attr = (stat.S_IFREG | 0o755) << 16
                archive.writestr(member_info, content[name], compress_type=zipfile.ZIP_DEFLATED)
            else:
                archive.writestr(name, content[name])
    archive_bytes = output.read_bytes()
    return {
        "schema_version": 1, "output": str(output), "size": len(archive_bytes),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "upstream_revision": revision, "artifacts": artifacts,
        "files": sorted(content),
    }
