"""Transactional PostgreSQL job identities and recovery operations.

Import this server-side module only where asyncpg and PGQueuer are installed.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import msgspec
from pgqueuer.queries import Queries

from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.queue import (
    ALL_ENTRYPOINTS,
    DependencyFailed,
    DependencyUnavailable,
    JobContext,
    JobEnvelope,
    LostOwnershipError,
)

MAX_REQUEST_ID_LENGTH = 200
MAX_EFFECT_KEY_LENGTH = 240


def encode_payload(payload: object) -> bytes:
    """Canonical representation makes event fingerprints independent of dict order."""
    return json.dumps(msgspec.to_builtins(payload), sort_keys=True, separators=(",", ":")).encode()


async def enqueue_job(  # noqa: PLR0912, PLR0913 - ordered producer, adoption, and enqueue protocol
    conn: asyncpg.Connection,
    *,
    event_name: str,
    payload: object,
    event_key: str,
    entity_key: str | None = None,
    depends_on: UUID | None = None,
    job_id: UUID | None = None,
) -> JobStatusResponse:
    """Commit identity and queue insertion on the business transaction's connection."""
    if not conn.is_in_transaction():
        raise ValueError("enqueue_job requires an active transaction")
    if event_name not in ALL_ENTRYPOINTS:
        raise ValueError(f"Unknown queue entrypoint: {event_name}")
    if not event_key:
        raise ValueError("event_key is required")
    encoded = encode_payload(payload)
    fingerprint = hashlib.sha256(encoded).hexdigest()
    if entity_key is not None:
        # Mark this producer before allocating an order. Shared locks let one
        # transaction enqueue several entities without opposing lock orders;
        # readiness below defers until every producer for its entity commits.
        await conn.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended($1,0))", "queue-entity:" + entity_key)
    identity = job_id or uuid4()
    legacy = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1 FOR UPDATE", identity) if job_id else None
    if legacy is not None:
        if legacy["action"] != event_name:
            raise ValueError("Legacy job action does not match the reviewed event")
        if legacy["event_key"] is not None or legacy["queue_job_id"] is not None:
            if legacy["event_key"] != event_key or legacy["payload_hash"] != fingerprint:
                raise ValueError("Legacy job identity has a conflicting payload or event")
            return await get_job(conn, identity)
        if legacy["status"] == "succeeded":
            raise ValueError("A completed legacy job cannot be replayed")
        # Legacy rows received a sequence at migration, before they entered this
        # queue. First adoption joins today's acceptance order; replay above
        # preserves the already accepted sequence and public identity.
        await conn.execute(
            """UPDATE public.jobs SET event_key=$2,payload_hash=$3,payload=$4,
            entity_key=$5,depends_on=$6,event_sequence=DEFAULT,
            status='queued',error_code=NULL,error_msg=NULL,finished_at=NULL
            WHERE id=$1""",
            identity,
            event_key,
            fingerprint,
            encoded,
            entity_key,
            depends_on,
        )
        inserted = identity
    else:
        inserted = await conn.fetchval(
            """INSERT INTO public.jobs(id,action,event_key,payload_hash,payload,entity_key,depends_on)
               VALUES($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT(action,event_key) WHERE event_key IS NOT NULL DO NOTHING RETURNING id""",
            identity,
            event_name,
            event_key,
            fingerprint,
            encoded,
            entity_key,
            depends_on,
        )
    if inserted is None:
        row = await conn.fetchrow(
            "SELECT * FROM public.jobs WHERE action=$1 AND event_key=$2 FOR UPDATE", event_name, event_key
        )
        if row is None:
            raise RuntimeError("Conflicting job identity disappeared")
        if row["payload_hash"] != fingerprint:
            raise ValueError("event identity reused with a different payload")
        return await get_job(conn, row["id"])
    envelope = JobEnvelope(identity, event_name, event_key, encoded, entity_key=entity_key)
    queued = await Queries.from_asyncpg_connection(conn).enqueue(
        event_name,
        msgspec.json.encode(envelope),
        dedupe_key=str(identity),
    )
    await conn.execute("UPDATE public.jobs SET queue_job_id=$2 WHERE id=$1", identity, queued[0])
    return JobStatusResponse(identity, "queued")


async def get_job(conn: asyncpg.Connection, job_id: UUID) -> JobStatusResponse:
    """Read the durable summary, projected atomically by queue state triggers."""
    row = await conn.fetchrow("SELECT id,status::text,error_code,error_msg FROM public.jobs WHERE id=$1", job_id)
    if row is None:
        raise LookupError("Job not found")
    return JobStatusResponse(**dict(row))


