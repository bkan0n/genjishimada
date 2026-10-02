"""Queue acceptance through real business services and PostgreSQL transactions."""

from __future__ import annotations

import asyncio
from pathlib import Path
import asyncpg
from uuid import uuid4

import pytest
from genjishimada_sdk.maps import GuideResponse
from litestar.datastructures import Headers, State

from repository.lootbox_repository import LootboxRepository
from repository.maps_repository import MapsRepository
from repository.newsfeed_repository import NewsfeedRepository
from repository.users_repository import UsersRepository
from services.lootbox_service import LootboxService
from services.maps_service import MapsService
from services.newsfeed_service import NewsfeedService
from services.users_service import UsersService

pytestmark = [pytest.mark.queue, pytest.mark.asyncio]


@pytest.fixture
async def asyncpg_pool(queue_postgres):
    """Apply the actual application migrations in a test-owned database."""
    from app import _async_pg_init

    root = Path(__file__).resolve().parents[3]
    database = f"producers_{uuid4().hex}"
    admin = await asyncpg.connect(queue_postgres["dsn"])
    await admin.execute(f'CREATE DATABASE "{database}"')
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    conn = await asyncpg.connect(dsn)
    try:
        for directory in (root / "migrations", root / "seeds"):
            for path in sorted(directory.glob("*.sql")):
                await conn.execute(path.read_text())
    finally:
        await conn.close()
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5, init=_async_pg_init)
    try:
        yield pool
    finally:
        await pool.close()
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def create_test_user(asyncpg_pool):
    async def create(nickname="Queue User"):
        user_id = (uuid4().int % 800_000_000_000_000_000) + 100_000_000_000_000_000
        await asyncpg_pool.execute(
            "INSERT INTO core.users(id,nickname,global_name) VALUES($1,$2,$2)", user_id, nickname
        )
        return user_id

    return create


@pytest.fixture
async def create_test_map(asyncpg_pool, create_test_user):
    async def create(code=None, **overrides):
        from genjishimada_sdk.difficulties import DIFFICULTY_RANGES_ALL

        creator_id = await create_test_user()
        difficulty = overrides.get("difficulty", "Medium")
        lower, upper = DIFFICULTY_RANGES_ALL[difficulty]
        map_id = await asyncpg_pool.fetchval(
            """INSERT INTO core.maps
            (code,map_name,category,checkpoints,official,playtesting,difficulty,raw_difficulty,hidden,archived)
            VALUES($1,$2,'Classic',10,$3,$4,$5,$6,false,false) RETURNING id""",
            code or f"T{uuid4().hex[:5].upper()}",
            overrides.get("map_name", "Hanamura"),
            overrides.get("official", True),
            overrides.get("playtesting", "Approved"),
            difficulty,
            (lower + upper) / 2,
        )
        await asyncpg_pool.execute(
            "INSERT INTO maps.creators(map_id,user_id,is_primary) VALUES($1,$2,true)", map_id, creator_id
        )
        return map_id

    return create


@pytest.fixture
async def create_test_completion(asyncpg_pool):
    async def create(user_id, map_id, **overrides):
        return await asyncpg_pool.fetchval(
            """INSERT INTO core.completions
            (user_id,map_id,verified,legacy,time,screenshot,completion,verified_by)
            VALUES($1,$2,$3,false,$4,$5,$6,$7) RETURNING id""",
            user_id,
            map_id,
            overrides.get("verified", True),
            overrides.get("time", 30.5),
            overrides.get("screenshot", "https://example.com/run.png"),
            overrides.get("completion", True),
            overrides.get("verified_by"),
        )

    return create


def guide_services(pool):
    state = State({"db_pool": pool})
    return (
        MapsService(pool, state, MapsRepository(pool)),
        LootboxService(pool, state, LootboxRepository(pool)),
        NewsfeedService(pool, state, NewsfeedRepository(pool)),
        UsersService(pool, state, UsersRepository(pool)),
    )


