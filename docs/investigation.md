# Actor filesystem access investigation

This repository investigates an operating-system boundary for actor-controlled
execution. Bundled Windows and macOS MXC executors and a Python-only lab build
support a controlled direct-write experiment. Non-elevated Windows ARM64 and
macOS ARM64 observations show useful writes inside the workspace and denied
create/overwrite attempts outside it from Python and each platform's shell.
Native compilation and execution evidence are tracked separately. The full
boundary below remains
unqualified; see [recorded results](results.md) for the exact evidence and limits.

## Required boundary

Each actor needs a stated and enforced filesystem access policy covering reads
and writes. The initial policy allows workspace writes, selected read-only
inputs/runtime paths and no access to private controller files. Instructions or
command text naming an external path cannot expand that authority. Effective
backend baseline permissions must be disclosed alongside explicit path grants.

The boundary must cover shell commands, scripts and interpreters, their
descendants, native language-server tools, and direct file-tool effects.
Process cleanup, approval policy, environment redirection, and path validation
are useful controls, but none alone establishes this boundary.

Deployment must support native Windows and macOS from an ordinary non-elevated
Python installation. Required administrator setup, separate user provisioning,
drivers, WSL 2, and an installed container or sandbox runtime are outside scope.
The lab distributes native helpers so cloning, packaging, and running it with a
verified helper do not require a compiler. Optional maintainer compilation of
those dependencies uses a separate toolchain. Their installation, architecture support,
dependencies, licensing, upgrades, and removal remain part of deployment
qualification.

Read and write restrictions are acceptance requirements for the worker experiment.
Network restriction, registry access, availability limits and protection from
kernel vulnerabilities are separate properties. Process/IPC routes remain
relevant if they let actor tools bypass the declared filesystem authority.

The candidate architecture keeps provider/control operations outside the actor
boundary and executes actor filesystem/command tools in a separate confined
worker. This allows actor policy to be narrower than provider runtime needs.
The [persistent-worker experiment](worker-experiment.md) tests that mechanism
without model inference. It does not yet integrate the production Bridge path.

Runtime-owned logging, storage, provisioning, and lifecycle operations remain
trusted and may write outside the actor workspace. This exemption does not
permit Runtime to execute actor-controlled code with unrestricted authority.
Repository hooks, package lifecycle scripts, executable configuration, and
workspace-authored tools invoked by a trusted operation must run inside the
boundary or be excluded from that operation. Trusted code, policy, and broker
credentials must not be replaceable by the actor.

## Starting evidence and its limits

The retained Windows product finding reports a real Coordinator UI Run in which
a Writer called Bridge's `workspace_run_command`. PowerShell used
`System.IO.File.WriteAllBytes` with an absolute destination in the original source
checkout. The working directory was the assigned Run workspace, the command
succeeded, and the external 35-byte file was independently observed. The substrate
was native Meadow Bridge with Copilot language server 1.545.1 in `trusted-host`
mode. No privilege escalation was involved. This is evidence of an actual outside
write, not merely an inaccurate artifact report.

A read-only source inspection of Runtime commit
`c3507f7398fb5fb30e2b3eb7a178b0e789d8374b` corroborates the mechanism:

- [`workspace_tools._command_spec()`][workspace-tools] validates cwd and passes
  command text unchanged.
- [`PreparedShell.argv()` and `OwnedCommands`][owned-commands] execute that text
  with the caller's OS identity. The source explicitly disclaims sandboxing.
- [The Windows process owner][windows-owner] uses `CreateProcessW` and Job
  lifetime ownership, without a restricted token or filesystem policy.
- [The Darwin process owner][darwin-owner] starts an ordinary subprocess and
  owns its process group.
- [Native transport][native-transport] launches the language server through
  those same process owners. Confining only shell callbacks would leave this
  effect path unresolved.
- [Direct file operations][file-publication] check resolved paths and later
  publish through pathnames. This does not establish race-safe confinement;
  no additional race exploit was demonstrated by this inspection.
- [ADR-056][bridge-contract] explicitly distinguishes the fixed `allow_all`
  permission policy from OS sandboxing and complete server-tool control.

These sources support the broader conclusion that arbitrary actor programs have
the current user's authority. They do not establish that every possible effect
path has been exercised, nor do they imply administrator authority.

Earlier exploratory restricted-token probes did not reach their filesystem
payloads. The latest reported PowerShell error was “Starting the CLR failed with
HRESULT 80070005.” Unchanged outside files in those runs are not confinement
passes. The probes establish neither a workable mechanism nor impossibility
under non-elevated deployment. This lab has not rerun or independently qualified
those probes.

