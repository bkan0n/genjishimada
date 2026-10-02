"""A contended API effect cannot monopolize the queue worker's connection."""

import asyncio
from contextlib import suppress

import asyncpg
import pytest

from genjishimada_sdk.queue_store import apply_mutation, enqueue_job, get_job
from genjishimada_sdk.queue_worker import QueueWorker

from .conftest import eventually

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


@pytest.mark.parametrize("shutdown", [False, True], ids=["unrelated-work-and-recovery", "bounded-shutdown"])
async def test_Q07_contended_api_effect_does_not_stall_worker(queue_db, queue_dsn, shutdown):
    await queue_db.execute("INSERT INTO business_effects VALUES('contended',0)")
    blocker = await asyncpg.connect(queue_dsn)
    api_connection = await asyncpg.connect(queue_dsn)
    blocking_transaction = blocker.transaction()
    await blocking_transaction.start()
    await blocker.execute("SELECT * FROM business_effects WHERE id='contended' FOR UPDATE")
    worker = QueueWorker(
        queue_dsn.replace("postgresql://postgres@", "postgresql://genjishimada_queue_worker@"),
        owner="bot",
        heartbeat_seconds=0.2,
        timeout_seconds=0.4,
        poll_seconds=0.02,
        drain_seconds=0.1,
        command_timeout_seconds=0.1,
        retry_delays=(),
    )
    api_requests = []
    executions = []
    unrelated_executions = []

    async def handle_contended(context):
        executions.append(context)

        async def operation():
            await api_connection.execute("UPDATE business_effects SET value=value+1 WHERE id='contended'")
            return {"applied": True}

        # An HTTP client disconnect does not cancel an already executing API
        # transaction. It holds the queue claim while its domain write waits.
        request = asyncio.create_task(apply_mutation(api_connection, context, "grant", "grant", operation))
        api_requests.append(request)
        await asyncio.shield(request)

    async def handle_unrelated(context):
        unrelated_executions.append(context)

    worker.add_handler("api.newsfeed.create", handle_contended)
    worker.add_handler("api.xp.grant", handle_unrelated)
    async with queue_db.transaction():
        contended = await enqueue_job(queue_db, event_name="api.newsfeed.create", payload={}, event_key="contended")
    task = asyncio.create_task(worker.run())
    try:

        async def heartbeat_blocked():
            return await queue_db.fetchval(
                """SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE wait_event_type='Lock'
                   AND query LIKE 'UPDATE public.pgqueuer SET heartbeat%')"""
            )

        await eventually(heartbeat_blocked)
        if shutdown:
            worker.stop()
            done, _ = await asyncio.wait({task}, timeout=2)
            assert task in done, "Worker shutdown remained blocked on the API transaction"
        else:
            async with queue_db.transaction():
                unrelated = await enqueue_job(queue_db, event_name="api.xp.grant", payload={}, event_key="unrelated")

            async def unrelated_succeeded():
                return (await get_job(queue_db, unrelated.id)).status == "succeeded"

            try:
                await eventually(unrelated_succeeded, timeout=3)
            except TimeoutError:
                pytest.fail("One locked heartbeat prevented unrelated queue work from completing")
            assert unrelated_executions[0].manager_id != executions[0].manager_id
        assert await queue_db.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", contended.id) == 0
        await blocking_transaction.rollback()
        blocking_transaction = None
        await asyncio.gather(*api_requests)
        if not shutdown:

            async def contended_succeeded():
                return (await get_job(queue_db, contended.id)).status == "succeeded"

            await eventually(contended_succeeded)
        assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='contended'") == 1
        assert await queue_db.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", contended.id) == 0
    finally:
        if blocking_transaction is not None:
            await blocking_transaction.rollback()
        worker.stop()
        with suppress(TimeoutError):
            await asyncio.wait_for(task, 8)
        await asyncio.gather(*api_requests, return_exceptions=True)
        await api_connection.close()
        await blocker.close()