@pytest.mark.parametrize("acceptance", ["approve", "force_accept"])
async def test_Q09_concurrent_playtest_acceptance_reuses_one_transition(
    asyncpg_pool,
    create_test_user,
    create_test_map,
    create_test_completion,
    acceptance,
):
    from repository.playtest_repository import PlaytestRepository
    from services.playtest_service import PlaytestService
    from genjishimada_sdk.difficulties import DIFFICULTY_MIDPOINTS

    verifier = await create_test_user()
    map_id = await create_test_map(playtesting="In Progress")
    thread_id = (uuid4().int % 800_000_000_000_000_000) + 100_000_000_000_000_000
    await asyncpg_pool.execute(
        "INSERT INTO playtests.meta(map_id,thread_id,initial_difficulty) VALUES($1,$2,5)",
        map_id,
        thread_id,
    )
    await create_test_completion(verifier, map_id, completion=False)
    await asyncpg_pool.execute(
        "INSERT INTO playtests.votes(map_id,playtest_thread_id,user_id,difficulty) VALUES($1,$2,$3,$4)",
        map_id,
        thread_id,
        verifier,
        DIFFICULTY_MIDPOINTS["Medium"],
    )
    service = PlaytestService(
        asyncpg_pool,
        State({"db_pool": asyncpg_pool}),
        PlaytestRepository(asyncpg_pool),
        MapsRepository(asyncpg_pool),
    )

    async def accept():
        if acceptance == "approve":
            return await service.approve(thread_id, verifier, Headers())
        return await service.force_accept(thread_id, "Medium", verifier, Headers())

    first, concurrent = await asyncio.gather(accept(), accept())
    assert first.id == concurrent.id
    # A later duplicate with different input is still the already accepted transition.
    repeated = await service.force_accept(thread_id, "Hard", verifier, Headers())
    assert repeated.id == first.id
    assert (await service.approve(thread_id, verifier, Headers())).id == first.id
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE entity_key=$1",
            f"playtest:{thread_id}",
        )
        == 1
    )
    assert (
        float(await asyncpg_pool.fetchval("SELECT raw_difficulty FROM core.maps WHERE id=$1", map_id))
        == DIFFICULTY_MIDPOINTS["Medium"]
    )


@pytest.mark.parametrize("acceptance", ["approve", "force_accept"])
async def test_Q09_playtest_reset_starts_a_new_acceptance_transition(
    asyncpg_pool,
    create_test_user,
    create_test_map,
    create_test_completion,
    acceptance,
):
    from repository.playtest_repository import PlaytestRepository
    from services.playtest_service import PlaytestService

    verifier = await create_test_user()
    map_id = await create_test_map(playtesting="In Progress")
    thread_id = (uuid4().int % 800_000_000_000_000_000) + 100_000_000_000_000_000
    await asyncpg_pool.execute(
        "INSERT INTO playtests.meta(map_id,thread_id,initial_difficulty) VALUES($1,$2,5)",
        map_id,
        thread_id,
    )
    await create_test_completion(verifier, map_id, completion=False)
    await asyncpg_pool.execute(
        "INSERT INTO playtests.votes(map_id,playtest_thread_id,user_id,difficulty) VALUES($1,$2,$3,5)",
        map_id,
        thread_id,
        verifier,
    )
    service = PlaytestService(
        asyncpg_pool,
        State({"db_pool": asyncpg_pool}),
        PlaytestRepository(asyncpg_pool),
        MapsRepository(asyncpg_pool),
    )

    async def accept():
        if acceptance == "approve":
            return await service.approve(thread_id, verifier, Headers())
        return await service.force_accept(thread_id, "Hard", verifier, Headers())

    first = await accept()
    reset = await service.reset(thread_id, verifier, "Re-evaluate difficulty", False, False, Headers())
    second = await accept()
    repeated = await accept()
    assert len({first.id, reset.id, second.id}) == 3
    assert second.id == repeated.id
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE entity_key=$1",
            f"playtest:{thread_id}",
        )
        == 3
    )


async def test_Q25_same_guide_concurrent_retry_rewards_once(asyncpg_pool, create_test_user, create_test_map):
    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(code=code)
    maps, lootbox, newsfeed, users = guide_services(asyncpg_pool)
    data = GuideResponse(user_id=user_id, url="https://example.com/guide")
    results = await asyncio.gather(
        *[maps.submit_guide(code, data, Headers(), lootbox, newsfeed, users) for _ in range(2)]
    )
    assert results == [data, data]
    async with asyncpg_pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM maps.guides WHERE map_id=$1 AND user_id=$2", map_id, user_id) == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.jobs WHERE action='api.xp.grant' AND entity_key=$1", f"user:{user_id}"
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.newsfeed WHERE payload->>'code'=$1 AND event_type='guide'", code
            )
            == 1
        )


