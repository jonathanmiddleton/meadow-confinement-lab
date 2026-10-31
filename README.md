# Meadow confinement lab

Standalone investigation of OS-enforced actor filesystem access for Meadow
on Windows and macOS. The deployment target is ordinary, non-elevated Python
with no required WSL, container service, compiler, or administrator setup.

**Current result:** on the tested Windows 11 ARM64 and macOS 15.6 ARM64 hosts,
a persistent worker completed repeated read/write/command requests under MXC:
workspace read/write, reference files read-only, and private-file reads/writes
denied by the OS. A child and grandchild obeyed the same sampled permissions,
while the trusted controller retained private logging access. Matching unconfined
controls and extracted-package runs passed. This qualifies the controlled worker
mechanism; production Bridge integration and full actor confinement remain open.
See [results and limits](docs/results.md).

## Persistent tool worker

```text
python investigate.py worker-experiment --output-root runs/worker-01
```

Use `python3` on macOS. This experiment sends repeated read/write/command
requests to a separate worker: workspace read/write, reference files read-only,
and private controller files denied. It checks continued operation after denial,
child/grandchild access and independent file bytes, with an unconfined control.
It needs only ordinary Python and the committed helpers. See the
[worker experiment](docs/worker-experiment.md) for the exact scope and receipts.

## Clone and run on Windows

```text
git clone https://github.com/jonathanmiddleton/meadow-confinement-lab.git
cd meadow-confinement-lab
python investigate.py environment --output evidence/host.json
python investigate.py experiment --output-root runs/direct-write-01
```

Use Python 3.11 or later (`py -3` can replace `python`) in an ordinary terminal.
Cloning includes the x64 and ARM64 native executors; no pip install, Rust, MSVC,
WSL, or other sandbox runtime is needed. The private repository requires your
usual GitHub access to clone; the experiment itself uses no network. It invokes
Windows PowerShell and the architecture-matched executable after verifying its
source pin, build receipt, size, and SHA-256.

The selected Windows backend requires native Process Security Container support.
The pinned upstream lists Windows 11 24H2 build 26100.9278 or later, or 25H2 build
26200.9278 or later. Actual process launch and write results determine success;
the version and capability probe alone do not. The lab does not install Windows
features, request elevation, change PowerShell execution policy, or fall back to
an unconfined launch.

## Run on macOS

Use Python 3.11+ in an ordinary terminal on macOS 15 or later:

```text
python3 investigate.py environment --output evidence/macos-host.json
python3 investigate.py experiment --output-root runs/macos-direct-write-01
```

The macOS path selects `native/macos-arm64/mxc-exec-mac` or
`native/macos-x64/mxc-exec-mac` from Python's reported architecture. The committed
executors have successful build manifests matching the source pin, size, and
SHA-256; each run verifies them. No Rust, Xcode, package installation, or installed
sandbox service is required to run the lab. Native execution has been observed
for ARM64; the x64 executor is built but has not been executed.

Python and `/bin/sh` run paired controls and Seatbelt cases. Python uses
`Path.write_bytes`; the shell uses direct redirection and retains the operation
exit and OS diagnostic. HOME and temporary directories are inside the workspace.
The policy has no explicit writable directory outside the workspace, but pinned
Seatbelt includes device and terminal allowances; see
[policy limits](docs/executors.md#capability-and-platform-limits). A pass concerns
the tested ordinary-file operations, not every filesystem object.

## Experiment evidence

Choose a new output directory for every experiment. All write targets are
disposable files under that directory, divided into a workspace and its outside
sibling. The unconfined control deliberately writes to both; the contained case
must write inside and fail outside. No real source checkout or user file is a
probe target. Windows PowerShell executes controlled inline code calling
`System.IO.File.WriteAllBytes`.

Each run retains `report.json`, policies, payloads, raw stdout/stderr, native logs,
and independently observed file hashes. Exit 0 means the narrow cases passed;
exit 1 means a case failed, and exit 2 means setup or controller failure. Startup
failure never counts as containment. If execution times out, preserve the report
and reconcile its processes before rerunning. The lab retains fixtures for
inspection rather than claiming full lifecycle cleanup.

Reports contain local paths, OS/Python details, selected tool locations, and the
explicit test environment. They do not dump your inherited environment or read
credentials. Share the report and case receipts when comparing experiment results.

## Build a portable copy

```text
python investigate.py build --output ../meadow-confinement-lab.zip
```

This build needs only Python's standard library and normal user permissions. It
packages the Python source, documentation, source pin, and verified committed
executors into a new ZIP. Extract it and use the same commands above. The output
parent must exist, and an existing ZIP is not overwritten. On macOS, extract
with a tool that restores the stored Unix executable permissions:

```text
/usr/bin/unzip ../meadow-confinement-lab.zip -d ../meadow-confinement-lab-portable
```

Python's `zipfile.extractall` does not restore these permissions. The controller
reports a non-executable helper instead of changing its permissions silently.
The ARM64 macOS direct-write experiment also passed from a ZIP extracted with
`/usr/bin/unzip`; see the retained [results](docs/results.md).

Native MXC source compilation is a separate maintainer operation using Rust and
platform developer tools on GitHub-hosted builders. The executors are lab builds
of pinned upstream source. Their manifests and build logs record
source/toolchain identity and hashes; these establish provenance, not a complete
security qualification. The macOS rebuild recipe additionally applies a
maintained POSIX semaphore patch and records its hash separately from the
upstream revision. See [executor provenance](docs/executors.md).

## Development and investigation

```text
python -m unittest discover -s tests -v
```

Unit tests check the controller, evaluator, and package builder. The real native
experiment supplies the separate OS evidence. The broader
[investigation](docs/investigation.md) includes descendants, path aliases, other
write operations, native-server tools, lifecycle, and wider platform deployment.

Microsoft MXC is pinned in [upstream.lock.json](upstream.lock.json) after removal
of its older Windows fallback paths. Its published `v1.0.1` release is not
equivalent and must not replace these assets. This repository is independent of
the sibling Runtime, Authoring, and MXC checkouts; running the lab needs none
of them. Generated reports and fixtures belong in ignored `evidence/` or `runs/`
directories, or an explicitly selected external directory.