The inspected candidate source snapshots are [Microsoft MXC][mxc],
its [process-container OS support notes][mxc-windows] and
[Seatbelt backend notes][mxc-seatbelt], and [Codex's MXC integration notes][codex-mxc].
Review their hard-link and network limitations against the matrix below. The
lab's MXC pin has been built for Windows and macOS ARM64 and x64 in hosted CI;
its build receipts are described in [Native executors](executors.md). The macOS
receipts record a non-root UID; the Windows build receipts do not establish token
elevation. Neither build qualifies source compilation on a restricted end host.

The initial execution evidence comes from the non-elevated
`littlemacwindowsvm`, Windows ARM64 build `26200.9711`. Python and Windows
PowerShell reached their payloads and wrote inside the allowed workspace while
direct outside create and overwrite operations were denied and independently
checked. The x64 helper has only been exercised under emulation on this ARM64
host. Native x64 deployment and the remaining matrix rows require
further evidence; this result does not qualify Meadow Bridge's complete effect
boundary.

On `littlemac.local`, macOS 15.6 ARM64, the same pinned MXC source and its Seatbelt
backend passed the paired Python and `/bin/sh` cases as UID 501. Both the source
checkout and packaged/extracted path passed the same ordinary-file inside-write
and outside-create/overwrite contract. Python reported `PermissionError`, errno
1; shell redirection reported `Operation not permitted` and operation exit 1.
All payloads completed, and the controller independently checked the expected
inside bytes, unchanged outside sentinel, and absent outside new file.

The macOS policy's only explicit writable directory is the case workspace,
with HOME and temporary paths redirected
there. MXC's generated profile additionally grants standard device and terminal
access, system/developer reads, and baseline Mach lookups. The exact allowances
are recorded in [executor policy limits](executors.md#capability-and-platform-limits)
and retained with each native run. They prevent treating the narrow experiment
as proof that all filesystem writes are confined to the workspace.

## Comparable native experiments

Each experiment owns disposable sibling directories: an allowed workspace, an
outside sentinel area, and a second Run workspace. No probe targets real source
checkouts, user configuration, credentials, or another live process. Runtime
scratch, interpreter caches, and temporary files should be directed into the
allowed workspace. Any unavoidable extra writable location must be documented
as a deviation from the requested boundary, not silently added to a pass policy.

The independent controller records initial sentinel bytes and metadata, launches
the restricted workload, and inspects effects after all owned processes settle.
An actor's report is supporting output, not the sole oracle. A successful startup
or zero exit status is not a security result.

| Surface | Useful allowed behavior required | Outside behavior to attempt and independently inspect |
| --- | --- | --- |
| Native startup | A small process starts, reports its effective execution context, and writes inside | Loader/startup failure is `not reached`, never a denied-write pass |
| Windows PowerShell | Start the CLR; create, read back, edit, rename, and delete inside | Absolute and relative external writes through cmdlets and direct .NET file APIs |
| Python | Import ordinary standard-library modules and run the same inside operations | `open`, `os`, `pathlib`, subprocesses, and direct OS calls where needed to distinguish enforcement from wrappers |
| Node.js | Start its runtime and perform inside operations | Filesystem APIs and spawned programs targeting the sentinel area |
| macOS shell | Run native `/bin/sh` plus available Python and Node witnesses | Shell redirection, utilities, and direct file APIs outside the workspace |
| Descendants | A child and grandchild perform inside work | Outside effects from descendants, alternate launch paths, and surviving/background children |
| Native language server | Complete a real supported tool operation inside the workspace | Server-owned filesystem and process effects, separate from Bridge callbacks |
| Direct file broker | Create and edit inside through the public tool request | External names, substitutions between validation and use, and callback requests from restricted code |
| Aliases and object identity | Ordinary in-workspace paths remain usable | Symlinks, Windows junctions/reparse points, hard links, path aliases, and mapped/UNC paths where available |
| Handles and permissions | Only necessary standard streams and controlled handles are inherited | Pre-opened outside writable handles, handle transfer, ACL/ownership changes, and rights that would enable a later write |
| Process and IPC access | Required request/response channels work | Access to the controller or another user process, local brokers/services, and other routes that could perform an unrestricted write |
| Concurrent Runs | Each Run writes its own workspace | Cross-Run writes, reused identities, shared writable caches, and policy or grant leakage after cleanup |
| Trusted operations | Logs and lifecycle operations remain functional | Actor-controlled hooks or tools causing trusted code to write outside on the actor's behalf |

Not every row is applicable to every mechanism or host. Record the reason and
remaining exposure explicitly. Missing privileges to construct a test alias are
a coverage limit; a malicious child failing to start is a startup failure. Neither
is evidence that a reachable operation was denied.

## Investigation sequence

The persistent worker described above passed its controlled read/write/command
contract on both development platforms. The next integration step connects that
worker behind a real Copilot/Bridge turn while preserving the provider/tool
authority split. The broader sequence below is a coverage inventory, not a
requirement to complete every generic probe before useful work.

1. **Specify one candidate.** Pin source and license, identify the actual kernel
   enforcement primitive, enumerate writable grants and broker interfaces, and
   explain its non-elevated installation path. Distinguish documented guarantees
   from implementation observations and hypotheses.
2. **Prove startup and ordinary work.** Run a small native witness, then the real
   platform shell and Python/Node interpreters. Each must reach its payload and
   successfully write inside before its outside results are assessed. Capture
   loader/runtime errors without broadening grants speculatively.
3. **Prove the narrow write policy.** Exercise create, overwrite, append, delete,
   rename, directory operations, and permission changes against owned outside
   sentinels. Check effects, bytes, metadata, and process settlement independently.
4. **Challenge alternate paths.** Exercise descendants, aliases, races, inherited
   handles, IPC, sibling Runs, and cleanup. A path-based rule must survive changes
   in how the same external object is addressed.
5. **Compose real effect owners.** Apply the candidate to shell commands, native
   server processes and their children, and direct broker operations. Establish
   which component enforces each path; cataloguing a tool is not enforcement.
6. **Qualify deployment and product behavior.** Repeat on native Windows and
   macOS using the distributable installation, then validate the actual Meadow
   Coordinator journey. Confirm useful artifacts appear inside the recorded Run
   workspace, external sentinels remain unchanged, and trusted persistence and
   cleanup still work. Feasibility in this lab alone does not qualify Meadow.

A candidate that only works after elevation, requires a forbidden runtime, or
cannot start the required workload does not satisfy this deployment target.
Preserve useful findings and the exact failing stage; do not infer universal
impossibility from one candidate's failure.

## Evidence to retain

For each execution, retain host identity, OS/build and architecture, source
commit, helper/runtime versions and hashes, effective non-elevated identity,
admitted root and grants, exact command, sanitized environment, start/end times,
exit status, stdout/stderr, inside-write evidence, outside observations, and
child/cleanup results. Do not record authentication secrets.

Give every matrix case an explicit result such as `pass`, `fail`, `not reached`,
or `not run`, plus the observation supporting it. A denied outside operation
passes only when the intended workload reached that operation, useful allowed
work succeeded, the relevant outside object was independently checked, and no
alternate effect escaped. Preserve unexpected outside effects as failures even
if the command returned an error.

Current status: Windows and macOS executors are available from the clone, and
narrow non-elevated direct-write evidence is recorded on ARM64 hosts for both
platforms. Native macOS x64 execution is untested. No candidate is qualified for
the complete Meadow boundary. [Results](results.md) distinguish the completed
cases from unsupported, unreached, and untested behavior.

[workspace-tools]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/workspace_tools.py#L804-L843
[owned-commands]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/owned_commands.py#L81-L98
[windows-owner]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/_owned_command_windows.py#L352-L430
[darwin-owner]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/_owned_command_posix.py#L100-L122
[native-transport]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/native_transport.py#L47-L60
[file-publication]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/meadow/substrates/meadow_bridge/execution/workspace_tools.py#L932-L965
[bridge-contract]: https://github.com/jonathanmiddleton/meadow-runtime/blob/c3507f7398fb5fb30e2b3eb7a178b0e789d8374b/adrs/056-direct-substrate-registration.md#L253-L269
[mxc]: https://github.com/microsoft/mxc/tree/b4c1007502835d958ab291d332b929187be00440
[mxc-windows]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/process-container/os-version-support.md
[mxc-seatbelt]: https://github.com/microsoft/mxc/blob/b4c1007502835d958ab291d332b929187be00440/docs/backends/seatbelt/seatbelt-backend.md
[codex-mxc]: https://github.com/openai/codex/blob/f752c97f7d0be0cbef5cece327f52a16ad6fb1c6/codex-rs/mxc-sandbox/README.md