async def test_Q02_guide_enqueue_failure_rolls_back(asyncpg_pool, create_test_user, create_test_map, monkeypatch):
    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(code=code)
    maps, lootbox, newsfeed, users = guide_services(asyncpg_pool)

    # Inject the database error at the real queue storage boundary; the services
    # and all writes before the error use PostgreSQL normally.
    from services import base

    original = base.enqueue_job

    async def fail_newsfeed(conn, **kwargs):
        if kwargs["event_name"] == "api.newsfeed.create":
            await conn.execute("SELECT 1/0")
        return await original(conn, **kwargs)

    monkeypatch.setattr(base, "enqueue_job", fail_newsfeed)
    with pytest.raises(Exception, match="division by zero"):
        await maps.submit_guide(
            code,
            GuideResponse(user_id=user_id, url="https://example.com/rollback"),
            Headers(),
            lootbox,
            newsfeed,
            users,
        )
    async with asyncpg_pool.acquire() as conn:
        assert (
            await conn.fetchval("SELECT count(*) FROM maps.guides WHERE map_id=$1 AND user_id=$2", map_id, user_id) == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.jobs WHERE action='api.xp.grant' AND entity_key=$1", f"user:{user_id}"
            )
            == 0
        )
        assert await conn.fetchval("SELECT count(*) FROM lootbox.xp WHERE user_id=$1", user_id) == 0


async def test_Q25_different_url_retains_conflict(asyncpg_pool, create_test_user, create_test_map):
    from services.exceptions.maps import DuplicateGuideError

    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    await create_test_map(code=code)
    maps, lootbox, newsfeed, users = guide_services(asyncpg_pool)
    await maps.submit_guide(
        code, GuideResponse(user_id=user_id, url="https://example.com/first"), Headers(), lootbox, newsfeed, users
    )
    with pytest.raises(DuplicateGuideError):
        await maps.submit_guide(
            code, GuideResponse(user_id=user_id, url="https://example.com/second"), Headers(), lootbox, newsfeed, users
        )


async def test_Q03_Q04_completion_ocr_work_commits_while_worker_offline(
    asyncpg_pool, create_test_user, create_test_map
):
    from types import SimpleNamespace
    from genjishimada_sdk.completions import CompletionCreateRequest
    from repository.completions_repository import CompletionsRepository
    from repository.notifications_repository import NotificationsRepository
    from services.completions_service import CompletionsService
    from services.notifications_service import NotificationsService

    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    await create_test_map(code=code)
    state = State({"db_pool": asyncpg_pool})
    users = UsersService(asyncpg_pool, state, UsersRepository(asyncpg_pool))
    notifications = NotificationsService(
        asyncpg_pool, state, NotificationsRepository(asyncpg_pool), UsersRepository(asyncpg_pool)
    )
    svc = CompletionsService(asyncpg_pool, state, CompletionsRepository(asyncpg_pool))
    result = await svc.submit_completion(
        CompletionCreateRequest(
            code=code, user_id=user_id, time=25.0, screenshot="https://example.com/run.png", video=None
        ),
        SimpleNamespace(headers=Headers()),
        notifications,
        users,
    )
    assert result.job_status is None  # Existing public OCR response remains unchanged.
    async with asyncpg_pool.acquire() as conn:
        assert await conn.fetchval("SELECT id FROM core.completions WHERE id=$1", result.completion_id)
        assert (
            await conn.fetchval(
                """SELECT count(*) FROM public.jobs j JOIN public.pgqueuer q ON q.id=j.queue_job_id
            WHERE j.action='completion.ocr.requested' AND j.entity_key=$1""",
                f"completion:{result.completion_id}",
            )
            == 1
        )


