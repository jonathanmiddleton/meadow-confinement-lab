# Native executors

The lab uses native MXC executors under `native/` for Windows and macOS.
Windows and macOS ARM64 and x64 executors are committed. Building a lab ZIP and
running an experiment with a verified executor require Python 3.11+ and the
standard library, without Rust,
package installation, administrator setup, WSL, or a container service. The host
still needs the OS capabilities used by its MXC backend.

The executors were built from the revision in [upstream.lock.json](../upstream.lock.json),
`b4c1007502835d958ab291d332b929187be00440`. Windows uses native PSEC only; macOS
uses Seatbelt. The published upstream `v1.0.1` release has different fallback
behavior and is not a substitute.

## Build and run the lab

From a clone, package the lab into a new ZIP:

```text
python investigate.py build --output lab-bundle.zip
```

This is a Python packaging operation. It verifies the bundled executors against
their manifests and the upstream source pin, then includes the Python code,
documentation, executor binaries, manifests, and licenses. It does not compile
native code or download dependencies. The printed receipt includes the ZIP's
SHA-256; retain it separately when transporting the archive. The output filename
must be new and its parent directory must exist. ZIP entries for macOS helpers
carry Unix `0755` permissions, including when the ZIP is built on Windows.
Extract on macOS with `/usr/bin/unzip` or another extractor that restores those
permissions. Python's `zipfile.extractall` does not restore executable bits; the
controller reports this condition without silently changing the extracted file.

On a non-elevated Windows or macOS host, use the clone or extracted ZIP
(`python3` is usually the macOS command):

```text
python investigate.py environment --output evidence/host.json
python investigate.py experiment --output-root runs/direct-write-01
```

The experiment requires the real Python interpreter used to launch it, plus
Windows PowerShell on Windows or `/bin/sh` on macOS. It selects a bundled helper
for the OS and architecture reported by Python. When deliberately testing
another architecture, supply its path with `--executor`; emulated execution must
be reported separately from native host
validation. Each output root must be new. All attempted writes target disposable
fixtures beneath that root, including the outside-workspace sentinels.

The experiment checks direct create and overwrite attempts from Python and
the platform shell, with independent file observations and matching unconfined
controls. Its result is narrower than the full boundary in
[the investigation](investigation.md). See [recorded results](results.md) for
the observations and remaining limits for each tested host.

## Recorded Windows executor builds

[GitHub Actions run 41051644663][build-run] built both executors successfully
with Rust 1.93.1 and zero build exit codes:

| Artifact | Target | Hosted runner | Receipt |
| --- | --- | --- | --- |
| `native/windows-arm64/wxc-exec.exe` | `aarch64-pc-windows-msvc` | `windows-11-arm` | [ARM64 manifest](../native/windows-arm64/manifest.json) |
| `native/windows-x64/wxc-exec.exe` | `x86_64-pc-windows-msvc` | `windows-2025` | [x64 manifest](../native/windows-x64/manifest.json) |

Each directory retains the executor, MXC's MIT license, build log, PE import
listing, and manifest. The manifests record source identity and clean-tree
checks, Cargo.lock and configuration hashes, compiler versions, exact commands,
runner images, workflow identity, binary size, and SHA-256. The PE listings were
captured successfully with `dumpbin`; dependency portability still needs
validation on each intended deployment host. These are lab-built upstream
executors, not Microsoft-signed releases.

Hosted compilation establishes the origin of the native dependencies. It does
not demonstrate that compiling MXC from source works under a normal user account
on a restricted machine. The supported lab build uses those existing binaries.
Build manifests correctly retain `confinement_status: not_tested`: native
execution results are separate evidence, recorded after compilation.

## Recorded macOS executor builds

[GitHub Actions run 41097456118][macos-build-run] built the same pinned MXC
revision at lab build-workflow commit
`a50521f534368585a37a03255f8ac4177beb7a32`. Both builds exited zero using Rust
1.93.1, locked dependencies, and the narrow `mxc_darwin` package. The hosted
builders reported macOS 15.8.2, ARM64, and effective UID 501.

| Artifact | Target | Compilation | Receipt |
| --- | --- | --- | --- |
| `native/macos-arm64/mxc-exec-mac` | `aarch64-apple-darwin` | Native ARM64 | [ARM64 manifest](../native/macos-arm64/manifest.json) |
| `native/macos-x64/mxc-exec-mac` | `x86_64-apple-darwin` | Cross-compiled on ARM64 | [x64 manifest](../native/macos-x64/manifest.json) |

