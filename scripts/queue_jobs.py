#!/usr/bin/env python3
"""Inspect and recover background jobs through the authenticated operator API.

Set QUEUE_API_URL (origin, e.g. http://localhost:8000), API_KEY, and QUEUE_OPERATOR_ID.
The API key needs jobs:manage; the API enforces its QUEUE_OPERATOR_IDS allowlist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4

import httpx


@dataclass(frozen=True)
class Operation:
    """An API operation that retains its audit identity across response loss."""

    method: str
    path: str
    params: dict[str, str | int] | None = None
    body: dict[str, object] | None = None
    request_id: str | None = None


def nonnegative(value: str) -> int:
    """Parse a saved failure generation."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("Generation must be nonnegative.")
    return parsed


def parser() -> argparse.ArgumentParser:
    """Define explicit inspection and recovery commands."""
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("stats", help="Show queue counts, oldest ready age, and uncertain effects.")
    listing = commands.add_parser("list", help="List actionable jobs, or filter by status.")
    listing.add_argument("--status", choices=["queued", "processing", "failed", "succeeded", "timeout"])
    listing.add_argument("--limit", type=int, choices=range(1, 101), metavar="1..100", default=50)
    inspect = commands.add_parser("inspect", help="Inspect current job state, effects, and recovery history.")
    inspect.add_argument("job_id", type=UUID)
    retry = commands.add_parser("retry", help="Retry the diagnosed failure generation of the same job.")
    reconcile = commands.add_parser("reconcile", help="Record evidence for an uncertain external effect.")
    reconcile.add_argument("job_id", type=UUID)
    reconcile.add_argument("effect_key")
    resolution = reconcile.add_mutually_exclusive_group(required=True)
    resolution.add_argument("--result-file", type=Path, help="JSON object describing an already-completed result.")
    resolution.add_argument("--resend", action="store_true", help="Explicitly permit repeating the uncertain effect.")
    reconcile.add_argument("--reason", required=True)
    discard = commands.add_parser("discard", help="Discard a held job with an audited reason.")
    discard.add_argument("--reason", required=True)
    for command in [retry, reconcile, discard]:
        command.add_argument(
            "--generation", type=nonnegative, required=True, help="retry_generation from inspect/list."
        )
        if command is not reconcile:
            command.add_argument("job_id", type=UUID)
        command.add_argument("--request-id", help="Reuse the printed request ID if the previous response was lost.")
    return root


def operation(args: argparse.Namespace, operator_id: int) -> Operation:
    """Build the same requests used by recovery controls, without database access."""
    prefix = "/api/v3/internal/jobs"
    if args.command == "stats":
        return Operation("GET", f"{prefix}/stats", params={"operator_id": operator_id})
    if args.command == "list":
        params: dict[str, str | int] = {"operator_id": operator_id, "limit": args.limit}
        if args.status is not None:
            params["status"] = args.status
        return Operation("GET", prefix, params=params)
    path = f"{prefix}/{args.job_id}"
    if args.command == "inspect":
        return Operation("GET", f"{path}/operations", params={"operator_id": operator_id})
    request_id = args.request_id or f"queue-cli:{uuid4()}"
    if not request_id.strip():
        raise ValueError("Request ID must not be empty.")
    body: dict[str, object] = {
        "operator_id": operator_id,
        "request_id": request_id,
        "expected_generation": args.generation,
    }
    if args.command == "retry":
        return Operation("POST", f"{path}/retry", body=body, request_id=request_id)
    if not args.reason.strip():
        raise ValueError("Recovery reason must not be empty.")
    body["reason"] = args.reason
    if args.command == "discard":
        return Operation("POST", f"{path}/discard", body=body, request_id=request_id)
    result = json.loads(args.result_file.read_text()) if args.result_file else None
    if args.result_file is not None and not isinstance(result, dict):
        raise ValueError("The result file must contain a JSON object.")
    body.update(result=result, resend=args.resend)
    if not args.effect_key.strip():
        raise ValueError("Effect key must not be empty.")
    return Operation(
        "POST",
        f"{path}/effects/{quote(args.effect_key, safe='')}/reconcile",
        body=body,
        request_id=request_id,
    )


def configuration() -> tuple[str, str, int]:
    """Read credentials from the environment, never command-line arguments."""
    url = os.environ.get("QUEUE_API_URL", "").rstrip("/")
    key = os.environ.get("API_KEY", "")
    raw_operator = os.environ.get("QUEUE_OPERATOR_ID", "")
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("QUEUE_API_URL must be an HTTP(S) API origin without embedded credentials.")
    if parts.path or parts.query or parts.fragment:
        raise ValueError("QUEUE_API_URL must be the API origin, without a path, query, or fragment.")
    if not key:
        raise ValueError("Set API_KEY to an authenticated API key with jobs:manage.")
    if not raw_operator.isdigit() or int(raw_operator) <= 0:
        raise ValueError("Set QUEUE_OPERATOR_ID to your allowlisted Discord user ID.")
    return url, key, int(raw_operator)


def execute(client: httpx.Client, request: Operation) -> int:
    """Execute once; print the audit key before a potentially ambiguous mutation."""
    if request.request_id:
        print(f"Request ID: {request.request_id}", file=sys.stderr, flush=True)
    try:
        response = client.request(request.method, request.path, params=request.params, json=request.body)
    except httpx.HTTPError:
        print(
            "API response unavailable. Inspect the job before repeating a mutation; reuse its request ID.",
            file=sys.stderr,
        )
        return 1
    try:
        result = response.json()
    except ValueError:
        print(f"API returned HTTP {response.status_code} without a JSON response.", file=sys.stderr)
        return 1
    success = response.is_success
    print(json.dumps(result, indent=2, ensure_ascii=False), file=sys.stdout if success else sys.stderr)
    return 0 if success else 1


def main() -> int:
    """Run one operator action; the server remains authoritative for authorization."""
    cli = parser()
    args = cli.parse_args()
    try:
        url, key, operator_id = configuration()
        request = operation(args, operator_id)
    except (ValueError, OSError) as exc:
        cli.error(str(exc))
    with httpx.Client(base_url=url, headers={"X-API-KEY": key}, timeout=30, follow_redirects=False) as client:
        return execute(client, request)


if __name__ == "__main__":
    raise SystemExit(main())