def json_value(value: object) -> Any:  # noqa: ANN401 - arbitrary serialized effect responses
    """Handle both default asyncpg JSON text and application-installed codecs."""
    return json.loads(value) if isinstance(value, str) else value


def operator_ids() -> set[int]:
    """Default recovery access to the existing alert recipient."""
    return {
        int(item.strip()) for item in os.getenv("QUEUE_OPERATOR_IDS", "141372217677053952").split(",") if item.strip()
    }


async def lock_claim(conn: asyncpg.Connection, context: JobContext) -> asyncpg.Record:
    """Fence new effects against the current execution, locking queue before identity."""
    row = await conn.fetchrow(
        """SELECT j.* FROM public.jobs j JOIN public.pgqueuer q ON q.id=j.queue_job_id
           WHERE j.id=$1 AND q.queue_manager_id=$2 AND q.updated=$3 AND q.status='picked'
           FOR UPDATE OF q""",
        context.job_id,
        context.manager_id,
        context.claimed_at,
    )
    if row is None:
        raise LostOwnershipError("Queue execution no longer owns its claim")
    return row


async def ensure_ready(conn: asyncpg.Connection, context: JobContext) -> None:
    """Check durable parent and entity order without holding a connection while waiting."""
    async with conn.transaction():
        row = await lock_claim(conn, context)
        if row["depends_on"] is not None:
            parent = await get_job(conn, row["depends_on"])
            if parent.status in {"failed", "timeout"}:
                raise DependencyFailed("Prerequisite needs recovery")
            if parent.status != "succeeded":
                raise DependencyUnavailable("Prerequisite has not completed")
        if row["entity_key"] is not None:
            # Never wait for a producer while holding the execution's queue row:
            # that producer may need the same row for a mutation receipt. The
            # next statement gets a fresh snapshot of the committed predecessors.
            if not await conn.fetchval(
                "SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))", "queue-entity:" + row["entity_key"]
            ):
                raise DependencyUnavailable("An entity producer has not committed")
            blocked = await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM public.jobs WHERE entity_key=$1 AND event_sequence<$2
                   AND status NOT IN ('succeeded') AND error_code IS DISTINCT FROM 'discarded')""",
                row["entity_key"],
                row["event_sequence"],
            )
            if blocked:
                raise DependencyUnavailable("An earlier operation for this entity has not completed")


async def retry_job(  # noqa: PLR0913, PLR0912 - one ordered authorization and state transition
    conn: asyncpg.Connection,
    job_id: UUID,
    *,
    operator_id: int,
    expected_generation: int,
    request_id: str,
    operator_ids: set[int] | None = None,
    binding: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Requeue one held execution, retaining effects and recording a single operator action."""
    allowed = operator_ids if operator_ids is not None else globals()["operator_ids"]()
    if operator_id not in allowed:
        raise PermissionError("Operator is not permitted to recover jobs")
    if not request_id or len(request_id) > MAX_REQUEST_ID_LENGTH:
        raise ValueError("Invalid recovery request ID")
    async with conn.transaction():
        # Serialize duplicate request keys even when their job IDs differ.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "queue-operation:" + request_id)
        previous = await conn.fetchrow("SELECT * FROM public.job_operations WHERE request_id=$1", request_id)
        if previous is not None:
            if (
                previous["job_id"] != job_id
                or previous["operator_id"] != operator_id
                or previous["generation"] != expected_generation
                or previous["action"] != "retry"
            ):
                raise ValueError("Recovery request ID reused for a different operation")
            return json_value(previous["result"])
        row = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1", job_id)
        if row is None:
            raise LookupError("Job not found")
        queue = await conn.fetchrow("SELECT * FROM public.pgqueuer WHERE id=$1 FOR UPDATE", row["queue_job_id"])
        row = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1 FOR UPDATE", job_id)
        if row is None:
            raise LookupError("Job not found")
        if binding is not None:
            alert = await conn.fetchrow("SELECT * FROM public.job_alerts WHERE job_id=$1", job_id)
            if alert is None or any(
                alert[name] != binding.get(name) for name in ("guild_id", "channel_id", "message_id")
            ):
                raise PermissionError("Recovery control does not match its stored alert")
        outcome = "queued"
        if row["error_code"] == "discarded":
            outcome = "discarded"
        elif row["status"] == "succeeded":
            outcome = "succeeded"
        elif queue is not None and queue["status"] in {"queued", "picked"}:
            outcome = "already_queued" if queue["status"] == "queued" else "running"
        elif row["retry_generation"] != expected_generation:
            outcome = "stale"
        elif (
            queue is None
            or queue["status"] != "failed"
            or await conn.fetchval(
                """SELECT EXISTS(SELECT 1 FROM public.job_effects
                    WHERE job_id=$1 AND kind='external' AND state='started')""",
                job_id,
            )
        ):
            outcome = "requires_reconciliation"
        result = {
            "outcome": outcome,
            "job_id": str(job_id),
            "status": str(row["status"]),
            "retry_generation": row["retry_generation"],
        }
        if outcome != "queued":
            return result
        if queue is None:
            raise RuntimeError("Queue row missing for retry")
        await conn.execute(
            """UPDATE public.pgqueuer SET status='queued',execute_after=now(),updated=now(),
            queue_manager_id=NULL,attempts=0,handler_failures=0,failure_code=NULL,failure_message=NULL WHERE id=$1""",
            queue["id"],
        )
        generation = await conn.fetchval(
            "UPDATE public.jobs SET retry_generation=retry_generation+1 WHERE id=$1 RETURNING retry_generation", job_id
        )
        result.update(status="queued", retry_generation=generation)
        await conn.execute(
            """INSERT INTO public.job_operations(request_id,job_id,operator_id,action,generation,result)
            VALUES($1,$2,$3,'retry',$4,$5::jsonb)""",
            request_id,
            job_id,
            operator_id,
            expected_generation,
            json.dumps(result),
        )
        return result


