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
    experiment = commands.add_parser("experiment", help="Run controlled Windows or macOS direct-write witnesses")
    experiment.add_argument("--output-root", type=Path, required=True, help="New directory for disposable fixtures and retained evidence")
    experiment.add_argument("--executor", type=Path, help="Override the bundled, manifest-verified executor")
    bundle = commands.add_parser("build", help="Build a portable ZIP using Python only")
    bundle.add_argument("--output", type=Path, required=True, help="New output ZIP file")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "experiment":
            from confinement_lab.experiment import run_experiment
            report = run_experiment(repo_root, args.output_root, args.executor)
            print(f"Direct-write experiment: {report['status']}")
            print(f"Report: {args.output_root / 'report.json'}")
            for case in report["cases"]:
                print(f"  {case['name']}: {case['evaluation']['status']} (qualifies: {case['qualifies']})")
            print("Full confinement remains unestablished; this is a narrow direct-write witness.")
            return 0 if report["status"] == "pass" else 1
        if args.command == "build":
            from confinement_lab.bundle import build_bundle
            receipt = build_bundle(repo_root, args.output)
            print(json.dumps(receipt, indent=2))
            return 0
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, f"{error}\n")

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
