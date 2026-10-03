"""The pinned queue library must preserve interrupted work and fence stale writers."""

import asyncio
import importlib.util
import logging
import time
from datetime import timedelta
from uuid import uuid4

import pytest
from pgqueuer.ports.repository import EntrypointExecutionParameter
from genjishimada_sdk.queue_store import enqueue_job, get_job

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


def runtime():
    assert importlib.util.find_spec("genjishimada_sdk.queue_worker"), "Fenced queue runtime is missing"
    from genjishimada_sdk import queue_worker

    return queue_worker


async def claimed(conn):
    async with conn.transaction():
        public = await enqueue_job(conn, event_name="api.newsfeed.create", payload={"id": 1}, event_key=str(uuid4()))
    queries = runtime().FencedQueries.from_asyncpg_connection(conn)
    jobs = await queries.dequeue(
        1, {"api.newsfeed.create": EntrypointExecutionParameter(concurrency_limit=1)}, uuid4(), 2, timedelta(seconds=60)
    )
    return public, queries, jobs[0]


async def test_Q06_cancellation_requeues_instead_of_deleting(queue_db):
    public, queries, job = await claimed(queue_db)
    await queries.log_jobs([(job, "canceled", None)])
    assert await queue_db.fetchval("SELECT status FROM pgqueuer WHERE id=$1", job.id) == "queued"
    assert (await get_job(queue_db, public.id)).status == "queued"


async def test_Q08_stale_owner_cannot_complete_retry_or_heartbeat_new_claim(queue_db):
    public, queries, job = await claimed(queue_db)
    before_logs = await queue_db.fetchval("SELECT count(*) FROM pgqueuer_log")
    owner = uuid4()
    await queue_db.execute(
        "UPDATE pgqueuer SET queue_manager_id=$2,updated=clock_timestamp(),heartbeat=now()-interval '2 minutes' WHERE id=$1",
        job.id,
        owner,
    )
    heartbeat = await queue_db.fetchval("SELECT heartbeat FROM pgqueuer WHERE id=$1", job.id)
    await queries.update_heartbeat([job.id])
    await queries.retry_job(job, timedelta(), None)
    await queries.log_jobs([(job, "successful", None)])
    row = await queue_db.fetchrow("SELECT * FROM pgqueuer WHERE id=$1", job.id)
    assert row["queue_manager_id"] == owner
    assert row["status"] == "picked"
    assert row["heartbeat"] == heartbeat
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer_log") == before_logs


async def test_Q16_success_is_retained_after_queue_row_removed(queue_db):
    public, queries, job = await claimed(queue_db)
    await queries.log_jobs([(job, "successful", None)])
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0
    assert (await get_job(queue_db, public.id)).status == "succeeded"
    await queue_db.execute("DELETE FROM pgqueuer_log")
    assert (await get_job(queue_db, public.id)).status == "succeeded"


async def test_Q17_failure_is_held_and_durably_inspectable(queue_db):
    public, queries, job = await claimed(queue_db)
    await queries.log_jobs([(job, "failed", None)])
    assert (await get_job(queue_db, public.id)).status == "failed"
    assert await queue_db.fetchval("SELECT count(*) FROM job_alerts WHERE job_id=$1", public.id) == 1


async def test_Q26_worker_rejects_duplicate_and_wrong_owner():
    worker = runtime().QueueWorker("postgresql://unused", owner="bot")

    async def handle(ctx):
        pass

    worker.add_handler("api.newsfeed.create", handle)
    with pytest.raises(ValueError, match="already"):
        worker.add_handler("api.newsfeed.create", handle)
    with pytest.raises(ValueError, match="owner"):
        worker.add_handler("completion.ocr.requested", handle)


async def test_Q17_handler_deadline_exhausts_ordinary_budget(queue_db):
    public, queries, job = await claimed(queue_db)
    worker = runtime().QueueWorker("unused", owner="bot", timeout_seconds=0.001, retry_delays=())

    async def stuck(ctx):
        await asyncio.sleep(60)

    with pytest.raises(runtime().HoldJobError, match="TimeoutError"):
        await worker._execute(queries, stuck, job)
    assert await queue_db.fetchval("SELECT handler_failures FROM pgqueuer WHERE id=$1", job.id) == 1


async def test_Q07_database_startup_error_defers_without_handler_failure(queue_db):
    module = runtime()
    public, queries, job = await claimed(queue_db)
    worker = module.QueueWorker("unused", owner="bot", retry_delays=())

    async def database_starting(ctx):
        raise module.asyncpg.CannotConnectNowError("the database system is starting up")

    with pytest.raises(module.RetryRequested):
        await worker._execute(queries, database_starting, job)
    assert await queue_db.fetchval("SELECT handler_failures FROM pgqueuer WHERE id=$1", job.id) == 0
    assert worker.state == "degraded"


@pytest.mark.parametrize("configuration_error", ["missing-grant", "missing-schema"])
async def test_Q07_startup_configuration_failure_has_bounded_logging_and_recovers(
    queue_db, queue_dsn, monkeypatch, caplog, configuration_error
):
    module = runtime()
    monkeypatch.setattr(module, "SUSTAINED_OUTAGE_SECONDS", 0.01)
    monkeypatch.setattr(module.random, "random", lambda: 0)
    caplog.set_level(logging.INFO, logger=module.__name__)
    role = "genjishimada_queue_worker"
    async with queue_db.transaction():
        public = await enqueue_job(
            queue_db, event_name="api.newsfeed.create", payload={"id": 1}, event_key=str(uuid4())
        )
    if configuration_error == "missing-grant":
        await queue_db.execute(f"REVOKE SELECT ON public.pgqueuer FROM {role}")
        restore = f"GRANT SELECT ON public.pgqueuer TO {role}"
    else:
        await queue_db.execute("ALTER TABLE public.pgqueuer RENAME TO unavailable_queue")
        restore = "ALTER TABLE public.unavailable_queue RENAME TO pgqueuer"
    attempts = []
    original_connect = module.asyncpg.connect

    async def connect(*args, **kwargs):
        connection = await original_connect(*args, **kwargs)
        attempts.append(time.monotonic())
        return connection

    monkeypatch.setattr(module.asyncpg, "connect", connect)
    worker_dsn = queue_dsn.replace("postgresql://postgres@", f"postgresql://{role}@")
    worker = module.QueueWorker(worker_dsn, owner="bot", poll_seconds=0.02, drain_seconds=0.1)
    handled = asyncio.Event()

    async def handle(ctx):
        handled.set()

    worker.add_handler("api.newsfeed.create", handle)
    task = asyncio.create_task(worker.run())
    try:
        async with asyncio.timeout(8):
            while len(attempts) < 3 or worker.state != "degraded":
                await asyncio.sleep(0.01)
        messages = [record.getMessage() for record in caplog.records if record.name == module.__name__]
        assert sum("Queue dependency unavailable:" in message for message in messages) == 1
        assert sum("Sustained queue connection outage:" in message for message in messages) == 1
        assert not any("Queue dependency recovered:" in message for message in messages)
        assert attempts[1] - attempts[0] >= 0.9
        assert attempts[2] - attempts[1] >= 1.8
        await queue_db.execute(restore)
        async with asyncio.timeout(8):
            await handled.wait()
            while (await get_job(queue_db, public.id)).status != "succeeded":
                await asyncio.sleep(0.01)
        assert worker.state == "running"
        messages = [record.getMessage() for record in caplog.records if record.name == module.__name__]
        assert sum("Queue dependency recovered:" in message for message in messages) == 1
    finally:
        worker.stop()
        await asyncio.wait_for(task, 3)
