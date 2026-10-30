# Observed feasibility results

On 2026-10-30, both Windows MXC executors passed the controlled direct-write
experiment on the littlemac Windows VM. Python and PowerShell started and wrote
inside the assigned workspace. Attempts to create a sibling file and overwrite
an existing sibling sentinel received OS access-denied errors. The controller
independently verified the inside bytes, unchanged sentinel, and absent new file.
Matching unconfined controls succeeded at all three writes.

This establishes useful process startup and denial of these specific direct file
operations with normal user permissions on this host. It does not establish the
complete actor boundary or make the lab a qualified production sandbox.

## Environment and distribution

- Execution host: littlemacwindowsvm; Windows computer name `LITTLEMACWINDOW`.
- Native OS: Windows 11 ARM64, build **26200.9711**.
- Controller token: **non_elevated**, checked with Windows TokenElevation.
- Interpreter: CPython **3.13.15**, x64 under Windows ARM64 emulation.
- PowerShell: in-box Windows PowerShell, controlled inline `-EncodedCommand`;
  writes use `System.IO.File.WriteAllBytes`.
- Final source runs: `arm64-inline-01` and `x64-inline-01`, both exit **0**.
- Their process-local PATH contained only Windows System32 and Windows
  PowerShell. `cargo`, `rustc`, `cl`, `git`, and `node` were unavailable through
  that PATH. No packages, OS features, toolchains, or runtime services were
  installed for these runs; no elevation or execution-policy changes were used.
- The Python ZIP build and extraction also completed under that minimal PATH.
  Running from the extracted copy (`portable-arm64-01`) passed all four cases
  with exit **0**, using the default ARM64 helper and the same harness source
  hashes as the source-checkout run. The retained build receipt identifies the ZIP.

The x64 helper ran under emulation on this ARM64 host. Native x64 hardware has
not been qualified by these local runs.
The later macOS observations are recorded below.

## Direct-write results

Each row used its own newly created fixture. The outside files were siblings of
the permitted workspace, under the task-owned disposable root. The policy gave
read/write access only to the workspace and read access to Windows and, for
Python, its installation. There was no explicit deny rule naming either outside
target, broad user-profile write grant, or ACL-mutating fallback.

| Executor | Payload | Unconfined inside / overwrite / create | Contained inside | Contained outside overwrite / create |
| --- | --- | --- | --- | --- |
| ARM64 native | Python | All succeeded | Succeeded | Both denied; `PermissionError`, errno 13 |
| ARM64 native | PowerShell | All succeeded | Succeeded | Both denied; `UnauthorizedAccessException`, HRESULT `80070005` |
| x64 emulated | Python | All succeeded | Succeeded | Both denied; `PermissionError`, errno 13 |
| x64 emulated | PowerShell | All succeeded | Succeeded | Both denied; `UnauthorizedAccessException`, HRESULT `80070005` |

All payloads completed and exited zero. Native logs identified the
`base-container` tier and zero child exits. This reaches the filesystem checks,
unlike the earlier restricted-token prototype whose CLR failed during startup.
The evaluator requires a successful matching control, completed payload evidence,
OS denial details, independent file observations, and the native backend event.
The controlled payload's nonce correlates output; it is not authentication against
an adversarial payload.

Observed effective profile, AppData and temporary paths stayed inside the
workspace. This is a path observation, not proof that every possible external
location is unwritable. Logs reported successful teardown but
`container_released: false`; complete resource cleanup is not established.

## Native build identity

Both helpers were compiled by [GitHub Actions run 41051644663][build], which
completed successfully at lab commit `94486d1ee49c902461d722843384e0887b0b6a08`.
The builders were `windows-11-arm` and `windows-2025`, using Rust 1.93.1 and
locked dependencies. Native compilation happened on those GitHub-hosted builders.
The hosted build receipts do not prove compilation under a non-elevated
token; the local Python packaging and execution are separate operations.

MXC source: `b4c1007502835d958ab291d332b929187be00440`.

| Executor | Bytes | SHA-256 |
| --- | ---: | --- |
| Windows ARM64 | 4,865,024 | `5b04b55a6228620cc178e96c9047829b9abf77ad48a35c0ff2057be23b445537` |
| Windows x64 | 5,498,368 | `f03fe076c352db0aa9ca71dca9add4dd0aad0a6e0369b8c37c8d975712037f77` |

The adjacent manifests retain source state, toolchain, exact build command,
exit status, runner identity, and hashes. Build logs, PE imports, and MIT licenses
are committed alongside the executors. The source still uses a 1.0.1 product
version; the pinned revision and binary digest distinguish it from the older
published 1.0.1 release. Hash verification binds the supplied bytes and receipt;
it does not authenticate an arbitrary third-party receipt.