async def test_Q09_verification_transitions_have_distinct_durable_identity(
    asyncpg_pool, create_test_user, create_test_map, create_test_completion
):
    from genjishimada_sdk.completions import CompletionVerificationUpdateRequest
    from repository.completions_repository import CompletionsRepository
    from services.completions_service import CompletionsService

    user_id = await create_test_user()
    verifier = await create_test_user()
    map_id = await create_test_map()
    completion_id = await create_test_completion(user_id, map_id, verified=False)
    svc = CompletionsService(asyncpg_pool, State({"db_pool": asyncpg_pool}), CompletionsRepository(asyncpg_pool))
    jobs = []
    for verdict in (True, False, True):
        jobs.append(
            await svc.verify_completion_with_pool(
                None,
                completion_id,
                CompletionVerificationUpdateRequest(verified=verdict, verified_by=verifier, reason="Review"),
            )
        )
    assert len({job.id for job in jobs}) == 3
    duplicate = await svc.verify_completion_with_pool(
        None, completion_id, CompletionVerificationUpdateRequest(verified=True, verified_by=verifier, reason="Review")
    )
    assert duplicate.id == jobs[-1].id
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE action='api.completion.verification' AND entity_key=$1",
            f"completion:{completion_id}",
        )
        == 3
    )


async def test_Q10_world_record_guard_and_xp_roll_back_together(
    asyncpg_pool, create_test_user, create_test_map, create_test_completion, monkeypatch
):
    from genjishimada_sdk.xp import XpGrantRequest
    from repository.completions_repository import CompletionsRepository
    from services.completions_service import CompletionsService
    from services import base

    user_id = await create_test_user()
    map_id = await create_test_map()
    completion_id = await create_test_completion(user_id, map_id)
    svc = CompletionsService(asyncpg_pool, State({"db_pool": asyncpg_pool}), CompletionsRepository(asyncpg_pool))
    original = base.enqueue_job

    async def fail_enqueue(conn, **kwargs):
        await conn.execute("SELECT 1/0")

    monkeypatch.setattr(base, "enqueue_job", fail_enqueue)
    with pytest.raises(Exception, match="division by zero"):
        await svc.grant_world_record_reward(completion_id, XpGrantRequest(100, "World Record"), Headers())
    assert not await asyncpg_pool.fetchval("SELECT wr_xp_check FROM core.completions WHERE id=$1", completion_id)
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM lootbox.xp WHERE user_id=$1", user_id) == 0
    monkeypatch.setattr(base, "enqueue_job", original)
    results = await asyncio.gather(
        *[
            svc.grant_world_record_reward(completion_id, XpGrantRequest(100, "World Record"), Headers())
            for _ in range(2)
        ]
    )
    assert sum(result is not None for result in results) == 1
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE action='api.xp.grant' AND entity_key=$1", f"user:{user_id}"
        )
        == 1
    )


async def claim_job(pool, job):
    from genjishimada_sdk.queue import JobContext

    row = await pool.fetchrow(
        """UPDATE public.pgqueuer SET status='picked',queue_manager_id=$2,updated=now()
        WHERE id=(SELECT queue_job_id FROM public.jobs WHERE id=$1) RETURNING *""",
        job.id,
        uuid4(),
    )
    import msgspec
    from genjishimada_sdk.queue import JobEnvelope

    envelope = msgspec.json.decode(row["payload"], type=JobEnvelope)
    return JobContext(
        job.id,
        envelope.event_name,
        envelope.event_key,
        row["id"],
        row["queue_manager_id"],
        row["updated"],
        envelope.payload,
    )


async def test_Q04_ocr_decision_and_fallback_are_atomic_and_replay_safe(
    asyncpg_pool, create_test_user, create_test_map, create_test_completion, monkeypatch
):
    import aiohttp
    from genjishimada_sdk.queue_store import enqueue_job
    from services.queue_continuations import QueueContinuations

    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(code=code)
    completion_id = await create_test_completion(user_id, map_id, verified=False)
    payload = dict(
        completion_id=completion_id, user_id=user_id, code=code, time=30.5, screenshot="https://example.com/ocr.png"
    )
    async with asyncpg_pool.acquire() as conn, conn.transaction():
        job = await enqueue_job(
            conn, event_name="completion.ocr.requested", payload=payload, event_key=f"ocr:{completion_id}"
        )
    context = await claim_job(asyncpg_pool, job)
    calls = []

    async def failed_ocr(self, payload, names):
        from utilities.transactions import active_connection

        assert active_connection() is None
        calls.append(1)
        raise aiohttp.ClientConnectionError("OCR unavailable")

    monkeypatch.setattr(QueueContinuations, "extract", failed_ocr)
    # The second handler models death after the decision committed but before
    # PGQueuer recorded completion; it must use the durable decision receipt.
    await QueueContinuations(State({"db_pool": asyncpg_pool})).ocr(context)
    await QueueContinuations(State({"db_pool": asyncpg_pool})).ocr(context)
    assert len(calls) == 1
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.job_effects WHERE job_id=$1 AND effect_key='ocr-decision'", job.id
        )
        == 1
    )
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE action='api.completion.submission' AND entity_key=$1",
            f"completion:{completion_id}",
        )
        == 1
    )
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM notifications.events WHERE user_id=$1", user_id) == 1


