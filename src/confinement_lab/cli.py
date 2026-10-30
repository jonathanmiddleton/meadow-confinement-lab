"""Commands that keep environment discovery separate from confinement evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from confinement_lab.environment import collect_environment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inventory = commands.add_parser("environment", help="Collect host facts; does not test confinement")
    inventory.add_argument("--output", type=Path, help="Write a new JSON report instead of stdout")
    args = parser.parse_args(argv)

    report = {
        "schema_version": 1,
        "kind": "environment_inventory",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "confinement_status": "not_tested",
        "environment": collect_environment(),
    }
    encoded = json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output is None:
        sys.stdout.write(encoded)
        return 0
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as output:
            output.write(encoded)
    except OSError as error:
        parser.exit(2, f"Cannot write report: {error}\n")
    print(f"Environment report: {args.output}")
    print("Confinement was not tested.")
    return 0