## Evidence and remaining scope

The Windows baseline Python test suite passed **20 tests**. These check evidence
evaluation, environment collection and portable packaging; native containment
comes from the experiments above. Full local receipts are retained under
`C:\Users\jonathanmiddleton\.codex\evidence\mcl27`, including per-run source
SHA-256 values, policies, raw process output, and native logs. Working fixtures
were under `C:\Temp\Codex\tasks\mcl27`.

Reproduction should use the [README commands](../README.md). A startup
failure, missing capability, or blocked binary is a feasibility result,
not a confinement pass. Preserve its `report.json` and case receipts.

Unresolved work includes deletes, rename and permission changes; junctions,
symlinks, hardlinks and path aliases; descendants and inherited handles; named
objects and interactions with other processes; native language-server effect
paths; useful tool compatibility; network behavior; lifecycle cleanup; and the
remaining macOS deployment variants. Meadow Runtime and Authoring have not
been changed. The confirmed Bridge issue remains open.

[build]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41051644663

## macOS ARM64 observations (2026-10-30)

The same pinned MXC revision passed the narrow ordinary-file create/overwrite
contract on `littlemac.local`, macOS **15.6** build **24G84**, native ARM64.
The controller ran as UID **501**, with Homebrew CPython **3.15.0** and the
native `/bin/sh` (Bash **3.2.57**). `cargo` and `rustc` were unavailable on the
execution PATH.
Execution required no compiler, package installation, administrator action,
container service, or separately installed sandbox runtime.

| Payload | Unconfined inside / overwrite / create | Contained inside | Contained outside overwrite / create |
| --- | --- | --- | --- |
| Python | All succeeded | Exact 64 bytes matched | Both denied; `PermissionError`, errno **1** (`EPERM`) |
| `/bin/sh` redirection | All succeeded | Exact 64 bytes matched | Both denied; operation exit **1**, `Operation not permitted` |

All four payloads completed with process exit **0**. The controller independently
observed the 66-byte outside sentinel unchanged and the outside new file absent
for each enforced case. Shell diagnostics and individual operation exits were
retained, including the target path. There was no write-target-specific deny
rule or unconfined retry. The explicit read/write directory was only the case
workspace; Python's real installation was granted read-only access.

Case roots resolved `/tmp` to `/private/tmp`; observed HOME, TMPDIR, TEMP and TMP
values stayed inside the workspace. The workload environment was explicit,
with GUI, keychain and nested PTY options disabled and no profile override.
Both policy `--dry-run` commands exited **0**, but those are validation evidence
only. Actual qualification also required completed, correlated payloads,
successful controls, OS denial details, independent bytes, and the pinned
Seatbelt launch path. The `applying sandbox` log occurs before `sandbox_init`
and cannot alone prove successful enforcement; source inspection establishes
that an initialization failure aborts before payload execution.

The source run `arm64-01` and extracted run `portable-arm64-01` both passed all
four cases, controller exit **0**, with identical harness source hashes and
native helper digest. The Python ZIP build and `/usr/bin/unzip` extraction
also exited **0**, preserving executable permissions. These commands ran with
PATH limited to `/usr/bin:/bin:/usr/sbin:/sbin` and a task-owned TMPDIR.
The ZIP receipt records its digest separately from native build provenance.

### macOS native artifact provenance

[GitHub Actions run 41097456118][mac-build] built both targets from lab build
commit `a50521f534368585a37a03255f8ac4177beb7a32`, with Rust **1.93.1**, locked
dependencies, and build exits **0**. Both builders were macOS **15.8.2** ARM64,
UID **501**. ARM64 was built natively; x64 was cross-compiled and has **not been
executed** in this investigation. The deployment target is macOS **15.0**.

| Executor | Bytes | SHA-256 |
| --- | ---: | --- |
| macOS ARM64 | 3,485,296 | `4f985ec32533c5f9279df24b638dbd9d3d048539b1dfbbcde4cdeed0925e40dc` |
| macOS x64 | 3,636,980 | `d6e2bbe9f596d7513e7983f024e8f76997570e29225375e7bc5e9aec58222d15` |

Both artifacts import only `/usr/lib/libSystem.B.dylib`,
`/usr/lib/libsandbox.1.dylib`, and `/usr/lib/libiconv.2.dylib`. The ARM64 output
has an ad-hoc linker signature and passed `codesign --verify`; x64 is unsigned
(signature inspection and verification exit **1**, retained as observations).
Neither artifact was Developer ID signed or notarized. These observations do
not establish Gatekeeper behavior for quarantined downloads or other hosts.
Build logs, dependency/load-command listings, signature observations, manifests
and MIT licenses accompany the native executors. Source and dependency hashes,
clean-tree checks, compiler commands, actual exits and CI identity remain in the
manifests; their `confinement_status` stays `not_tested`.

