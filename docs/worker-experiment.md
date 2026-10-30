# Persistent tool-worker experiment

Run from a clone with ordinary Python 3.11+ and the committed native executors:

```text
python investigate.py worker-experiment --output-root runs/worker-01
```

On macOS use `python3`. Choose a new output directory each time. No package
installation, provider credentials, compiler, elevation or container service is
needed. The command uses the same supported native backends and artifact
verification as the [direct-write experiment](executors.md).

## What runs

A trusted Python controller launches one persistent Python worker through MXC.
The worker receives JSON-line requests over stdin and returns correlated frames
over stdout. It performs file reads, file writes and a synchronous command.
Command output is captured inside its result; it cannot become worker protocol
frames. Native diagnostics go to separate files. The worker applies no pathname
permission filter: the OS must supply the denial evidence.

Each control/enforcement case creates disjoint disposable roots:

| Root | Confined worker access | Controller access |
| --- | --- | --- |
| `workspace` | Read/write | Read/write |
| `reference` | Read-only | Read/write |
| `private` | No content read/write grant | Read/write |
| `executor-code` | Read-only controlled worker/payload source | Read/write |

Python installation and OS baseline reads are also allowed. HOME, profile/cache
locations and temporary files are directed into the workspace. Private fixtures
overlapping an interpreter/code read grant are rejected. Filesystem roots are
resolved before launch. Native networking is explicitly allowed; this experiment
does not establish or require network restriction.

The controller sends 11 requests to the same worker: allowed workspace and
reference reads; workspace creation; denied reference overwrite; denied private
read, overwrite and creation; successful workspace write after those denials;
a command with a child and grandchild; another successful read; and shutdown.
Each descendant directly attempts reads and writes in all three fixture roots.
The parent continues writing its private log between requests.

The matching unconfined control uses fresh fixtures and must successfully perform
all operations, including those denied by enforcement. The worker has a finite
native session deadline and commands have bounded waits. A controlled shutdown
response and completed pipes are required. Forced helper termination is a failed
case, not proof of descendant cleanup.

## Evidence and acceptance

`report.json` summarizes both cases. Each case retains its policy, fixture/source
digests, requests, correlated transcript, raw stdout/stderr, controller log and
independent file observations. Native Windows acceptance additionally requires
the PSEC `base-container` exit event with the worker PID and zero exit. macOS
acceptance requires the generated Seatbelt profile, application-path log, real
worker completion and zero exit; a log or dry-run alone is insufficient.

A pass requires every expected operation to run, correct allowed-read bytes,
actual `PermissionError` denials where required, independent expected file bytes,
no private file creation, one worker PID throughout, distinct child/grandchild
PIDs and normal process completion. Startup failures, malformed requests, absent
operations and unchanged files without reached denials cannot qualify.

Exit codes: `0` means both controlled cases qualified; `1` means the completed
experiment failed; `2` means setup/controller execution raised an error. Retain
failed outputs and inspect `report.json` when present before another attempt.

To verify clone-only packaging:

```text
python investigate.py build --output lab.zip
```

Extract to a fresh directory and run the same `worker-experiment` command there.
On macOS use `/usr/bin/unzip` or an extractor preserving executable permissions.
Optional `--executor native/windows-x64/wxc-exec.exe` selects another
manifest-verified helper; architecture/emulation must be reported accurately.

## What this does not establish

This is a deterministic mechanism experiment, not a production Bridge worker or
a real Copilot turn. Its controlled payloads and correlation tokens are not an
authentication boundary against hostile tool code. Arbitrary commands must not
be sent to this lab worker. No claim is made for aliases, hardlinks, inherited
file handles, registry operations, all metadata/device access, hostile IPC,
multiple actors or detached-process cleanup. Seatbelt's baseline device and
metadata permissions still apply; see [executor limits](executors.md#capability-and-platform-limits).

The result answers whether a useful persistent tool process can communicate with
trusted control while holding narrower ordinary-file permissions. A subsequent
Bridge/Copilot integration must preserve that authority separation and its own
tool ownership, identity and lifecycle contracts.
