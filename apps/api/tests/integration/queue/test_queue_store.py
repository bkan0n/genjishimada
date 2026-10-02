"""Acceptance tests assert committed state, not mocked publication calls."""

from __future__ import annotations

import importlib
import importlib.util
from uuid import uuid4

import pytest

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


def store():
    name = "genjishimada_sdk.queue_store"
    assert importlib.util.find_spec(name) is not None, "Durable queue store is missing"
    return importlib.import_module(name)


async def test_Q01_enqueue_rolls_back_with_business_transaction(queue_db):
    enqueue = store().enqueue_job
    with pytest.raises(RuntimeError, match="abort"):
        async with queue_db.transaction():
            await queue_db.execute("INSERT INTO business_effects VALUES ('guide', 1)")
            await enqueue(queue_db, event_name="api.newsfeed.create", payload={"id": 1}, event_key="guide:1")
            raise RuntimeError("abort")
    assert await queue_db.fetchval("SELECT count(*) FROM business_effects") == 0
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 0
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 0


async def test_Q02_enqueue_requires_transaction(queue_db):
    with pytest.raises(ValueError, match="transaction"):
        await store().enqueue_job(queue_db, event_name="api.newsfeed.create", payload={}, event_key="event")
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 0


async def test_Q03_offline_worker_does_not_lose_accepted_work(queue_db):
    async with queue_db.transaction():
        response = await store().enqueue_job(
            queue_db, event_name="api.newsfeed.create", payload={"id": 8}, event_key="news:8"
        )
    row = await queue_db.fetchrow(
        "SELECT q.* FROM pgqueuer q JOIN jobs j ON j.queue_job_id=q.id WHERE j.id=$1", response.id
    )
    assert row["status"] == "queued"
    assert response.status == "queued"
    assert row["payload"]


async def test_Q25_duplicate_identity_returns_original_job_and_rejects_conflict(queue_db):
    async with queue_db.transaction():
        one = await store().enqueue_job(
            queue_db, event_name="api.newsfeed.create", payload={"id": 1}, event_key="guide:1"
        )
    async with queue_db.transaction():
        two = await store().enqueue_job(
            queue_db, event_name="api.newsfeed.create", payload={"id": 1}, event_key="guide:1"
        )
    assert one.id == two.id
    with pytest.raises(ValueError, match="payload"):
        async with queue_db.transaction():
            await store().enqueue_job(
                queue_db, event_name="api.newsfeed.create", payload={"id": 2}, event_key="guide:1"
            )
    assert await queue_db.fetchval("SELECT count(*) FROM pgqueuer") == 1


async def test_Q26_unknown_event_is_rejected_before_persistence(queue_db):
    with pytest.raises(ValueError, match="entrypoint"):
        async with queue_db.transaction():
            await store().enqueue_job(queue_db, event_name="missing", payload={}, event_key="missing")
    assert await queue_db.fetchval("SELECT count(*) FROM jobs") == 0
