"""Readiness must defer without waiting on a producer that needs its claim."""

import asyncio

import asyncpg
import pytest

from genjishimada_sdk.queue import DependencyUnavailable
from genjishimada_sdk.queue_store import apply_mutation, enqueue_job, ensure_ready, lock_claim
from genjishimada_sdk.queue_worker import FencedQueries

from .conftest import eventually
from .test_queue_entity_ordering import claim

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


async def test_Q14_readiness_defers_when_producer_waits_for_its_claim(queue_db, queue_dsn):
    event = "api.newsfeed.create"
    async with queue_db.transaction():
        await enqueue_job(queue_db, event_name=event, payload={}, event_key="current", entity_key="shared")
    worker = await asyncpg.connect(queue_dsn)
    producer = await asyncpg.connect(queue_dsn)
    task = None
    try:
        queries = FencedQueries.from_asyncpg_connection(worker)
        job, context = await claim(queries, event)
        transaction = worker.transaction()
        await transaction.start()
        await lock_claim(worker, context)

        async def produce_and_mutate():
            async with producer.transaction():
                await enqueue_job(producer, event_name=event, payload={}, event_key="later", entity_key="shared")

                async def mutation():
                    await producer.execute("INSERT INTO business_effects(id,value) VALUES('mutation',1)")
                    return {"applied": True}

                return await apply_mutation(producer, context, "mutation", "request", mutation)

        task = asyncio.create_task(produce_and_mutate())

        async def blocked_on_claim():
            return worker.get_server_pid() in await queue_db.fetchval(
                "SELECT pg_blocking_pids($1)", producer.get_server_pid()
            )

        await eventually(blocked_on_claim)
        # A blocking entity lock here would deadlock with the producer's claim
        # lock. Readiness must release its savepoint immediately instead.
        with pytest.raises(DependencyUnavailable, match="producer"):
            await asyncio.wait_for(ensure_ready(worker, context), 3)
        await transaction.rollback()
        assert await asyncio.wait_for(task, 3) == {"applied": True}
        assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='mutation'") == 1
        assert await queue_db.fetchval("SELECT count(*) FROM job_effects WHERE job_id=$1", context.job_id) == 1
        await ensure_ready(worker, context)
        await queries.log_jobs([(job, "successful", None)])
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await producer.close()
        await worker.close()