def effect_headers(context, effect):
    return {
        "X-API-KEY": "testing",
        "X-Job-ID": str(context.job_id),
        "X-Job-Effect": effect,
        "X-Job-Manager": str(context.manager_id),
        "X-Job-Claimed-At": context.claimed_at.isoformat(),
    }


@pytest.fixture
async def producer_http(asyncpg_pool, queue_postgres):
    from app import create_app
    from litestar.testing import AsyncTestClient

    database = await asyncpg_pool.fetchval("SELECT current_database()")
    dsn = queue_postgres["dsn"].rsplit("/", 1)[0] + "/" + database
    async with AsyncTestClient(app=create_app(dsn, queue_workers_enabled=False)) as client:
        yield client


async def test_Q08_Q10_http_reward_replay_is_atomic(asyncpg_pool, producer_http, create_test_user):
    from genjishimada_sdk.queue_store import enqueue_job

    user_id = await create_test_user()
    async with asyncpg_pool.acquire() as conn, conn.transaction():
        job = await enqueue_job(
            conn, event_name="api.completion.verification", payload={"completion_id": 1}, event_key=f"http:{uuid4()}"
        )
    context = await claim_job(asyncpg_pool, job)
    headers = effect_headers(context, "xp:completion:1")
    first = await producer_http.post(
        f"/api/v3/lootbox/users/{user_id}/xp", json={"amount": 100, "type": "World Record"}, headers=headers
    )
    assert first.status_code == 200, first.text
    second = await producer_http.post(
        f"/api/v3/lootbox/users/{user_id}/xp", json={"amount": 100, "type": "World Record"}, headers=headers
    )
    assert second.status_code == 200, second.text
    assert first.json() == second.json()
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE action='api.xp.grant' AND entity_key=$1", f"user:{user_id}"
        )
        == 1
    )
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.job_effects WHERE job_id=$1 AND effect_key=$2 AND state='completed'",
            job.id,
            "xp:completion:1",
        )
        == 1
    )
    # A stale worker has no authority to start another effect.
    headers["X-Job-Manager"] = str(uuid4())
    headers["X-Job-Effect"] = "xp:another-effect"
    stale = await producer_http.post(
        f"/api/v3/lootbox/users/{user_id}/xp", json={"amount": 100, "type": "World Record"}, headers=headers
    )
    assert stale.status_code == 409, stale.text
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.jobs WHERE action='api.xp.grant' AND entity_key=$1", f"user:{user_id}"
        )
        == 1
    )


async def test_Q01_http_receipt_rolls_back_with_failed_enqueue(
    asyncpg_pool, producer_http, create_test_user, monkeypatch
):
    from genjishimada_sdk.queue_store import enqueue_job
    from services import base

    user_id = await create_test_user()
    async with asyncpg_pool.acquire() as conn, conn.transaction():
        job = await enqueue_job(
            conn, event_name="api.completion.verification", payload={"completion_id": 1}, event_key=f"http:{uuid4()}"
        )
    context = await claim_job(asyncpg_pool, job)

    async def failed_enqueue(conn, **kwargs):
        await conn.execute("SELECT 1/0")

    monkeypatch.setattr(base, "enqueue_job", failed_enqueue)
    response = await producer_http.post(
        f"/api/v3/lootbox/users/{user_id}/xp",
        json={"amount": 100, "type": "World Record"},
        headers=effect_headers(context, "xp:rollback"),
    )
    assert response.status_code == 500, response.text
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM lootbox.xp WHERE user_id=$1", user_id) == 0
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM public.job_effects WHERE job_id=$1", job.id) == 0


