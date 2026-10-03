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
from dataclasses import dataclass, replace
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


def identities(plan: ImportPlan) -> set[tuple[str, ...]]:
    """Match duplicate copies using the same identities as queue insertion."""
    result: set[tuple[str, ...]] = {("event", plan.event_name, plan.event_key)}
    if plan.job_id is not None:
        result.add(("job", str(plan.job_id)))
    try:
        if plan.record.get("job_id"):
            result.add(("job", str(UUID(str(plan.record["job_id"])))))
    except ValueError:
        pass  # Invalid identities remain in the preserved source record.
    return result


def protect_duplicates(plans: list[ImportPlan]) -> list[ImportPlan]:
    """Resolve unambiguous UUIDs and preserve conflicts across connected logical copies."""
    parents = list(range(len(plans)))
    owners: dict[tuple[str, ...], int] = {}

    def group(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, plan in enumerate(plans):
        for identity in identities(plan):
            parents[group(index)] = group(owners.setdefault(identity, index))
    blocked = {group(index) for index, plan in enumerate(plans) if plan.disposition != "enqueued"}
    job_ids: dict[int, set[UUID]] = {}
    events: dict[int, set[tuple[str, str]]] = {}
    for index, plan in enumerate(plans):
        identity = group(index)
        if plan.job_id is not None:
            job_ids.setdefault(identity, set()).add(plan.job_id)
        events.setdefault(identity, set()).add((plan.event_name, plan.event_key))
    blocked.update(identity for identity, values in job_ids.items() if len(values) > 1)
    blocked.update(identity for identity, values in events.items() if len(values) > 1)
    resolved = {identity: next(iter(values)) for identity, values in job_ids.items() if identity not in blocked}
    return [
        replace(
            plan,
            disposition="needs_reconciliation",
            reason="Another copy of this logical job is unresolved or has a conflicting disposition.",
        )
        if plan.disposition == "enqueued" and group(index) in blocked
        else replace(plan, job_id=resolved[group(index)])
        if plan.disposition == "enqueued" and group(index) in resolved
        else plan
        for index, plan in enumerate(plans)
    ]


def protect_legacy_history(plan: ImportPlan, legacy: asyncpg.Record | None) -> ImportPlan:
    """Prefer stored execution evidence over an assertion that legacy work is unstarted."""
    if (
        plan.disposition == "enqueued"
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
        return replace(
            plan,
            disposition="needs_reconciliation",
            reason="Stored job history indicates prior execution; the manifest cannot authorize replay.",
        )
    return plan


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
    if isinstance(requested, str) and isinstance(evidence, str) and evidence.strip():
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
    return protect_duplicates(result)


async def apply_manifest(connection: asyncpg.Connection, plans: list[ImportPlan]) -> Counter:
    """Atomically persist dispositions and enqueue only reviewed work; reruns are safe."""
    counts = Counter()
    async with connection.transaction():
        # Lock all source and logical identities in a stable order before inspecting
        # prior imports, so concurrent manifests cannot bypass each other's evidence.
        locks = {canonical(identity) for plan in plans for identity in identities(plan)}
        locks.update(canonical(("source", plan.source_id)) for plan in plans)
        for identity in sorted(locks):
            await connection.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", identity)
        legacy_jobs: dict[UUID | None, asyncpg.Record | None] = {
            job_id: await connection.fetchrow("SELECT * FROM public.jobs WHERE id=$1 FOR UPDATE", job_id)
            for job_id in sorted({plan.job_id for plan in plans if plan.job_id is not None})
        }
        prior = []
        for row in await connection.fetch("SELECT * FROM public.job_imports WHERE disposition != 'enqueued'"):
            record = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
            prior.append(replace(plan_record(record, row["source_id"]), disposition=row["disposition"]))
        guarded = [protect_legacy_history(plan, legacy_jobs.get(plan.job_id)) for plan in plans]
        plans = protect_duplicates([*guarded, *prior])[: len(plans)]
        for plan in sorted(plans, key=lambda item: item.source_id):
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
            if disposition == "enqueued" and job_id is not None:
                existing_id = await connection.fetchval(
                    "SELECT id FROM public.jobs WHERE action=$1 AND event_key=$2", plan.event_name, plan.event_key
                )
                if existing_id is not None and existing_id != job_id:
                    disposition = "needs_reconciliation"
                    reason = "This event already belongs to a different public job UUID."
            if disposition == "enqueued":
                response = await enqueue_job(
                    connection,
                    event_name=plan.event_name,
                    payload=plan.payload,
                    event_key=plan.event_key,
                    entity_key=plan.record.get("entity_key"),
                    job_id=job_id,
                )
                if job_id is not None and response.id != job_id:
                    raise ValueError("Event identity changed during import; the supplied public job UUID was not used.")
                job_id = response.id
            elif legacy_jobs.get(job_id) is None:
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
