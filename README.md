# Meadow confinement lab

Standalone investigation of OS-enforced workspace write confinement for Meadow
on Windows and macOS. The deployment target is an ordinary, non-elevated Python
installation with no required WSL, container service, or administrator setup.

**Status: bootstrap only.** This repository currently collects environment facts
and defines the investigation. It does not yet build, distribute, or run a sandbox
executor, and no confinement result is claimed.

## Clone and collect host facts

```text
git clone https://github.com/jonathanmiddleton/meadow-confinement-lab.git
cd meadow-confinement-lab
python investigate.py environment --output evidence/host.json
```

Use Python 3.11 or later. On Windows, `py -3` can replace `python`; on macOS,
`python3` can replace it. No pip installation or third-party Python package is
needed. The private repository requires your usual GitHub access for cloning;
the collector itself uses no network.

The report contains OS/Python information, privilege-probe results and selected
tool locations. It does not enumerate environment variables or read credentials.
It may include your username in filesystem paths. Keep evidence local unless you
choose to share it. The output file must be new so an earlier result is preserved.

`confinement_status: not_tested` is intentional. Successful diagnostics do not
establish that a sandbox is available or that its boundary holds.

## Investigation and executors

- [Investigation scope and acceptance evidence](docs/investigation.md)
- [Building and transporting native executors](docs/executors.md)
- [Pinned MXC source](upstream.lock.json)

Microsoft MXC is the first candidate. The pin selects source after removal of its
older Windows fallback paths. The published MXC `v1.0.1` release is not equivalent:
its defaults permit a fallback that modifies host ACLs. Do not replace the pin
with that release or a floating branch.

The expected deployment shape is Python orchestration plus an architecture-matched
native helper built on a development host. Restricted hosts should not need to
compile MXC. Native artifacts, transport, compatibility and confinement still need
validation; cloning this bootstrap does not provision them.

## Development checks

```text
python -m unittest discover -s tests -v
python investigate.py environment
```

These verify diagnostics, not the MXC security boundary. Generated binaries,
checkouts and reports belong in the ignored `artifacts/`, `vendor/`, `runs/` and
`evidence/` directories or an explicitly selected external investigation directory.

This repository is independent of the sibling Runtime, Authoring and MXC
checkouts. Remote collectors do not need those repositories.