async def test_Q04_tournament_non_pb_ocr_survives_speed_trigger(
    asyncpg_pool, create_test_user, create_test_map, create_test_completion
):
    from types import SimpleNamespace
    from genjishimada_sdk.completions import CompletionCreateRequest
    from repository.completions_repository import CompletionsRepository
    from repository.tournaments_repository import TournamentRepository
    from repository.notifications_repository import NotificationsRepository
    from services.completions_service import CompletionsService
    from services.notifications_service import NotificationsService

    user_id = await create_test_user()
    code = f"T{uuid4().hex[:5].upper()}"
    map_id = await create_test_map(code=code)
    await create_test_completion(user_id, map_id, time=10.0, completion=True)
    category = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.categories(name,difficulties) VALUES($1, ARRAY['Medium']) RETURNING id",
        f"queue-{uuid4()}",
    )
    cycle = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.cycles(category_id,map_id,status) VALUES($1,$2,'active') RETURNING id",
        category,
        map_id,
    )
    state = State({"db_pool": asyncpg_pool})
    users = UsersService(asyncpg_pool, state, UsersRepository(asyncpg_pool))
    notifications = NotificationsService(
        asyncpg_pool, state, NotificationsRepository(asyncpg_pool), UsersRepository(asyncpg_pool)
    )
    svc = CompletionsService(
        asyncpg_pool, state, CompletionsRepository(asyncpg_pool), TournamentRepository(asyncpg_pool)
    )
    result = await svc.submit_completion(
        CompletionCreateRequest(
            code=code, user_id=user_id, time=20.0, screenshot="https://example.com/nonpb.png", video=None
        ),
        SimpleNamespace(headers=Headers()),
        notifications,
        users,
    )
    assert result.completion_id == 0
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM tournaments.completions WHERE cycle_id=$1 AND user_id=$2", cycle, user_id
        )
        == 1
    )
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM public.jobs WHERE action='tournament.ocr.requested'") == 1


async def test_Q14_linked_map_parent_retry_releases_continuation(asyncpg_pool, create_test_map):
    from genjishimada_sdk.maps import LinkMapsCreateRequest
    from genjishimada_sdk.queue import DependencyUnavailable, DependencyFailed
    from genjishimada_sdk.queue_store import ensure_ready, retry_job, get_job
    from services.queue_continuations import QueueContinuations

    official_code, unofficial_code = f"T{uuid4().hex[:5].upper()}", f"T{uuid4().hex[:5].upper()}"
    await create_test_map(code=unofficial_code, official=False)
    maps, lootbox, newsfeed, _ = guide_services(asyncpg_pool)
    parent = await maps.link_map_codes(
        LinkMapsCreateRequest(official_code, unofficial_code), Headers(), newsfeed, lootbox
    )
    assert parent is not None
    child_id = await asyncpg_pool.fetchval(
        "SELECT id FROM public.jobs WHERE action='map.linked.newsfeed.requested' AND depends_on=$1", parent.id
    )
    assert child_id is not None
    async with asyncpg_pool.acquire() as conn:
        child = await get_job(conn, child_id)
    context = await claim_job(asyncpg_pool, child)
    async with asyncpg_pool.acquire() as conn:
        with pytest.raises(DependencyUnavailable):
            await ensure_ready(conn, context)
    await asyncpg_pool.execute(
        "UPDATE public.pgqueuer SET status='failed',failure_code='handler_failed' WHERE id=(SELECT queue_job_id FROM public.jobs WHERE id=$1)",
        parent.id,
    )
    async with asyncpg_pool.acquire() as conn:
        with pytest.raises(DependencyFailed):
            await ensure_ready(conn, context)
    await asyncpg_pool.execute(
        "UPDATE public.pgqueuer SET status='failed',failure_code='dependency_failed' WHERE id=$1", context.queue_job_id
    )
    async with asyncpg_pool.acquire() as conn:
        accepted = await retry_job(
            conn, parent.id, operator_id=1, operator_ids={1}, expected_generation=0, request_id=f"linked:{uuid4()}"
        )
    assert accepted["outcome"] == "queued"
    thread_id = 141372217677053952
    await asyncpg_pool.execute(
        "UPDATE playtests.meta SET thread_id=$2 WHERE map_id=(SELECT id FROM core.maps WHERE code=$1)",
        official_code,
        thread_id,
    )
    # The queue terminal trigger is the same projection used by the real worker.
    await asyncpg_pool.execute(
        """WITH done AS (DELETE FROM public.pgqueuer WHERE id=(SELECT queue_job_id FROM public.jobs WHERE id=$1) RETURNING *)
        INSERT INTO public.pgqueuer_log(job_id,status,entrypoint,priority) SELECT id,'successful',entrypoint,priority FROM done""",
        parent.id,
    )
    assert (
        await asyncpg_pool.fetchval("SELECT status FROM public.pgqueuer WHERE id=$1", context.queue_job_id) == "queued"
    )
    resumed = await claim_job(asyncpg_pool, child)
    async with asyncpg_pool.acquire() as conn:
        await ensure_ready(conn, resumed)
    handler = QueueContinuations(State({"db_pool": asyncpg_pool}))
    await handler.linked_map(resumed)
    await handler.linked_map(resumed)
    assert (
        await asyncpg_pool.fetchval(
            "SELECT count(*) FROM public.newsfeed WHERE event_type='linked_map' AND payload->>'official_code'=$1",
            official_code,
        )
        == 1
    )
    assert (
        await asyncpg_pool.fetchval(
            "SELECT (payload->>'playtest_id')::bigint FROM public.newsfeed WHERE event_type='linked_map' AND payload->>'official_code'=$1",
            official_code,
        )
        == thread_id
    )