async def _effect_context(conn: asyncpg.Connection, context: JobContext, key: str, administrative: bool) -> None:
    if not key or len(key) > MAX_EFFECT_KEY_LENGTH:
        raise ValueError("Invalid effect key")
    if administrative:
        if not key.startswith("alert:"):
            raise PermissionError("Administrative effects are limited to failure alerts")
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM public.job_alerts WHERE job_id=$1)", context.job_id):
            raise LookupError("No failure alert exists for this job")
        await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"alert:{context.job_id}:{key}")
    else:
        await lock_claim(conn, context)


async def claim_effect(
    conn: asyncpg.Connection, context: JobContext, key: str, *, destination: str, administrative: bool = False
) -> dict[str, Any]:
    """Reserve an external effect; a prior uncompleted reservation is uncertain."""
    async with conn.transaction():
        fingerprint = hashlib.sha256(destination.encode()).hexdigest()
        # Returning immutable evidence is safe after the execution ends. A new
        # effect still requires the current claim below.
        completed = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2 AND state='completed'",
            context.job_id,
            key,
        )
        if completed is not None and not administrative:
            if completed["fingerprint"] != fingerprint or completed["kind"] != "external":
                raise ValueError("Effect identity reused for a different destination")
            return {"state": "completed", "result": json_value(completed["result"])}
        await _effect_context(conn, context, key, administrative)
        row = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2 FOR UPDATE", context.job_id, key
        )
        if row is not None:
            if row["fingerprint"] != fingerprint:
                raise ValueError("Effect identity reused for a different destination")
            if row["state"] == "completed":
                return {"state": "completed", "result": json_value(row["result"])}
            if row["state"] == "started":
                return {"state": "uncertain", "result": None}
            await conn.execute(
                """UPDATE public.job_effects SET state='started',manager_id=$3,claimed_at=$4,updated_at=now()
                   WHERE job_id=$1 AND effect_key=$2""",
                context.job_id,
                key,
                context.manager_id,
                context.claimed_at,
            )
        else:
            await conn.execute(
                """INSERT INTO public.job_effects(
                    job_id,effect_key,kind,state,fingerprint,destination,manager_id,claimed_at)
                VALUES($1,$2,$3,'started',$4,$5,$6,$7)""",
                context.job_id,
                key,
                "alert" if administrative else "external",
                fingerprint,
                destination,
                context.manager_id,
                context.claimed_at,
            )
        return {"state": "claimed", "result": None}


async def complete_effect(
    conn: asyncpg.Connection, context: JobContext, key: str, result: object, *, administrative: bool = False
) -> dict[str, Any]:
    """Persist completion evidence; never overwrite a previous successful result."""
    async with conn.transaction():
        await _effect_context(conn, context, key, administrative)
        row = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2 FOR UPDATE", context.job_id, key
        )
        if row is None:
            raise LookupError("Effect was not reserved")
        if row["state"] == "completed":
            if json_value(row["result"]) != result:
                raise ValueError("Completed effect result cannot be replaced")
        else:
            await conn.execute(
                """UPDATE public.job_effects SET state='completed',result=$3::jsonb,updated_at=now()
                   WHERE job_id=$1 AND effect_key=$2""",
                context.job_id,
                key,
                json.dumps(result),
            )
        return {"state": "completed", "result": result}


