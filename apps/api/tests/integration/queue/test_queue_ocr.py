"""OCR proof changes are checked against the locked authoritative completion."""

from uuid import uuid4

import pytest
from genjishimada_sdk.completions import ExtractedResultResponse
from genjishimada_sdk.queue_store import enqueue_job
from litestar.datastructures import State
from services.completions_service import CompletionsService
from services.queue_continuations import QueueContinuations

from .test_queue_producers import asyncpg_pool, claim_job, create_test_completion, create_test_map, create_test_user

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


async def test_Q08_Q04_ocr_cannot_verify_proof_changed_during_extraction(
    asyncpg_pool,
    create_test_user,
    create_test_map,
    create_test_completion,
    monkeypatch,
):
    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(code=code)
    completion_id = await create_test_completion(user_id, map_id, verified=False)
    original = dict(
        completion_id=completion_id, user_id=user_id, code=code, time=30.5, screenshot="https://example.com/run.png"
    )
    async with asyncpg_pool.acquire() as conn, conn.transaction():
        job = await enqueue_job(conn, event_name="completion.ocr.requested", payload=original, event_key=str(uuid4()))
    context = await claim_job(asyncpg_pool, job)
    verified = []

    async def verify(self, *args, **kwargs):
        verified.append(True)

    async def extract(self, payload, names):
        await asyncpg_pool.execute(
            "UPDATE core.completions SET time=29,screenshot='https://example.com/changed.png' WHERE id=$1",
            completion_id,
        )
        return ExtractedResultResponse(name=names[0], time=30.5, code=code, sources={}, texts={})

    monkeypatch.setattr(CompletionsService, "verify_completion_with_pool", verify)
    monkeypatch.setattr(QueueContinuations, "extract", extract)
    await QueueContinuations(State({"db_pool": asyncpg_pool})).ocr(context)
    assert verified == []
    assert not await asyncpg_pool.fetchval("SELECT verified FROM core.completions WHERE id=$1", completion_id)
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM jobs WHERE action='api.completion.submission' AND entity_key=$1",
            f"completion:{completion_id}",
        )
        == 1
    )