### macOS evidence and limits

Receipts, raw output, per-case policies, generated Seatbelt profiles in `mxc.log`,
payloads and independent observations are retained locally under
`evidence/macos-20261030/`; disposable fixtures remain under
`/tmp/Codex/tasks/confinement-macos/runs/`. Generated evidence is ignored by Git.
No native startup or confinement failure occurred in these two runs.
The updated Python test suite passed **27 tests**, exit **0**, separately from
the native experiments.

The pinned profile's baseline permits writes to literal `/dev/null`, `/dev/zero`,
`/dev/random`, `/dev/urandom`, and `/dev/tty`, plus extension-gated
`/dev/ttys[0-9]+` terminal access. It also grants system reads and baseline Mach
lookups. The workspace read/write rule includes filesystem Unix-socket bind and
connect. Thus this is evidence about the tested ordinary files, not a claim
that every filesystem-object write is restricted to the workspace tree.

Controlling-terminal/session interactions, IPC, broader descendant behavior,
aliases, inherited handles, deletion/rename/permission operations, native
language-server effects, useful tool compatibility, networking, and complete
lifecycle cleanup remain untested here. Pipes alone do not establish terminal
isolation. The lab has not qualified Intel execution, other Python installations,
quarantined distribution, or Meadow's full actor boundary. Fixtures are retained
for inspection; there were no controller timeouts requiring process reconciliation.

[mac-build]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41097456118

## Shared-candidate Windows regression (2026-10-30)

The Windows coordinator verified implementation candidate
`44c4c51e037929c78b9d11d6aa33c928c8ef7d0c`, whose functional source hashes also
match the macOS source and extracted runs above. On the same littlemac Windows
ARM64 development VM described earlier, CPython 3.13.15 ran the unit suite,
portable ZIP build, extraction, and real packaged experiment under a non-elevated
token. PATH contained only Windows System32 and Windows PowerShell.

- `python -I -m unittest discover -s tests -v`: exit **0**, **25 passed**, with
  **2 native POSIX-shell cases skipped** because no native POSIX shell exists on
  Windows. Both cases passed in the macOS worker's 27-test run.
- `python -I investigate.py build --output <new-zip>`: exit **0**. All four
  native assets passed manifest checks; both macOS ZIP members retained explicit
  Unix `0755` metadata even when packaged on Windows.
- The extracted `investigate.py experiment` completed with exit **0**; Python
  and Windows PowerShell control/enforcement cases all qualified. Inside bytes
  matched, outside sentinels stayed unchanged, outside new files were absent,
  and the Windows `base-container` child-exit events remained required.
- The extracted harness source hashes matched the candidate checkout. Windows
  native assets were unchanged. No timeout occurred or matching owned fixture
  process remained at the post-run check; this is not general lifecycle proof.

Raw unit/controller output, the bundle receipt, policies, payloads, native logs,
and independent observations are retained under
`C:\Users\jonathanmiddleton\.codex\evidence\mclmac`. The retained receipt
identifies the tested ZIP by SHA-256. The implementation now has comparable
ordinary-file feasibility evidence on the two ARM64 development platforms;
the remaining limits above still apply. Subsequent documentation-only recording
does not change the tested functional source.

## Persistent tool worker: Windows (2026-10-30)

The [persistent-worker experiment](worker-experiment.md) passed on the same
Windows ARM64 development VM with CPython 3.13.15 and a non-elevated controller.
Both the native ARM64 helper and the x64 helper under emulation completed the
control and enforcement cases. Each case used one worker for all 11 requests.

| Operation | Unconfined control | Confined worker |
| --- | --- | --- |
| Workspace read/create/write and later read | Correct bytes | Correct bytes |
| Reference read | Correct bytes | Correct bytes |
| Reference overwrite | Succeeded | `PermissionError`, errno 13 |
| Private read/overwrite/create | Succeeded | `PermissionError`, errno 13 |
| Child and grandchild operations in all three roots | All succeeded | Same allowed/denied outcomes as worker |
| Controller private logging between requests | Succeeded | Succeeded |

The controller independently verified exact file bytes, unchanged protected
files and absence of the private new file. The worker remained useful after
denials; command output returned through the request protocol. Both helpers
reported the matching worker PID through their `processcontainer` /
`base-container` zero-exit event. All native invocations exited **0**, completed
their output pipes and required no forced termination. This demonstrates the
controlled worker mechanism, not the production Bridge integration or a complete
security boundary against hostile tools.