async def test_Q02_tournament_reward_outbox_and_ack_commit_together(
    asyncpg_pool, create_test_user, create_test_map, monkeypatch
):
    from services.tournament_outbox_service import publish_pending_transitions
    from services import base

    user_id = await create_test_user()
    map_id = await create_test_map()
    edition = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.editions(started_at,ends_at,status) VALUES(now()-interval '7 days',now(),'completed') RETURNING id"
    )
    category = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.categories(name,difficulties,placement_xp) VALUES($1,ARRAY['Medium'],'[{\"place\":1,\"xp\":100}]') RETURNING id",
        f"queue-{uuid4()}",
    )
    cycle = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.cycles(edition_id,category_id,map_id,status) VALUES($1,$2,$3,'completed') RETURNING id",
        edition,
        category,
        map_id,
    )
    payload = {
        "edition_id": edition,
        "results": [
            {
                "cycle_id": cycle,
                "category_id": category,
                "standings": [
                    {
                        "rank": 1,
                        "user_id": user_id,
                        "name": "Winner",
                        "time": 10.0,
                        "verified": True,
                        "completion": True,
                    }
                ],
                "winner_user_id": user_id,
            }
        ],
        "started": [],
    }
    source = await asyncpg_pool.fetchval(
        "INSERT INTO tournaments.pending_transitions(edition_id,event_type,payload) VALUES($1,'edition_rollover',$2) RETURNING id",
        edition,
        payload,
    )
    original = base.enqueue_job

    async def failed_rollover(conn, **kwargs):
        if kwargs["event_name"] == "api.tournament.rollover":
            await conn.execute("SELECT 1/0")
        return await original(conn, **kwargs)

    monkeypatch.setattr(base, "enqueue_job", failed_rollover)
    with pytest.raises(Exception, match="division by zero"):
        await publish_pending_transitions(State({"db_pool": asyncpg_pool}))
    assert not await asyncpg_pool.fetchval("SELECT published FROM tournaments.pending_transitions WHERE id=$1", source)
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM lootbox.xp WHERE user_id=$1", user_id) == 0
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM public.jobs") == 0
    monkeypatch.setattr(base, "enqueue_job", original)
    await publish_pending_transitions(State({"db_pool": asyncpg_pool}))
    await publish_pending_transitions(State({"db_pool": asyncpg_pool}))
    assert await asyncpg_pool.fetchval("SELECT published FROM tournaments.pending_transitions WHERE id=$1", source)
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM public.jobs WHERE action='api.xp.grant'") == 1
    assert await asyncpg_pool.fetchval("SELECT count(*) FROM public.jobs WHERE action='api.tournament.rollover'") == 1


async def test_Q08_mastery_uses_current_completions_not_stale_payload(asyncpg_pool, create_test_user):
    from genjishimada_sdk.maps import MapMasteryCreateRequest

    user_id = await create_test_user()
    maps, *_ = guide_services(asyncpg_pool)
    result = await maps.update_mastery(MapMasteryCreateRequest(user_id, "Hanamura", "Prodigy"))
    assert result is not None
    assert result.medal == "Placeholder"
    assert (
        await asyncpg_pool.fetchval("SELECT medal FROM maps.mastery WHERE user_id=$1 AND map_name='Hanamura'", user_id)
        == "Placeholder"
    )
