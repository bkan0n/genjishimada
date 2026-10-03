"""Dependency recovery survives either ordering of concurrent terminal writes."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import asyncpg
import pytest
from pgqueuer.ports.repository import EntrypointExecutionParameter

from genjishimada_sdk.queue import HoldJobError
from genjishimada_sdk.queue_store import discard_job, enqueue_job, ensure_ready, get_job, retry_job
from genjishimada_sdk.queue_worker import FencedQueries, QueueWorker

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]
ROLE = "genjishimada_queue_worker"
PARENT_EVENT = "api.playtest.create"
CHILD_EVENT = "map.linked.newsfeed.requested"


async def claim(queries, event):
    jobs = await queries.dequeue(1, {event: EntrypointExecutionParameter(1)}, uuid4(), 2, timedelta(seconds=60))
    assert len(jobs) == 1
    return jobs[0]


@pytest.mark.parametrize("ordering", ["child-first", "parent-first", "uncommitted-child"])
async def test_Q14_dependency_recovery_survives_terminal_write_order(queue_db, queue_dsn, ordering):
    async with queue_db.transaction():
        parent = await enqueue_job(queue_db, event_name=PARENT_EVENT, payload={}, event_key="parent")
        child = await enqueue_job(queue_db, event_name=CHILD_EVENT, payload={}, event_key="child", depends_on=parent.id)
    parent_connection = await asyncpg.connect(queue_dsn, user=ROLE)
    child_connection = await asyncpg.connect(queue_dsn, user=ROLE)
    try:
        parent_queries = FencedQueries.from_asyncpg_connection(parent_connection)
        child_queries = FencedQueries.from_asyncpg_connection(child_connection)
        parent_job = await claim(parent_queries, PARENT_EVENT)
        await parent_queries.log_jobs([(parent_job, "failed", None)])
        child_job = await claim(child_queries, CHILD_EVENT)

        async def prepare(context):
            await ensure_ready(queue_db, context)

        async def unexpected_handler(context):
            pytest.fail("A child must not execute while its prerequisite has failed")

        worker = QueueWorker("unused", owner="api", before_job=prepare)
        with pytest.raises(HoldJobError, match="DependencyFailed"):
            await worker._execute(child_queries, unexpected_handler, child_job)

        await retry_job(
            queue_db, parent.id, operator_id=7, operator_ids={7}, expected_generation=0, request_id="parent-retry"
        )
        parent_job = await claim(parent_queries, PARENT_EVENT)

        async def finish_parent():
            await parent_queries.log_jobs([(parent_job, "successful", None)])

        async def park_child():
            await child_queries.log_jobs([(child_job, "failed", None)])

        if ordering == "child-first":
            await park_child()
            await finish_parent()
        elif ordering == "parent-first":
            await finish_parent()
            await park_child()
        else:
            # The parent trigger cannot see the child's uncommitted failure.
            async with child_connection.transaction():
                await park_child()
                await asyncio.wait_for(finish_parent(), 3)

        assert (await get_job(queue_db, parent.id)).status == "succeeded"
        resumed = await claim(child_queries, CHILD_EVENT)
        assert resumed.id == child_job.id
        assert await queue_db.fetchval("SELECT handler_failures FROM jobs WHERE id=$1", child.id) == 0
        assert await queue_db.fetchval("SELECT retry_generation FROM jobs WHERE id=$1", child.id) == 0
        # Recovery works with the production role, without exposing application data.
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await child_connection.fetch("SELECT * FROM public.jobs")
    finally:
        await parent_connection.close()
        await child_connection.close()


@pytest.mark.parametrize("parent_finishes_first", [True, False])
async def test_Q14_dependency_poll_leaves_unresolved_and_other_failures_held(
    queue_db, queue_dsn, monkeypatch, parent_finishes_first
):
    monkeypatch.setenv("QUEUE_OPERATOR_IDS", "7")
    async with queue_db.transaction():
        parent = await enqueue_job(queue_db, event_name=PARENT_EVENT, payload={}, event_key="completed-parent")
        pending = await enqueue_job(queue_db, event_name=PARENT_EVENT, payload={}, event_key="pending-parent")
        children = []
        for key, event, dependency in (
            ("ready", CHILD_EVENT, parent.id),
            ("ordinary-failure", CHILD_EVENT, parent.id),
            ("unresolved-parent", CHILD_EVENT, pending.id),
            ("other-entrypoint", "completion.ocr.requested", parent.id),
            ("uncertain-effect", CHILD_EVENT, parent.id),
            ("discarded", CHILD_EVENT, parent.id),
        ):
            children.append(
                await enqueue_job(queue_db, event_name=event, payload={}, event_key=key, depends_on=dependency)
            )
    queries = FencedQueries.from_asyncpg_connection(queue_db)
    parent_job = await claim(queries, PARENT_EVENT)
    if parent_finishes_first:
        await queries.log_jobs([(parent_job, "successful", None)])
    for index, child in enumerate(children):
        await queue_db.execute(
            """UPDATE public.pgqueuer SET status='failed',failure_code=$2
               WHERE id=(SELECT queue_job_id FROM jobs WHERE id=$1)""",
            child.id,
            "ordinary_failure" if index == 1 else "dependency_failed",
        )
    await queue_db.execute(
        """INSERT INTO public.job_effects(job_id,effect_key,kind,state,fingerprint)
           VALUES($1,'uncertain','external','started','destination')""",
        children[4].id,
    )
    await discard_job(
        queue_db, children[5].id, operator_id=7, expected_generation=0, request_id="discard", reason="Reviewed discard"
    )
    await queue_db.execute(
        """UPDATE public.pgqueuer SET attempts=4,handler_failures=2
           WHERE id=(SELECT queue_job_id FROM jobs WHERE id=$1)""",
        children[0].id,
    )
    if not parent_finishes_first:
        await queries.log_jobs([(parent_job, "successful", None)])

    connection = await asyncpg.connect(queue_dsn, user=ROLE)
    try:
        worker_queries = FencedQueries.from_asyncpg_connection(connection)
        resumed = await claim(worker_queries, CHILD_EVENT)
        assert resumed.id == await queue_db.fetchval("SELECT queue_job_id FROM jobs WHERE id=$1", children[0].id)
        expected = ["failed", "failed", "failed" if parent_finishes_first else "queued", "failed", "failed"]
        assert [(await get_job(queue_db, child.id)).status for child in children[1:]] == expected
        assert dict(
            await queue_db.fetchrow(
                "SELECT attempts,handler_failures,retry_generation FROM jobs WHERE id=$1", children[0].id
            )
        ) == {"attempts": 4, "handler_failures": 2, "retry_generation": 0}
        assert (await get_job(queue_db, children[5].id)).error_code == "discarded"
    finally:
        await connection.close()
