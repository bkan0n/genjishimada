"""Operator recovery and effect receipts are database guarantees, independent of Discord."""

import asyncio
import hashlib
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest
from genjishimada_sdk import queue_store
from genjishimada_sdk.queue import JobContext, LostOwnershipError
from genjishimada_sdk.queue_worker import FencedQueries
from pgqueuer.ports.repository import EntrypointExecutionParameter

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


async def make_job(conn, *, held=False, entity=None, depends_on=None):
    async with conn.transaction():
        public = await queue_store.enqueue_job(
            conn,
            event_name="api.newsfeed.create",
            payload={"id": 1},
            event_key=str(uuid4()),
            entity_key=entity,
            depends_on=depends_on,
        )
    queries = FencedQueries.from_asyncpg_connection(conn)
    jobs = await queries.dequeue(
        1, {"api.newsfeed.create": EntrypointExecutionParameter(1)}, uuid4(), 2, timedelta(seconds=60)
    )
    job = jobs[0]
    context = JobContext(public.id, job.entrypoint, str(public.id), job.id, job.queue_manager_id, job.updated, b"{}")
    if held:
        await queries.log_jobs([(job, "failed", None)])
    return public, context, queries, job


async def test_Q20_concurrent_retries_have_one_winner(queue_db, queue_dsn):
    assert hasattr(queue_store, "retry_job"), "Audited retry service is missing"
    public, _, _, _ = await make_job(queue_db, held=True)

    async def retry():
        conn = await asyncpg.connect(queue_dsn)
        try:
            return await queue_store.retry_job(
                conn, public.id, operator_id=7, operator_ids={7}, expected_generation=0, request_id=str(uuid4())
            )
        finally:
            await conn.close()

    results = await asyncio.gather(retry(), retry())
    assert sorted(r["outcome"] for r in results) == ["already_queued", "queued"]
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", public.id) == 1
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations WHERE action='retry'") == 1


async def test_Q21_operator_permission_is_checked_before_mutation(queue_db):
    public, _, _, _ = await make_job(queue_db, held=True)
    with pytest.raises(PermissionError):
        await queue_store.retry_job(
            queue_db, public.id, operator_id=8, operator_ids={7}, expected_generation=0, request_id="denied"
        )
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", public.id) == 0


async def test_Q22_uncertain_external_effect_blocks_retry(queue_db):
    public, ctx, queries, job = await make_job(queue_db)
    result = await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    assert result["state"] == "claimed"
    again = await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    assert again["state"] == "uncertain"
    await queries.log_jobs([(job, "failed", None)])
    result = await queue_store.retry_job(
        queue_db, public.id, operator_id=7, operator_ids={7}, expected_generation=0, request_id="uncertain"
    )
    assert result["outcome"] == "requires_reconciliation"
    assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", public.id) == 0


async def test_Q10_completed_effect_preserved_on_replay(queue_db):
    public, ctx, _, _ = await make_job(queue_db)
    await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    await queue_store.complete_effect(queue_db, ctx, "send-one", {"id": 123})
    result = await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    assert result == {"state": "completed", "result": {"id": 123}}


async def test_Q09_snapshot_preserves_original_decision(queue_db):
    public, ctx, _, _ = await make_job(queue_db)
    first = await queue_store.save_snapshot(queue_db, ctx, "reward", {"rank": 1})
    second = await queue_store.save_snapshot(queue_db, ctx, "reward", {"rank": 2})
    assert first == second == {"rank": 1}


async def test_Q10_mutation_and_receipt_share_one_transaction(queue_db):
    assert hasattr(queue_store, "apply_mutation"), "Atomic mutation receipt helper is missing"
    public, ctx, _, _ = await make_job(queue_db)

    async def grant():
        await queue_db.execute(
            "INSERT INTO business_effects VALUES ('xp',50) ON CONFLICT(id) DO UPDATE SET value=business_effects.value+50"
        )
        return {"xp": 50}

    first = await queue_store.apply_mutation(queue_db, ctx, "xp-grant", "POST:/xp/user", grant)
    again = await queue_store.apply_mutation(queue_db, ctx, "xp-grant", "POST:/xp/user", grant)
    assert first == again == {"xp": 50}
    assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='xp'") == 50
    with pytest.raises(ValueError):
        await queue_store.apply_mutation(queue_db, ctx, "xp-grant", "POST:/xp/other-user", grant)


async def test_Q01_failed_mutation_has_no_receipt_or_domain_write(queue_db):
    public, ctx, _, _ = await make_job(queue_db)

    async def fail():
        await queue_db.execute("INSERT INTO business_effects VALUES ('xp',50)")
        raise RuntimeError("abort")

    with pytest.raises(RuntimeError):
        await queue_store.apply_mutation(queue_db, ctx, "grant", "POST:/xp/user", fail)
    assert await queue_db.fetchval("SELECT count(*) FROM business_effects") == 0
    assert await queue_db.fetchval("SELECT count(*) FROM job_effects") == 0


async def test_Q10_completed_receipt_is_readable_after_claim_ends(queue_db):
    public, ctx, queries, job = await make_job(queue_db)
    await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    await queue_store.complete_effect(queue_db, ctx, "send-one", {"id": 123})
    await queries.log_jobs([(job, "successful", None)])
    result = await queue_store.claim_effect(queue_db, ctx, "send-one", destination="destination")
    assert result == {"state": "completed", "result": {"id": 123}}
    with pytest.raises(LostOwnershipError):
        await queue_store.claim_effect(queue_db, ctx, "another-send", destination="destination")
