# Native executors

No native executor has been built or qualified by this repository yet. The
commands below are derived from the pinned MXC source, not recorded successful
builds. `upstream.lock.json` identifies that source.

## Developer host

Use a clean MXC checkout at `b4c1007502835d958ab291d332b929187be00440`.
The sibling `../mxc` is convenient locally but is not a remote-host dependency.
For an independent developer checkout:

```text
git clone https://github.com/microsoft/mxc.git vendor/mxc
git -C vendor/mxc checkout --detach b4c1007502835d958ab291d332b929187be00440
git -C vendor/mxc status --short
```

Windows builds need Rust 1.93, the matching Rust target, MSVC, and the Windows SDK
(including the resource compiler and linker). From the upstream `src` directory,
build only the executor for the destination architecture:

```text
cargo build --locked --release -p wxc --bin wxc-exec --target x86_64-pc-windows-msvc --no-default-features
```

For Windows ARM64, replace the target with `aarch64-pc-windows-msvc`.
The expected output is `src/target/<target>/release/wxc-exec.exe`. Upstream's
`.cargo/config.toml` selects a static CRT; preserve those flags and verify the
actual binary's dependencies before calling it portable. The minimal build does
not request WSL, VM, Node SDK or .NET SDK components.

macOS uses MXC's `mxc-exec-mac` and Seatbelt backend. Build and validate it on a
native Mac following the pinned [backend guide][seatbelt] and upstream build
instructions. Signing/notarization and distribution remain to be investigated.

Do not run upstream host-preparation scripts or request elevation to make a
candidate pass. That would change the deployment conditions under investigation.

## Artifact provenance

Before transporting a helper, record its actual:

- Full upstream revision, clean-tree state and `src/Cargo.lock` SHA-256.
- Compiler version, target, exact build command and exit status.
- Binary filename, size, SHA-256 and reported version.
- Investigation revision and hashes of every bundled file.

Include MXC's `LICENSE.md`. Keep the archive digest outside the archive. Version
text alone is insufficient: this development source still uses a version label
also used by an earlier release. Never invent checksums for an unbuilt artifact.
The binary delivery mechanism will be selected once a candidate exists; generated
binaries are not committed by this bootstrap.

## Restricted host

The intended inputs are this clone, ordinary Python, a matched executor bundle,
and the native OS features. No compiler or privileged setup belongs here.
First run the environment collector. Later executor probes must separately record:

1. Native API/capability discovery, including any upstream `--probe` output.
2. Actual process startup and useful work inside the allowed workspace.
3. Independent observations of denied outside effects.

MXC's current `--probe` does not create a contained process. An API export or
supported-looking Windows build is not proof of successful launch or confinement.
Windows requirements are in the pinned [OS support table][windows]. The macOS
backend documents macOS 15 or later. Hosts lacking required capabilities must
produce an unsupported result; do not retry the payload without confinement.

[seatbelt]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/seatbelt/seatbelt-backend.md
[windows]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/process-container/os-version-support.md