Final source runs were `windows-arm64-02` and `windows-x64-02`. The standard-library
ZIP build, fresh extraction, and `portable arm64-02` packaged run also exited
**0**. Source and extracted package hashes matched. Both macOS binary ZIP entries
retained `0755` metadata. The commands ran with PATH containing only Windows
System32 and Windows PowerShell; no compiler, package installation, elevation or
native asset rebuild was used. The Python unit suite ran **34 tests**: **32
passed**, with the same **2 native POSIX-shell cases skipped** on Windows.

Receipts, raw output, policies, transcripts, fixture hashes, native logs, bundle
identity and independent observations are retained under
`C:\Users\jonathanmiddleton\.codex\evidence\mclworker`; the disposable roots were
under `C:\Temp\Codex\tasks\mclworker`. The two native Windows binaries and upstream
revision are unchanged from the identities above. Separate macOS worker
execution evidence follows; earlier direct-write passes do not qualify it.

## Persistent-worker macOS validation (2026-10-30)

Functional candidate `1003cfa8874459046c4c8f05586878d1c8fb84dd` passed the
[persistent worker experiment](worker-experiment.md) on `littlemac.local`,
macOS **15.6** build **24G84**, native ARM64, UID **501**, using CPython
**3.15.0** and the existing committed ARM64 MXC helper. No native artifact,
source pin, or access policy was changed for this validation.

The first unit run on `9c9caa57bd92594250f49d0815c0620ed73cbf14` exited **1**:
33 tests passed and the private-fixture/read-grant overlap test failed. Fixture
construction retained `/tmp/...`, while the read grant resolved to
`/private/tmp/...`; a lexical containment comparison missed the same physical
root. A bounded Python diagnostic reproduced the mismatch and confirmed that
canonical fixture paths were rejected as expected. Candidate `1003cfa` resolves
the root in `prepare_worker_fixture` before storing its paths. The existing test
and policy were preserved. The subsequent complete unit run passed **34 tests**,
exit **0**, with no skips. The original failure receipt remains retained.

| Check on corrected candidate | Actual exit | Observed result |
| --- | ---: | --- |
| Source `worker-experiment`, `source-arm64-02` | 0 | Control and enforced cases qualified; 11 requests each |
| Standard-library ZIP build | 0 | All four existing native assets verified and packaged |
| `/usr/bin/unzip` extraction | 0 | Both macOS helper entries retained executable `0755` permissions |
| Extracted `worker-experiment`, `portable-arm64-02` | 0 | Control and enforced cases qualified; 11 requests each |

Final parent commands used an explicit PATH of `/bin` and a task-owned TMPDIR.
Cargo, Rust, C/C++ compiler shims and build commands were unavailable through
that PATH. The worker retained its configured system PATH, including `/usr/bin`;
no compiler was invoked, and absence of toolchain files on this developer host
is not established. Earlier successful runs with a broader parent system PATH
are retained separately. The source and extracted reports have identical harness
hashes matching the corrected candidate. Both used ARM64 helper SHA-256
`4f985ec32533c5f9279df24b638dbd9d3d048539b1dfbbcde4cdeed0925e40dc`.
The tested ZIP SHA-256 is
`666150fb27d36a6d309d912315de0aa5b4a1d56fa77609f16f8477acd3d23e11`.
Its documentation predates the final wording of this results entry; functional
source is unchanged.

In each enforced case, one persistent worker read workspace and reference
contents, wrote workspace files, and continued successfully after denied
reference overwrite and private read/overwrite/create requests. Those denials
reported `PermissionError`, errno **1**, at the operation stage. Distinct child
and grandchild processes also read/wrote the workspace, read the reference,
and received OS denials for reference writes and private reads/writes. The
unconfined controls completed the corresponding operations successfully.

All 15 independent filesystem observations per case matched expectations,
including unchanged denied-write targets and absence of the enforced private
new file. The controller's private log matched the complete expected sequence
of start, 11 request identifiers, and finish. Workers and synchronous descendants
exited normally; output readers finished, and no helper termination was forced.
The recorded worker/child/grandchild PIDs were absent at the post-run snapshot.
No native failure or timeout occurred. This is evidence for these controlled
processes, not general detached-process cleanup.

Raw initial/final unit output, the path diagnostic, command exits, build and
extraction receipts, native policies/logs, transcripts, controlled payloads,
private controller logs, and independent observations are retained under
`/Users/jonathanmiddleton/.codex/evidence/confinement-worker-macos-20261030`.
Disposable fixtures remain under
`/tmp/Codex/tasks/confinement-worker-macos/runs/`. Networking was explicitly
allowed and was not tested. The experiment retains the documented Seatbelt
baseline, IPC, metadata/device, alias, hostile-code, and lifetime limits;
it does not qualify a production actor or Bridge/Copilot integration.
