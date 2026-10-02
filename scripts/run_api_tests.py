#!/usr/bin/env python3
"""Run the full API suite with bounded workers and reproducible collection order.

Also loaded as a pytest plugin via ``-p scripts.run_api_tests`` so every xdist
worker applies the same ordering. Test paths and pytest output paths are relative
to apps/api, regardless of the invoking shell's working directory.
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
DEFAULT_SEED = 20260928
ORDERS = ("collected", "reverse", "shuffle")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Make ordering options available to the controller and each xdist worker."""
    group = parser.getgroup("api-order", "API suite ordering")
    group.addoption("--api-order", choices=ORDERS, default="collected", help="API test collection order")
    group.addoption("--api-seed", type=int, default=DEFAULT_SEED, help="Seed used by --api-order=shuffle")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Reorder collected cases without removing or changing any case."""
    order = config.getoption("--api-order")
    if order == "reverse":
        items.reverse()
    elif order == "shuffle":
        random.Random(config.getoption("--api-seed")).shuffle(items)


def pytest_report_header(config: pytest.Config) -> str:
    """Include the reproducibility settings in pytest's session output."""
    return f"API order: {config.getoption('--api-order')}; seed: {config.getoption('--api-seed')}"


def _worker_count(value: str) -> int:
    workers = int(value)
    if workers < 0:
        raise argparse.ArgumentTypeError("workers must be nonnegative (0 runs serially)")
    return workers


def main(argv: list[str] | None = None) -> int:
    """Invoke pytest using this interpreter, the API config, and its working directory."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Additional arguments go to pytest, e.g. -m unit, tests/maps, --testmon, or --junitxml=/tmp/api.xml.",
        allow_abbrev=False,
    )
    parser.add_argument("--workers", type=_worker_count, default=2, help="Worker count; 0 for serial (default: 2)")
    parser.add_argument("--order", choices=ORDERS, default="collected", help="Collection order (default: collected)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Shuffle seed (default: {DEFAULT_SEED})")
    options, pytest_args = parser.parse_known_args(argv)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]

    environment = os.environ.copy()
    pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), *([pythonpath] if pythonpath else [])])
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(API_ROOT / "pyproject.toml"),
        "-p",
        "scripts.run_api_tests",
        "-n",
        str(options.workers),
        "--dist=worksteal",
        "--durations=20",
        # Queue acceptance owns a serial runner and an independent fixture boundary.
        "--ignore=tests/integration/queue",
        f"--api-order={options.order}",
        f"--api-seed={options.seed}",
        *pytest_args,
    ]
    try:
        return subprocess.run(command, cwd=API_ROOT, env=environment, check=False).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
