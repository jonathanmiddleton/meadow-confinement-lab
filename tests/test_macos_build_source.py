"""Build provenance follows the real Git source state without compiling MXC."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))

from build_mxc_macos import prepare_patched_source, verify_source_unchanged


class MacosBuildSourceTests(unittest.TestCase):
    def test_patch_is_the_only_admitted_source_change(self):
        with tempfile.TemporaryDirectory(prefix="mxc-build-source-") as temporary:
            upstream = Path(temporary)

            def git(*arguments):
                subprocess.run(["git", "-C", str(upstream), *arguments], check=True,
                               capture_output=True)

            git("init", "--quiet")
            profile = upstream / "src/mxc-sdk/src/backends/seatbelt/common/profile_builder.rs"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                'const BASELINE_ALLOW: &str = "\\\n'
                ';; --- baseline (required for any process to start) ---\n'
                '(allow process-fork)\n(allow process-exec)\n'
                '(allow signal (target same-sandbox))\n(allow sysctl-read)\n'
                '(allow file-read-metadata)\n";\n', encoding="utf-8", newline="\n")
            git("add", ".")
            git("-c", "user.name=Build fixture", "-c", "user.email=fixture@example.invalid",
                "commit", "--quiet", "-m", "Fixture source")
            prepared = prepare_patched_source(
                upstream, REPOSITORY / "patches/mxc-seatbelt-posix-semaphores.patch")
            self.assertIn("(allow ipc-posix-sem)", profile.read_text(encoding="utf-8"))
            verify_source_unchanged(upstream, prepared)
            with self.assertRaisesRegex(RuntimeError, "must be clean"):
                prepare_patched_source(
                    upstream, REPOSITORY / "patches/mxc-seatbelt-posix-semaphores.patch")

            patched_bytes = profile.read_bytes()
            profile.write_bytes(patched_bytes + b"// unexpected compiler mutation\n")
            with self.assertRaisesRegex(RuntimeError, "changed source"):
                verify_source_unchanged(upstream, prepared)
            profile.write_bytes(patched_bytes)

            unexpected = upstream / "unexpected-source.rs"
            unexpected.write_text("// untracked compiler mutation\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed source"):
                verify_source_unchanged(upstream, prepared)
            unexpected.unlink()
            verify_source_unchanged(upstream, prepared)


if __name__ == "__main__":
    unittest.main()
