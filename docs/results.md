# Observed Windows feasibility results

On 2026-10-30, both committed MXC executors passed the controlled direct-write
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

The x64 helper ran under emulation on this ARM64 host. It has **not** been
qualified on native x64 hardware or on the user's restricted remote host.
macOS native execution has not been tested.

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
locked dependencies. Native compilation happened there, not on the restricted
host. The hosted build receipts do not prove compilation under a non-elevated
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

The maintained Python test suite passed **20 tests**. These check evidence
evaluation, environment collection and portable packaging; native containment
comes from the experiments above. Full local receipts are retained under
`C:\Users\jonathanmiddleton\.codex\evidence\mcl27`, including per-run source
SHA-256 values, policies, raw process output, and native logs. Working fixtures
were under `C:\Temp\Codex\tasks\mcl27`.

Remote reproduction should use the [README commands](../README.md). A remote
startup failure, missing capability, or blocked binary is a feasibility result,
not a confinement pass. Preserve its `report.json` and case receipts.

Unresolved work includes deletes, rename and permission changes; junctions,
symlinks, hardlinks and path aliases; descendants and inherited handles; named
objects and interactions with other processes; native language-server effect
paths; useful tool compatibility; network behavior; lifecycle cleanup; and the
macOS implementation and distribution. Meadow Runtime and Authoring have not
been changed. The confirmed Bridge issue remains open.

[build]: https://github.com/jonathanmiddleton/meadow-confinement-lab/actions/runs/41051644663
