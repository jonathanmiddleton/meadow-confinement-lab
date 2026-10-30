"""Run directly from a clone without installing a package."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from confinement_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
