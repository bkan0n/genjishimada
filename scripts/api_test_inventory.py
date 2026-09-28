#!/usr/bin/env python3
"""Verify that API test moves preserve every collected case and parameter ID.

Capture collection with ``uv run --project apps/api pytest apps/api/tests
--collect-only -q -o addopts=''`` and pass the resulting file to this script.
The committed manifest records the original case IDs and their new file paths.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "docs/testing/api-test-migration.json"


def collected_cases(path: Path) -> list[str]:
    """Read quiet pytest collection output, ignoring its summary and warnings."""
    cases = []
    for line in path.read_text().splitlines():
        node_id = line.strip()
        if "::" not in node_id or not node_id.split("::", 1)[0].endswith(".py"):
            continue
        if node_id.startswith("apps/api/"):
            node_id = node_id.removeprefix("apps/api/")
        if node_id.startswith("tests/"):
            cases.append(node_id)
    if not cases:
        raise ValueError(f"No pytest case IDs found in {path}")
    return cases


def skip_markers(path: Path) -> list[str]:
    """Keep existing skip/xfail expressions visible alongside collection parity."""
    tree = ast.parse(path.read_text())
    markers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "xfail"}:
            if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
                markers.append(ast.unparse(node))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "mark"
                and node.func.attr in {"skip", "skipif", "xfail"}
            ):
                markers.append(ast.unparse(node))
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "pytest"
                and node.func.attr in {"skip", "xfail"}
            ):
                markers.append(ast.unparse(node))
    return sorted(markers)


def main() -> int:
    """Compare a collected suite against the original case and skip inventory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="Output of a full pytest --collect-only -q run")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    expected = Counter(f"{entry['destination']}::{case}" for entry in manifest["files"] for case in entry["cases"])
    actual = Counter(collected_cases(args.collection))
    missing = expected - actual
    added = actual - expected
    problems = []
    for entry in manifest["files"]:
        path = ROOT / "apps/api" / entry["destination"]
        if not path.is_file():
            problems.append(f"Missing file: {entry['destination']}")
        elif skip_markers(path) != entry["skip_markers"]:
            problems.append(f"Changed skip/xfail expressions: {entry['destination']}")
    for label, differences in (("Missing cases", missing), ("Unexpected cases", added)):
        if differences:
            problems.append(f"{label}:\n" + "\n".join(f"  {case} (x{count})" for case, count in differences.items()))
    if problems:
        print("\n".join(problems))
        return 1
    bot = sum(count for case, count in actual.items() if case.startswith("tests/bot/"))
    print(f"Inventory preserved: {sum(actual.values())} cases ({bot} bot; {sum(actual.values()) - bot} API).")
    print(f"All {len(manifest['files'])} test files retain their original case and skip/xfail inventory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
