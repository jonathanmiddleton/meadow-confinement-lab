# Meadow confinement lab

Standalone investigation of OS-enforced workspace write confinement for Meadow
on Windows and macOS. The deployment target is ordinary, non-elevated Python
with no required WSL, container service, compiler, or administrator setup.

**Current result:** on our Windows 11 ARM64 host, Python and Windows PowerShell
started inside MXC's native process container, wrote inside the workspace, and
received access denied for direct creation and overwrite of sibling files.
Matching unconfined controls could perform those same outside writes. This is a
narrow feasibility result; full actor confinement and macOS remain unestablished.
See [results and limits](docs/results.md).

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
an unconfined launch. macOS currently supports environment collection only.

Choose a new output directory for every experiment. All write targets are
disposable files under that directory, divided into a workspace and its outside
sibling. The unconfined control deliberately writes to both; the contained case
must write inside and fail outside. No real source checkout or user file is a
probe target. PowerShell executes controlled inline code calling
`System.IO.File.WriteAllBytes`; Python uses `Path.write_bytes`.

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
parent must exist, and an existing ZIP is not overwritten.

Native MXC source compilation is a separate maintainer operation using Rust,
MSVC, and the Windows SDK on GitHub-hosted Windows builders. The committed
binaries are self-built and unsigned. Their manifests and build logs record
source/toolchain identity and hashes; these establish provenance, not a complete
security qualification. See [executor provenance](docs/executors.md).

## Development and investigation

```text
python -m unittest discover -s tests -v
```

Unit tests check the controller, evaluator, and package builder. The real native
experiment supplies the separate OS evidence. The broader
[investigation](docs/investigation.md) includes descendants, path aliases, other
write operations, native-server tools, lifecycle, and macOS.

Microsoft MXC is pinned in [upstream.lock.json](upstream.lock.json) after removal
of its older Windows fallback paths. Its published `v1.0.1` release is not
equivalent and must not replace these assets. This repository is independent of
the sibling Runtime, Authoring, and MXC checkouts; running the lab needs none
of them. Generated reports and fixtures belong in ignored `evidence/` or `runs/`
directories, or an explicitly selected external directory.
