# Native executors

The repository includes Windows ARM64 and x64 MXC executors under `native/`.
Cloning the lab supplies these dependencies; building a lab ZIP and running the
Windows experiment require Python 3.11+ and the standard library, without Rust,
MSVC, package installation, administrator setup, WSL, or a container service.
The host still needs the native Windows capabilities used by MXC.

The executors were built from the revision in [upstream.lock.json](../upstream.lock.json),
`b4c1007502835d958ab291d332b929187be00440`, using native PSEC only. The published
upstream `v1.0.1` release has different fallback behavior and is not a substitute.

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
must be new and its parent directory must exist.

On a non-elevated Windows host, use the clone or extracted ZIP:

```text
python investigate.py environment --output evidence/host.json
python investigate.py experiment --output-root runs/direct-write-01
```

The experiment requires the real Python interpreter used to launch it and
Windows PowerShell. It selects a bundled helper for the architecture reported
by Python. When deliberately testing another architecture, supply its path with
`--executor`; emulated execution must be reported separately from native host
validation. Each output root must be new. All attempted writes target disposable
fixtures beneath that root, including the outside-workspace sentinels.

The experiment checks direct create and overwrite attempts from Python and
Windows PowerShell, with independent file observations and matching unconfined
controls. Its result is narrower than the full boundary in
[the investigation](investigation.md). See [recorded results](results.md) for
the evidence obtained on `littlemacwindowsvm` and its remaining limits.

## Recorded executor builds

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

## Optional maintainer rebuild

Rebuilding the third-party executors is separate from building or running the
lab. The [build workflow](../.github/workflows/build-mxc.yml) runs manually or
when a tag matching `mxc-build-*` is pushed. It checks out the pinned upstream
revision, builds the narrow `wxc-exec` target for both architectures, and uploads
the artifact directories. It runs no confinement experiments.

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
2. Actual process startup and useful work inside the allowed workspace.
3. Independent observations of denied outside effects.

MXC's current `--probe` does not create a contained process. An API export or a
supported-looking Windows build is not proof of successful launch or
confinement. Windows requirements are in the pinned [OS support table][windows].
Unsupported requests must fail; never retry an actor payload without confinement
to make an experiment pass. The explicit unconfined controls are separate owned
fixtures whose purpose is to prove the attempted outside operations are possible.

No macOS executor is bundled or validated yet. MXC's `mxc-exec-mac` uses Seatbelt;
its pinned [backend guide][seatbelt] specifies macOS 15 or later. Native macOS
builds, non-elevated execution, signing/notarization, and distribution remain to
be investigated. Do not run upstream host-preparation scripts or elevate a
restricted-host experiment to change its outcome.

[build-run]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41051644663
[seatbelt]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/seatbelt/seatbelt-backend.md
[windows]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/process-container/os-version-support.md
