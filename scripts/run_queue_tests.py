#!/usr/bin/env python3
"""Run mandatory queue acceptance tests and validate the acceptance report."""

import argparse
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Run all required queue tests, rejecting absent or skipped coverage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="Omit isolated process/container fault injection.")
    args = parser.parse_args()
    artifacts = ROOT / "artifacts" / "queue"
    artifacts.mkdir(parents=True, exist_ok=True)
    report = artifacts / "acceptance.xml"
    report.unlink(missing_ok=True)
    environment = {**os.environ, "QUEUE_ACCEPTANCE": "1", "QUEUE_ARTIFACT_DIR": str(artifacts)}
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--no-testmon",
        "-n",
        "0",
        "-ra",
        "--strict-markers",
        "--confcutdir=tests/integration/queue",
        "-o",
        "asyncio_mode=auto",
        "-o",
        "xfail_strict=true",
        "--junitxml",
        str(report),
        "-m",
        "queue and not queue_fault" if args.fast else "queue",
        "tests/integration/queue",
    ]
    result = subprocess.run(command, cwd=ROOT / "apps" / "api", env=environment, check=False)
    if result.returncode:
        return result.returncode
    if not report.exists():
        print("Queue acceptance did not produce a test report.", file=sys.stderr)
        return 1
    cases = list(ET.parse(report).iter("testcase"))
    if not cases or any(case.find("skipped") is not None for case in cases):
        print("Queue acceptance requires collected tests with no skipped or xfail scenarios.", file=sys.stderr)
        return 1
    if not args.fast:
        observed = set()
        for case in cases:
            observed.update(re.findall(r"Q\d{2}", case.get("name", "") + case.get("classname", "")))
        missing = {f"Q{number:02}" for number in range(1, 29)} - observed
        if missing:
            print(f"Queue acceptance IDs missing from report: {', '.join(sorted(missing))}", file=sys.stderr)
            return 1
    print(f"Queue acceptance passed ({len(cases)} cases). Report: {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
