#!/usr/bin/env python3
"""Build the pinned macOS executor and retain compilation-only provenance."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def file_receipt(path: Path) -> dict:
    data = path.read_bytes()
    return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def checked_text(command: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{command[0]} exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("arm64", "x64"), required=True)
    parser.add_argument("--upstream-directory", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args()
    lab = Path(__file__).resolve().parents[1]
    upstream = args.upstream_directory.resolve(strict=True)
    output = (args.output_directory or lab / "artifacts" / f"mxc-macos-{args.architecture}").absolute()
    output.mkdir(parents=True, exist_ok=False)
    target = {"arm64": "aarch64-apple-darwin", "x64": "x86_64-apple-darwin"}[args.architecture]
    command = ["cargo", "+1.93", "--config", "../.azure-pipelines/.cargo/config.public.toml",
               "build", "--locked", "--release", "-p", "mxc_darwin", "--bin", "mxc-exec-mac",
               "--target", target, "--color", "never"]
    receipt = {
        "schema_version": 1, "status": "building", "confinement_status": "not_tested",
        "started_at": datetime.now(timezone.utc).isoformat(), "platform": "Darwin",
        "architecture": args.architecture, "target": target, "build_exit_code": None,
        "command": {"executable": command[0], "arguments": command[1:],
                    "working_directory": "upstream/src"},
        "runner": {"system": platform.system(), "machine": platform.machine(),
                   "macos_version": platform.mac_ver()[0], "effective_uid": getattr(os, "geteuid", lambda: None)(),
                   "os": os.environ.get("RUNNER_OS"), "architecture": os.environ.get("RUNNER_ARCH"),
                   "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion")},
        "workflow": {name: os.environ.get(variable) for name, variable in (
            ("repository", "GITHUB_REPOSITORY"), ("revision", "GITHUB_SHA"),
            ("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("workflow_ref", "GITHUB_WORKFLOW_REF"))},
        "files": [],
    }

    def save() -> None:
        receipt["files"] = [file_receipt(path) for path in sorted(output.iterdir())
                            if path.is_file() and path.name != "manifest.json"]
        (output / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    try:
        if platform.system() != "Darwin" or os.geteuid() == 0:
            raise RuntimeError("Build on macOS as a non-root user with Rust and the Apple toolchain.")
        lock_path = lab / "upstream.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        receipt["upstream_repository"] = lock["repository"]
        receipt["expected_upstream_revision"] = lock["revision"]
        receipt["upstream_lock"] = file_receipt(lock_path)
        receipt["build_script"] = file_receipt(Path(__file__))
        receipt["workflow_source"] = file_receipt(lab / ".github/workflows/build-mxc.yml")
        receipt["lab_revision"] = checked_text(["git", "-C", str(lab), "rev-parse", "HEAD"])
        revision = checked_text(["git", "-C", str(upstream), "rev-parse", "HEAD"])
        if revision != lock["revision"]:
            raise RuntimeError(f"MXC revision differs from upstream.lock.json: {revision}")
        receipt["upstream_revision"] = revision
        receipt["upstream_tree"] = checked_text(["git", "-C", str(upstream), "rev-parse", "HEAD^{tree}"])
        if checked_text(["git", "-C", str(upstream), "status", "--porcelain"]):
            raise RuntimeError("MXC checkout must be clean before building.")
        receipt["upstream_clean_before"] = True
        for key, relative in (("cargo_lock", "src/Cargo.lock"), ("compiler_config", ".cargo/config.toml"),
                              ("dependency_feed_config", ".azure-pipelines/.cargo/config.public.toml"),
                              ("toolchain_config", "src/rust-toolchain.toml")):
            receipt[key] = file_receipt(upstream / relative)
        shutil.copyfile(upstream / "LICENSE.md", output / "LICENSE.md")

        overrides = ("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_DIR",
                     "CARGO_TARGET_" + target.upper().replace("-", "_") + "_RUSTFLAGS")
        for name in overrides:
            if name in os.environ:
                raise RuntimeError(f"{name} is set; remove the override for a recorded upstream build.")
        build_environment = os.environ.copy()
        build_environment["MACOSX_DEPLOYMENT_TARGET"] = "15.0"
        receipt["build_environment"] = {
            "MACOSX_DEPLOYMENT_TARGET": {"inherited": os.environ.get("MACOSX_DEPLOYMENT_TARGET"),
                                        "effective": "15.0", "reason": "Pinned Seatbelt backend requires macOS 15+."},
            "compiler_overrides": {name: "unset" for name in overrides},
        }
        receipt["rustc"] = checked_text(["rustc", "+1.93", "-Vv"], upstream / "src")
        receipt["cargo"] = checked_text(["cargo", "+1.93", "-V"], upstream / "src")
        receipt["clang"] = checked_text(["xcrun", "clang", "--version"])
        receipt["sdk_version"] = checked_text(["xcrun", "--sdk", "macosx", "--show-sdk-version"])
        save()
        with (output / "build.log").open("wb") as log:
            built = subprocess.run(command, cwd=upstream / "src", env=build_environment,
                                   stdout=log, stderr=subprocess.STDOUT)
        receipt["build_exit_code"] = built.returncode
        save()
        if built.returncode:
            raise RuntimeError(f"MXC build exited {built.returncode}; see build.log.")
        clean = not checked_text(["git", "-C", str(upstream), "status", "--porcelain"])
        receipt["upstream_clean_after"] = clean
        if not clean:
            raise RuntimeError("MXC build changed tracked or untracked source.")
        executable = output / "mxc-exec-mac"
        shutil.copy2(upstream / "src/target" / target / "release/mxc-exec-mac", executable)
        receipt["observations"] = {}
        for name, arguments, required in (
            ("file", ["file", str(executable)], True),
            ("dependencies", ["otool", "-L", str(executable)], True),
            ("load_commands", ["otool", "-l", str(executable)], True),
            ("signature", ["codesign", "-d", "--verbose=4", str(executable)], False),
            ("signature_verification", ["codesign", "--verify", "--verbose=4", str(executable)], False),
        ):
            result = subprocess.run(arguments, capture_output=True)
            (output / f"{name}.stdout.txt").write_bytes(result.stdout)
            (output / f"{name}.stderr.txt").write_bytes(result.stderr)
            receipt["observations"][name] = {"command": arguments, "exit_code": result.returncode}
            if required and result.returncode:
                raise RuntimeError(f"{name} inspection exited {result.returncode}.")
        receipt["signing_action"] = "none; compiler/linker output inspected without modification"
        receipt["notarization"] = "not_performed"
        receipt["status"] = "built"
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as failure:
        receipt["status"] = "failed"
        receipt["error"] = str(failure)
        print(str(failure), file=sys.stderr)
        return 1
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == "__main__":
    sys.exit(main())
