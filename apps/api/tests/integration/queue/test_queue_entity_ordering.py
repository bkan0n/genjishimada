"""Entity order survives overlapping producer transactions."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import asyncpg
import msgspec
import pytest
from pgqueuer.ports.repository import EntrypointExecutionParameter

from genjishimada_sdk.queue import DependencyUnavailable, JobContext, JobEnvelope
from genjishimada_sdk.queue_store import enqueue_job, ensure_ready
from genjishimada_sdk.queue_worker import FencedQueries

from .conftest import eventually

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
FIRST_EVENT = "api.newsfeed.create"
LATER_EVENT = "api.xp.grant"


async def claim(queries, event):
    jobs = await queries.dequeue(1, {event: EntrypointExecutionParameter(1)}, uuid4(), 2, timedelta(seconds=60))
    assert len(jobs) == 1
    job = jobs[0]
    envelope = msgspec.json.decode(job.payload, type=JobEnvelope)
    return job, JobContext(
        envelope.job_id, event, envelope.event_key, job.id, job.queue_manager_id, job.updated, envelope.payload
    )


async def wait_for_database_wait(observer, connection, task):
    async def waiting_or_finished():
        return task.done() or await observer.fetchval(
            "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=$1", connection.get_server_pid()
        )

    await eventually(waiting_or_finished)


@pytest.mark.parametrize("adopt_legacy", [False, True], ids=["new-job", "legacy-adoption"])
async def test_Q14_later_entity_job_waits_for_earlier_producer_commit(queue_db, queue_dsn, adopt_legacy):
    first_connection = await asyncpg.connect(queue_dsn)
    later_connection = await asyncpg.connect(queue_dsn)
    later_task = None
    try:
        legacy_id = uuid4() if adopt_legacy else None
        if legacy_id is not None:
            await queue_db.execute("INSERT INTO jobs(id,action,status) VALUES($1,$2,'failed')", legacy_id, FIRST_EVENT)
        first_transaction = first_connection.transaction()
        await first_transaction.start()
        first = await enqueue_job(
            first_connection,
            event_name=FIRST_EVENT,
            payload={},
            event_key="first",
            entity_key="shared",
            job_id=legacy_id,
        )

        async def enqueue_later():
            async with later_connection.transaction():
                return await enqueue_job(
                    later_connection, event_name=LATER_EVENT, payload={}, event_key="later", entity_key="shared"
                )

        later_task = asyncio.create_task(enqueue_later())
        later = await asyncio.wait_for(later_task, 3)
        queries = FencedQueries.from_asyncpg_connection(queue_db)
        later_job, later_context = await claim(queries, LATER_EVENT)
        with pytest.raises(DependencyUnavailable, match="producer"):
            await asyncio.wait_for(ensure_ready(queue_db, later_context), 3)

        await first_transaction.commit()
        assert await queue_db.fetchval(
            "SELECT a.event_sequence<b.event_sequence FROM jobs a,jobs b WHERE a.id=$1 AND b.id=$2", first.id, later.id
        )
        with pytest.raises(DependencyUnavailable, match="earlier operation"):
            await ensure_ready(queue_db, later_context)
        first_job, first_context = await claim(queries, FIRST_EVENT)
        await ensure_ready(queue_db, first_context)
        await queries.log_jobs([(first_job, "successful", None)])
        await ensure_ready(queue_db, later_context)
        await queries.log_jobs([(later_job, "successful", None)])
    finally:
        if later_task is not None:
            later_task.cancel()
            await asyncio.gather(later_task, return_exceptions=True)
        await later_connection.close()
        await first_connection.close()


async def test_Q14_legacy_adoption_joins_current_entity_order_once(queue_db):
    legacy_id = uuid4()
    await queue_db.execute("INSERT INTO jobs(id,action,status) VALUES($1,$2,'failed')", legacy_id, LATER_EVENT)
    async with queue_db.transaction():
        first = await enqueue_job(
            queue_db, event_name=FIRST_EVENT, payload={}, event_key="accepted-first", entity_key="shared"
        )
    async with queue_db.transaction():
        adopted = await enqueue_job(
            queue_db,
            event_name=LATER_EVENT,
            payload={},
            event_key="adopted-later",
            entity_key="shared",
            job_id=legacy_id,
        )
    assert adopted.id == legacy_id
    queries = FencedQueries.from_asyncpg_connection(queue_db)
    first_job, first_context = await claim(queries, FIRST_EVENT)
    assert first_context.job_id == first.id
    await ensure_ready(queue_db, first_context)
    original_order = await queue_db.fetchval("SELECT event_sequence FROM jobs WHERE id=$1", legacy_id)
    for supplied_id in (legacy_id, None):
        async with queue_db.transaction():
            replay = await enqueue_job(
                queue_db,
                event_name=LATER_EVENT,
                payload={},
                event_key="adopted-later",
                entity_key="shared",
                job_id=supplied_id,
            )
        assert replay.id == legacy_id
        assert await queue_db.fetchval("SELECT event_sequence FROM jobs WHERE id=$1", legacy_id) == original_order
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 2
    later_job, later_context = await claim(queries, LATER_EVENT)
    with pytest.raises(DependencyUnavailable, match="earlier operation"):
        await ensure_ready(queue_db, later_context)
    await queries.log_jobs([(first_job, "successful", None)])
    await ensure_ready(queue_db, later_context)
    await queries.log_jobs([(later_job, "successful", None)])


@pytest.mark.parametrize("rollback_savepoint", [False, True], ids=["transaction", "savepoint"])
async def test_Q14_rolled_back_producer_releases_order_without_blocking_other_entities(
    queue_db, queue_dsn, rollback_savepoint
):
    producer = await asyncpg.connect(queue_dsn)
    try:
        outer = producer.transaction()
        await outer.start()
        pending = producer.transaction() if rollback_savepoint else outer
        if rollback_savepoint:
            await pending.start()
        aborted = await enqueue_job(
            producer, event_name=FIRST_EVENT, payload={}, event_key="aborted", entity_key="shared"
        )
        async with queue_db.transaction():
            await enqueue_job(queue_db, event_name=LATER_EVENT, payload={}, event_key="later", entity_key="shared")
            await enqueue_job(queue_db, event_name=FIRST_EVENT, payload={}, event_key="unrelated", entity_key="other")
        queries = FencedQueries.from_asyncpg_connection(queue_db)
        later_job, later_context = await claim(queries, LATER_EVENT)
        with pytest.raises(DependencyUnavailable, match="producer"):
            await asyncio.wait_for(ensure_ready(queue_db, later_context), 3)
        unrelated_job, unrelated_context = await claim(queries, FIRST_EVENT)
        await asyncio.wait_for(ensure_ready(queue_db, unrelated_context), 3)
        await queries.log_jobs([(unrelated_job, "successful", None)])

        await pending.rollback()
        assert await queue_db.fetchval("SELECT count(*) FROM jobs WHERE id=$1", aborted.id) == 0
        await asyncio.wait_for(ensure_ready(queue_db, later_context), 3)
        await queries.log_jobs([(later_job, "successful", None)])
    finally:
        await producer.close()


async def test_Q14_reciprocal_entity_producers_can_commit_without_a_lock_cycle(queue_db, queue_dsn):
    connections = [await asyncpg.connect(queue_dsn) for _ in range(2)]
    try:
        transactions = [connection.transaction() for connection in connections]
        for transaction in transactions:
            await transaction.start()
        for index, connection in enumerate(connections):
            await enqueue_job(
                connection,
                event_name=FIRST_EVENT,
                payload={},
                event_key=f"producer:{index}:self",
                entity_key=f"user:{index}",
            )
        # Rival quest notifications enqueue self then rival: concurrent rivals
        # visit the same two users in opposite order within their transactions.
        async with asyncio.timeout(3):
            await asyncio.gather(
                *(
                    enqueue_job(
                        connection,
                        event_name=LATER_EVENT,
                        payload={},
                        event_key=f"producer:{index}:rival",
                        entity_key=f"user:{1 - index}",
                    )
                    for index, connection in enumerate(connections)
                )
            )
        await asyncio.gather(*(transaction.commit() for transaction in transactions))
        assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 4
    finally:
        await asyncio.gather(*(connection.close() for connection in connections))


async def test_Q14_entity_enqueue_does_not_invert_domain_row_locks(queue_db, queue_dsn):
    await queue_db.execute("INSERT INTO business_effects VALUES('xp',0)")
    early_producer = await asyncpg.connect(queue_dsn)
    early_mutation = await asyncpg.connect(queue_dsn)
    blocked_update = None
    try:
        producer_transaction = early_producer.transaction()
        mutation_transaction = early_mutation.transaction()
        await producer_transaction.start()
        await mutation_transaction.start()
        await enqueue_job(
            early_producer, event_name=FIRST_EVENT, payload={}, event_key="notification", entity_key="user:1"
        )
        await early_mutation.execute("UPDATE business_effects SET value=value+1 WHERE id='xp'")
        blocked_update = asyncio.create_task(
            early_producer.execute("UPDATE business_effects SET value=value+1 WHERE id='xp'")
        )
        await wait_for_database_wait(queue_db, early_producer, blocked_update)
        assert not blocked_update.done()

        # Verification publishes a notification before granting XP; an ordinary
        # XP grant updates the row before publishing its notification.
        await asyncio.wait_for(
            enqueue_job(early_mutation, event_name=LATER_EVENT, payload={}, event_key="xp", entity_key="user:1"),
            3,
        )
        await mutation_transaction.commit()
        await asyncio.wait_for(blocked_update, 3)
        await producer_transaction.commit()
        assert await queue_db.fetchval("SELECT value FROM business_effects WHERE id='xp'") == 2
        assert await queue_db.fetchval("SELECT count(*) FROM jobs WHERE entity_key='user:1'") == 2
    finally:
        if blocked_update is not None:
            blocked_update.cancel()
            await asyncio.gather(blocked_update, return_exceptions=True)
        await early_mutation.close()
        await early_producer.close()