async def release_effect(
    conn: asyncpg.Connection, context: JobContext, key: str, *, administrative: bool = False
) -> dict[str, Any]:
    """Release only a reservation owned by the active caller after definite rejection."""
    async with conn.transaction():
        await _effect_context(conn, context, key, administrative)
        await conn.execute(
            """DELETE FROM public.job_effects WHERE job_id=$1 AND effect_key=$2
            AND state='started' AND manager_id IS NOT DISTINCT FROM $3 AND claimed_at IS NOT DISTINCT FROM $4""",
            context.job_id,
            key,
            context.manager_id,
            context.claimed_at,
        )
    return {"released": True}


async def save_snapshot(conn: asyncpg.Connection, context: JobContext, key: str, value: object) -> Any:  # noqa: ANN401 - persisted JSON decision
    """Freeze application decisions before external work so replay takes the same branch."""
    key = "snapshot:" + key
    async with conn.transaction():
        await lock_claim(conn, context)
        row = await conn.fetchrow(
            "SELECT result FROM public.job_effects WHERE job_id=$1 AND effect_key=$2", context.job_id, key
        )
        if row is not None:
            return json_value(row["result"])
        await conn.execute(
            """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint,result)
            VALUES($1,$2,'mutation','completed',$3,$4::jsonb)""",
            context.job_id,
            key,
            hashlib.sha256(key.encode()).hexdigest(),
            json.dumps(value),
        )
        return value


async def inspect_job(conn: asyncpg.Connection, job_id: UUID) -> dict[str, Any]:
    """Return sanitized durable execution/effect state for operator diagnostics."""
    row = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1", job_id)
    if row is None:
        raise LookupError("Job not found")
    alert = await conn.fetchrow("SELECT * FROM public.job_alerts WHERE job_id=$1", job_id)
    effects = await conn.fetch(
        "SELECT effect_key,kind,state,destination,result FROM public.job_effects WHERE job_id=$1 ORDER BY created_at",
        job_id,
    )
    result = {
        "job_id": str(job_id),
        "event_name": row["action"],
        "status": str(row["status"]),
        "retry_generation": row["retry_generation"],
        "error_msg": row["error_msg"],
        "error_code": row["error_code"],
        "handler_failures": row["handler_failures"],
        "attempts": row["attempts"],
        "failed_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "effects": [{**dict(e), "result": json_value(e["result"])} for e in effects],
        "guild_id": None,
        "channel_id": None,
        "message_id": None,
        "notified_generation": None,
    }
    if alert:
        result.update({k: alert[k] for k in ("guild_id", "channel_id", "message_id", "notified_generation")})
    return result


async def _recorded_operation(  # noqa: PLR0913 - complete audited request identity
    conn: asyncpg.Connection,
    job_id: UUID,
    *,
    operator_id: int,
    request_id: str,
    action: str,
    expected_generation: int,
    reason: str,
) -> dict[str, Any] | None:
    if not request_id or len(request_id) > MAX_REQUEST_ID_LENGTH:
        raise ValueError("Invalid recovery request ID")
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", "queue-operation:" + request_id)
    previous = await conn.fetchrow("SELECT * FROM public.job_operations WHERE request_id=$1", request_id)
    if previous is None:
        return None
    if (
        previous["job_id"] != job_id
        or previous["operator_id"] != operator_id
        or previous["action"] != action
        or previous["generation"] != expected_generation
        or previous["reason"] != reason
    ):
        raise ValueError("Recovery request ID reused for a different operation")
    return json_value(previous["result"])


async def _held_generation(conn: asyncpg.Connection, job_id: UUID, expected_generation: int) -> asyncpg.Record:
    row = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1", job_id)
    if row is None:
        raise LookupError("Job not found")
    # Match retry/worker lock order: queue row before public identity.
    queue = await conn.fetchrow("SELECT status FROM public.pgqueuer WHERE id=$1 FOR UPDATE", row["queue_job_id"])
    row = await conn.fetchrow("SELECT * FROM public.jobs WHERE id=$1 FOR UPDATE", job_id)
    if row is None:
        raise LookupError("Job not found")
    if row["retry_generation"] != expected_generation:
        raise ValueError("Failure generation changed; inspect the current job before acting")
    if queue is None or queue["status"] != "failed":
        raise ValueError("Only held jobs can be reconciled or discarded")
    return row