The [macOS build script](../scripts/build_mxc_macos.py) requires a non-root
effective UID and records the actual build exit, source cleanliness and tree,
Cargo.lock and compiler/configuration hashes, build command, compiler versions,
target, macOS deployment target, runner and workflow identity, artifact bytes,
and SHA-256. It retains the MIT license and `file`, `otool`, and `codesign`
observations. It performs no explicit signing, notarization, or confinement run.
The ARM64 linker output had a valid ad-hoc signature; x64 was unsigned. Both
artifacts import only `/usr/lib/libSystem.B.dylib`,
`/usr/lib/libsandbox.1.dylib`, and `/usr/lib/libiconv.2.dylib`, and record a minimum
macOS version of 15.0. Build status and signature observations do not establish
Gatekeeper acceptance or execution on another Mac. Native x64 execution remains
untested.

The ARM64 helper passed the paired Python and `/bin/sh` experiment on a separate
macOS 15.6 ARM64 host as UID 501, both from the checkout and an extracted lab ZIP.
No Rust compiler was invoked; `cargo` and `rustc` were unavailable on the
execution PATH. These runtime observations are
recorded separately in [results](results.md); they do not change the build
manifests' `confinement_status: not_tested`.

## Optional maintainer rebuild

Rebuilding the third-party executors is separate from building or running the
lab. The [build workflow](../.github/workflows/build-mxc.yml) runs manually or
when a tag matching `mxc-build-*` is pushed. It checks out the pinned upstream
revision, builds the narrow `wxc-exec` or `mxc-exec-mac` target, and uploads
the artifact directories. It runs no confinement experiments.

Manual dispatch accepts `platform=windows`, `platform=macos`, or `platform=all`.
The macOS jobs use Rust 1.93 and the Apple developer toolchain, build both
architectures, and set `MACOSX_DEPLOYMENT_TARGET=15.0`. No host-preparation script
or elevation is part of the build. These developer tools are build dependencies;
the resulting lab deployment uses the committed executors.

For a developer-host rebuild, obtain a clean checkout at the source pin and use
[scripts/build_mxc.ps1](../scripts/build_mxc.ps1):

```text
pwsh -NoProfile -File scripts/build_mxc.ps1 -Architecture arm64 -UpstreamDirectory ../mxc
```

Use `x64` for an x64 destination. This optional source build requires Rust 1.93,
the matching Rust target, MSVC, and the Windows SDK, including its resource
compiler and linker. The script preserves upstream's static CRT and hardening
flags, uses its public dependency feed, and records the build. It requests no
WSL, VM, IsolationSession, Node SDK, or .NET SDK feature.

Before replacing a committed executor, verify the successful workflow and
manifest, compare the downloaded executable's actual size and hash, and retain
its license and build evidence. Version text alone is insufficient: both this
development source and the older release use a `1.0.1` package version. Keep
native artifact changes reviewable alongside their new source pin and receipts.

## Capability and platform limits

Keep these stages distinct:

1. Native API/capability discovery, including any upstream `--probe` output.
   On macOS, `--dry-run` validates the policy without executing the payload.
2. Actual process startup and useful work inside the allowed workspace.
3. Independent observations of denied outside effects.

MXC's current `--probe` does not create a contained process. An API export or a
supported-looking Windows build is not proof of successful launch or
confinement. Windows requirements are in the pinned [OS support table][windows].
Unsupported requests must fail; never retry an actor payload without confinement
to make an experiment pass. The explicit unconfined controls are separate owned
fixtures whose purpose is to prove the attempted outside operations are possible.

MXC's `mxc-exec-mac` uses Seatbelt; its pinned [backend guide][seatbelt] specifies
macOS 15 or later. The lab selects Seatbelt explicitly, disables GUI, Keychain,
and nested-PTY options, and uses no profile override. Its only explicit writable
directory is the disposable workspace. The generated profile still includes
MXC's baseline writable literals `/dev/null`, `/dev/zero`, `/dev/random`,
`/dev/urandom`, and `/dev/tty`, plus `/dev/ttys[0-9]+` access gated by a sandbox
PTY extension. It also includes system/developer read grants and baseline Mach
lookups. These are deviations from an all-filesystem-objects write boundary;
they are not evidence that ordinary sibling files are writable.
Workspace read/write grants also permit Unix-domain socket operations under that
root. Socket and other IPC routes have not been exercised by this experiment.

The controller retains the generated profile in each enforced case's `mxc.log`.
It requires the pinned sandbox-init launch path plus a completed payload,
matching successful control, OS-denial diagnostics, and independently checked
file bytes. The pinned executor aborts spawn if `sandbox_init` fails. The log
marker or policy dry run alone cannot qualify a case. Wider IPC, descendant,
device, signing/notarization, and deployment behavior remain separate questions.
Controlling-terminal and session interactions are untested; captured pipes alone
do not establish terminal isolation or session detachment.
Do not run upstream host-preparation scripts or elevate a restricted-host
experiment to change its outcome.

[build-run]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41051644663
[macos-build-run]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41097456118
[seatbelt]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/seatbelt/seatbelt-backend.md
[windows]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/process-container/os-version-support.md
