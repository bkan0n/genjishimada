"""Audited reconciliation and discard cannot act on a later failure generation."""

from uuid import uuid4
import pytest
from genjishimada_sdk import queue_store
from .test_queue_recovery import make_job

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


@pytest.mark.parametrize("action", ["reconcile", "discard"])
async def test_Q21_recovery_decision_cannot_touch_later_generation(queue_db, monkeypatch, action):
    monkeypatch.setenv("QUEUE_OPERATOR_IDS", "7")
    public, ctx, queries, job = await make_job(queue_db)
    await queue_store.claim_effect(queue_db, ctx, "destination", destination="one")
    await queries.log_jobs([(job, "failed", None)])
    await queue_db.execute("UPDATE jobs SET retry_generation=1 WHERE id=$1", public.id)
    args = dict(operator_id=7, expected_generation=0, request_id=str(uuid4()), reason="Diagnosed older generation")
    with pytest.raises(ValueError, match="generation"):
        if action == "reconcile":
            await queue_store.reconcile_effect(queue_db, public.id, "destination", resend=True, **args)
        else:
            await queue_store.discard_job(queue_db, public.id, **args)
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1
    assert await queue_db.fetchval("SELECT state FROM job_effects") == "started"
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations") == 0


@pytest.mark.parametrize("action", ["reconcile", "discard"])
async def test_Q20_lost_recovery_response_replays_recorded_operation(queue_db, monkeypatch, action):
    monkeypatch.setenv("QUEUE_OPERATOR_IDS", "7")
    public, ctx, queries, job = await make_job(queue_db)
    await queue_store.claim_effect(queue_db, ctx, "destination", destination="one")
    await queries.log_jobs([(job, "failed", None)])
    args = dict(operator_id=7, expected_generation=0, request_id=str(uuid4()), reason="Reviewed completion evidence")

    async def perform():
        if action == "reconcile":
            return await queue_store.reconcile_effect(queue_db, public.id, "destination", result={"id": 1}, **args)
        return await queue_store.discard_job(queue_db, public.id, **args)

    first = await perform()
    second = await perform()
    assert first == second
    assert await queue_db.fetchval("SELECT count(*) FROM job_operations") == 1
    args["reason"] = "Changed operation"
    with pytest.raises(ValueError, match="reused"):
        await perform()