async def reconcile_effect(  # noqa: PLR0913 - audited reconciliation inputs
    conn: asyncpg.Connection,
    job_id: UUID,
    key: str,
    *,
    operator_id: int,
    expected_generation: int,
    request_id: str,
    reason: str,
    result: object = None,
    resend: bool = False,
) -> dict[str, Any]:
    """Record an explicit operator decision for an uncertain external outcome."""
    if operator_id not in operator_ids():
        raise PermissionError("Operator is not permitted to recover jobs")
    if not reason.strip() or (result is None and not resend) or (resend and result is not None):
        raise ValueError("Provide a reason and either completion evidence or an explicit resend decision")
    response = {"state": "resend" if resend else "completed", "effect_key": key, "result": result}
    async with conn.transaction():
        previous = await _recorded_operation(
            conn,
            job_id,
            operator_id=operator_id,
            request_id=request_id,
            action="reconcile",
            expected_generation=expected_generation,
            reason=reason,
        )
        if previous is not None:
            if previous != response:
                raise ValueError("Recovery request ID reused for a different reconciliation")
            return previous
        row = await _held_generation(conn, job_id, expected_generation)
        effect = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2 FOR UPDATE", job_id, key
        )
        if effect is None or effect["state"] != "started":
            raise ValueError("Effect is not uncertain")
        await conn.execute(
            """UPDATE public.job_effects SET state=$3,result=$4::jsonb,updated_at=now()
            WHERE job_id=$1 AND effect_key=$2""",
            job_id,
            key,
            response["state"],
            json.dumps(result),
        )
        await conn.execute(
            """INSERT INTO public.job_operations(request_id,job_id,operator_id,action,generation,reason,result)
            VALUES($1,$2,$3,'reconcile',$4,$5,$6::jsonb)""",
            request_id,
            job_id,
            operator_id,
            row["retry_generation"],
            reason,
            json.dumps(response),
        )
        return response


async def discard_job(  # noqa: PLR0913 - audited discard identity
    conn: asyncpg.Connection, job_id: UUID, *, operator_id: int, expected_generation: int, request_id: str, reason: str
) -> dict[str, Any]:
    """Discard only held work, with an explicit audit reason and retained identity."""
    if operator_id not in operator_ids():
        raise PermissionError("Operator is not permitted to recover jobs")
    if not reason.strip():
        raise ValueError("Discard requires a reason")
    async with conn.transaction():
        previous = await _recorded_operation(
            conn,
            job_id,
            operator_id=operator_id,
            request_id=request_id,
            action="discard",
            expected_generation=expected_generation,
            reason=reason,
        )
        if previous is not None:
            return previous
        row = await _held_generation(conn, job_id, expected_generation)
        await conn.execute("DELETE FROM public.pgqueuer WHERE id=$1", row["queue_job_id"])
        await conn.execute(
            "UPDATE public.jobs SET status='failed',error_code='discarded',error_msg=$2,finished_at=now() WHERE id=$1",
            job_id,
            reason[:1500],
        )
        result = {"outcome": "discarded", "job_id": str(job_id)}
        await conn.execute(
            """INSERT INTO public.job_operations(request_id,job_id,operator_id,action,generation,reason,result)
            VALUES($1,$2,$3,'discard',$4,$5,$6::jsonb)""",
            request_id,
            job_id,
            operator_id,
            row["retry_generation"],
            reason,
            json.dumps(result),
        )
        return result


async def apply_mutation(
    conn: asyncpg.Connection, context: JobContext, key: str, fingerprint: str, operation: Callable[[], Awaitable[Any]]
) -> Any:  # noqa: ANN401 - persisted JSON response
    """Commit a domain mutation, downstream jobs, and its replay response atomically."""
    async with conn.transaction():
        # Read completed results even after the original execution claim expires.
        row = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2", context.job_id, key
        )
        if row is not None and row["state"] == "completed":
            if row["fingerprint"] != fingerprint or row["kind"] != "mutation":
                raise ValueError("Mutation effect identity reused for a different request")
            return json_value(row["result"])
        await lock_claim(conn, context)
        # Queue lock serializes concurrent requests from the same execution.
        row = await conn.fetchrow(
            "SELECT * FROM public.job_effects WHERE job_id=$1 AND effect_key=$2", context.job_id, key
        )
        if row is not None:
            if row["state"] != "completed" or row["fingerprint"] != fingerprint or row["kind"] != "mutation":
                raise ValueError("Conflicting mutation effect")
            return json_value(row["result"])
        result = await operation()
        await conn.execute(
            """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint,result)
            VALUES($1,$2,'mutation','completed',$3,$4::jsonb)""",
            context.job_id,
            key,
            fingerprint,
            json.dumps(result),
        )
        return result
