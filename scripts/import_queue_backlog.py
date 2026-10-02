#!/usr/bin/env python3
"""Plan or apply reviewed legacy backlog dispositions without contacting the old broker.

Input is JSON Lines; see docs/operations/queue-migration.md. Dry-run is the default.
The source export must be retained independently, including any original transport metadata.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs" / "sdk" / "src"))

from genjishimada_sdk.queue import EVENT_PAYLOAD_TYPES
from genjishimada_sdk.queue_store import enqueue_job


@dataclass(frozen=True)
class ImportPlan:
    """An explicit disposition for one source export record."""

    source_id: str
    event_name: str
    payload: Any
    record: dict[str, Any]
    disposition: str
    reason: str
    event_key: str
    job_id: UUID | None = None


def canonical(value: object) -> str:
    """Return deterministic JSON for source identity comparisons."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_record(record: dict[str, Any], fallback_id: str) -> ImportPlan:
    """Validate a reviewed disposition; ambiguous records are always preserved."""
    source_id = str(record.get("source_id") or fallback_id)
    event_name = str(record.get("queue", "")).removesuffix(".dlq")
    payload = record.get("payload")
    event_key = str(record.get("event_key") or f"legacy:{source_id}")
    requested = record.get("disposition", "needs_reconciliation")
    evidence = record.get("evidence")
    disposition = "needs_reconciliation"
    reason = "No reviewed disposition with supporting evidence."
    job_id = None
    if isinstance(evidence, str) and evidence.strip():
        if requested in {"completed", "discarded"}:
            disposition, reason = requested, evidence
        elif requested == "enqueue":
            try:
                if event_name not in EVENT_PAYLOAD_TYPES:
                    raise ValueError("Unsupported or retired event name; explicit reconciliation required.")
                payload = msgspec.convert(payload, type=EVENT_PAYLOAD_TYPES[event_name], strict=True)
                if record.get("job_id"):
                    job_id = UUID(str(record["job_id"]))
                if (
                    record.get("effects_started") is not False
                    or record.get("legacy_claim")
                    or record.get("completed_effects")
                ):
                    reason = "Prior execution is possible; preserve completed effects before resuming work."
                else:
                    disposition, reason = "enqueued", evidence
            except (ValueError, TypeError, msgspec.ValidationError) as exc:
                reason = (
                    f"Payload/identity validation failed ({type(exc).__name__}); review the retained source record."
                )
    return ImportPlan(source_id, event_name, payload, record, disposition, reason, event_key, job_id)


def load_manifest(path: Path) -> list[ImportPlan]:
    """Preserve every nonempty source line, including malformed JSON."""
    source = path.read_bytes()
    export_id = hashlib.sha256(source).hexdigest()
    result = []
    seen: dict[str, str] = {}
    for number, line in enumerate(source.decode("utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        fallback_id = f"{export_id}:{number}"
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                record = {"malformed_source": record}
        except json.JSONDecodeError:
            record = {"malformed_source": line}
        plan = plan_record(record, fallback_id)
        fingerprint = canonical(record)
        if plan.source_id in seen and seen[plan.source_id] != fingerprint:
            raise ValueError(f"Source ID {plan.source_id!r} occurs with conflicting content; nothing was imported.")
        seen[plan.source_id] = fingerprint
        result.append(plan)
    return result


async def apply_manifest(connection: asyncpg.Connection, plans: list[ImportPlan]) -> Counter:
    """Atomically persist dispositions and enqueue only reviewed work; reruns are safe."""
    counts = Counter()
    async with connection.transaction():
        for plan in sorted(plans, key=lambda item: item.source_id):
            # Serialize reruns of the same export, including source IDs absent from the table.
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", plan.source_id)
            old = await connection.fetchrow(
                "SELECT payload, disposition FROM public.job_imports WHERE source_id=$1", plan.source_id
            )
            if old is not None:
                original = json.loads(old["payload"]) if isinstance(old["payload"], str) else old["payload"]
                if canonical(original) != canonical(plan.record):
                    raise ValueError(
                        f"Source ID {plan.source_id!r} already has a different recorded disposition/content."
                    )
                counts["already_recorded"] += 1
                continue
            job_id = plan.job_id
            disposition, reason = plan.disposition, plan.reason
            legacy = (
                await connection.fetchrow("SELECT * FROM public.jobs WHERE id=$1 FOR UPDATE", job_id)
                if job_id
                else None
            )
            if (
                disposition == "enqueued"
                and legacy is not None
                and legacy["event_key"] is None
                and legacy["queue_job_id"] is None
                and legacy["action"] == plan.event_name
                and legacy["status"] != "succeeded"
                and (
                    legacy["status"] != "queued"
                    or legacy["attempts"] > 0
                    or legacy["started_at"] is not None
                    or legacy["finished_at"] is not None
                )
            ):
                disposition = "needs_reconciliation"
                reason = "Stored job history indicates prior execution; the manifest cannot authorize replay."
            if disposition == "enqueued":
                response = await enqueue_job(
                    connection,
                    event_name=plan.event_name,
                    payload=plan.payload,
                    event_key=plan.event_key,
                    entity_key=plan.record.get("entity_key"),
                    job_id=job_id,
                )
                job_id = response.id
            elif legacy is None:
                # Keep unmatched original IDs in the retained source, without creating runnable work.
                job_id = None
            await connection.execute(
                """INSERT INTO public.job_imports(source_id,job_id,disposition,reason,payload)
                   VALUES ($1,$2,$3,$4,$5::jsonb)""",
                plan.source_id,
                job_id,
                disposition,
                reason,
                canonical(plan.record),
            )
            counts[disposition] += 1
    return counts


async def main() -> None:
    """Report plans by default; write only when explicitly invoked with --apply."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Persist reviewed dispositions and enqueue approved records."
    )
    parser.add_argument(
        "--dsn-env", default="QUEUE_IMPORT_DATABASE_URL", help="Environment variable containing migration-owner DSN."
    )
    args = parser.parse_args()
    plans = load_manifest(args.manifest)
    if not args.apply:
        counts = Counter(plan.disposition for plan in plans)
        print(canonical({"mode": "dry-run", "source_records": len(plans), "dispositions": dict(counts)}))
        return
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        parser.error(f"Set {args.dsn_env} to the target migration-owner connection URL before --apply.")
    connection = await asyncpg.connect(dsn)
    try:
        counts = await apply_manifest(connection, plans)
    finally:
        await connection.close()
    print(canonical({"mode": "applied", "source_records": len(plans), "dispositions": dict(counts)}))


if __name__ == "__main__":
    asyncio.run(main())
