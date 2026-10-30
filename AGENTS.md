# Working in this repository

This is a standalone feasibility investigation, not Meadow Runtime or a qualified
security component. Read README.md and docs/investigation.md before changing it.

- Preserve Windows and macOS support. Restricted-host execution must need no
  administrator setup, WSL, container service, or compiler. Developer builds may
  use toolchains; distribute their resulting native assets separately.
- Keep Python diagnostics runnable from a clone with Python 3.11+ and the standard
  library. Do not require package installation just to collect environment facts.
- Keep environment discovery, native API availability, successful process startup,
  and observed confinement as separate evidence. A payload that never starts
  cannot prove outside writes are denied.
- Bind each native artifact to upstream.lock.json and actual build checksums.
  Never substitute a floating upstream version or an unconfined fallback.
- Probes must operate on explicitly created disposable fixtures. Outside-workspace
  targets belong inside the investigation's disposable root, never in real user
  files. Preserve failed runs and their receipts.
- Do not collect credentials, full environments, or unrelated files. Inspect
  reports for private paths before sharing them. Keep generated evidence ignored.
- Use meaningful behavioral tests. Bootstrap checks use
  `python -m unittest discover -s tests -v`; report native execution separately.
- Inspect git status before editing and commit/push completed in-scope changes.
  Do not change Runtime, Authoring, or the sibling MXC checkout implicitly.
