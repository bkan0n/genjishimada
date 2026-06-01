"""Real-DB integration tests for the tournament rewards engine (08-03).

These drive the two wired hook points end-to-end against a real database:

- Participation XP attaches to the tournament VERIFY path (11-02/11-03 D-04a/D-06)
  and is exercised here by submitting a normal completion on the active cycle's
  map (auto-detected, recorded unverified) and then hitting the verify endpoint.
- Placement + streak rewards and the non-participant reset sweep attach to
  ``publish_pending_transitions`` for ``cycle_completed`` rows (08-03 Task 2),
  driven here by seeding a ``cycle_completed`` pending_transitions row and calling
  the poller directly (the 07-03 pattern).

No live broker is required: ``BaseService.publish_message`` is monkeypatched (the
same effect as the documented ``X-PYTEST-ENABLED=1`` skip) so every grant's
``api.xp.grant`` publish and the outbox publish are no-ops. Assertions read
``tournaments.xp_grants`` (the ledger), ``tournaments.streaks``, and ``lootbox.xp``.

The session/xdist-shared DB means other tests may add rows; assertions use
membership/property checks (e.g. a specific user's streak, a per-cycle ledger
count), never global totals.
"""

import json
from uuid import uuid4

import pytest
from litestar.datastructures import State

import services.base as base_module
from services.tournament_outbox_service import publish_pending_transitions

pytestmark = [pytest.mark.integration, pytest.mark.domain_tournaments]

BASE = "/api/v3/tournaments"


def _stub_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip every RabbitMQ publish (outbox publish + inner api.xp.grant publish)."""
    from uuid import uuid4 as _uuid4

    from genjishimada_sdk.internal import JobStatusResponse

    async def _fake_publish(self, *, routing_key, data, headers, idempotency_key=None):  # noqa: ANN001
        return JobStatusResponse(_uuid4(), "succeeded")

    monkeypatch.setattr(base_module.BaseService, "publish_message", _fake_publish)


async def _seed_category(
    asyncpg_pool,
    *,
    participation_xp: int = 0,
    placement_xp: list[dict] | None = None,
    streak_xp: list[dict] | None = None,
) -> int:
    """Insert a tournaments.categories row with reward config; return its id."""
    async with asyncpg_pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO tournaments.categories
                (name, difficulties, participation_xp, placement_xp, streak_xp)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            RETURNING id
            """,
            f"Rewards {uuid4().hex[:10]}",
            ["Easy"],
            participation_xp,
            json.dumps(placement_xp or []),
            json.dumps(streak_xp or []),
        )


async def _seed_cycle(asyncpg_pool, category_id: int, map_id: int, *, status: str = "completed") -> int:
    """Insert a cycle (completed by default) for the category/map; return its id."""
    async with asyncpg_pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO tournaments.cycles (category_id, map_id, status, started_at, ended_at)
            VALUES ($1, $2, $3, NOW() - INTERVAL '7 days', NOW())
            RETURNING id
            """,
            category_id,
            map_id,
            status,
        )


async def _seed_completion(asyncpg_pool, cycle_id: int, user_id: int, map_id: int, time: float) -> None:
    """Insert a tournament completion (makes the user a cycle participant)."""
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot)
            VALUES ($1, $2, $3, $4, $5)
            """,
            cycle_id,
            user_id,
            map_id,
            time,
            "https://example.com/s.png",
        )


async def _seed_completed_transition(asyncpg_pool, cycle_id: int, category_id: int, standings: list[dict]) -> int:
    """Seed an edition_rollover pending_transitions row the poller will pick up.

    Migration 0024 collapsed cycle_completed into a combined edition_rollover row
    (D-09); the per-cycle completed payload now lives in the rollover's
    ``results`` list (one entry per child cycle). The poller drives the reward
    side-effects per results entry, keyed on cycle_id (Pattern 4), so this still
    exercises the same award/streak/ledger path. A throwaway edition supplies the
    nullable edition_id FK + the edition-scoped idempotency key.
    """
    completed_entry = {
        "cycle_id": cycle_id,
        "category_id": category_id,
        "standings": standings,
        "winner_user_id": standings[0]["user_id"] if standings else None,
    }
    payload = json.dumps({"edition_id": None, "results": [completed_entry], "started": []})
    async with asyncpg_pool.acquire() as conn:
        edition_id = await conn.fetchval(
            """
            INSERT INTO tournaments.editions (started_at, ends_at, status)
            VALUES (NOW() - INTERVAL '7 days', NOW(), 'completed')
            RETURNING id
            """
        )
        # edition_id must be in the payload too (idempotency key source) -- patch it in.
        payload = json.dumps({"edition_id": edition_id, "results": [completed_entry], "started": []})
        return await conn.fetchval(
            """
            INSERT INTO tournaments.pending_transitions (cycle_id, edition_id, event_type, payload)
            VALUES (NULL, $1, 'edition_rollover', $2::jsonb)
            RETURNING id
            """,
            edition_id,
            payload,
        )


async def _clear_unpublished_except(asyncpg_pool, cycle_id: int) -> None:
    """Drop any orphaned unpublished outbox rows so the poll batch is just ours.

    The shared DB can carry an unpublishable poison row from another outbox test
    that would make the poll raise before reaching our edition_rollover row. Our
    rollover row carries cycle_id NULL and references our cycle inside
    payload->'results'; keep only rows whose results contain our cycle_id and drop
    everything else still unpublished.
    """
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM tournaments.pending_transitions
            WHERE published = FALSE
              AND NOT (payload->'results' @> jsonb_build_array(jsonb_build_object('cycle_id', $1::int)))
            """,
            cycle_id,
        )


def _standing(rank: int, user_id: int) -> dict:
    return {
        "rank": rank,
        "user_id": user_id,
        "name": f"User{user_id}",
        "time": 10.0 + rank,
        "verified": True,
        "completion": True,
    }


async def _grant_count(asyncpg_pool, cycle_id: int) -> int:
    async with asyncpg_pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM tournaments.xp_grants WHERE cycle_id = $1",
            cycle_id,
        )


async def _streak(asyncpg_pool, user_id: int) -> int | None:
    async with asyncpg_pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT current_streak FROM tournaments.streaks WHERE user_id = $1",
            user_id,
        )


async def _xp_amount(asyncpg_pool, user_id: int) -> int:
    async with asyncpg_pool.acquire() as conn:
        amount = await conn.fetchval("SELECT amount FROM lootbox.xp WHERE user_id = $1", user_id)
        return amount or 0


class TestParticipationGrant:
    """RWD-01: participation XP is granted on VERIFY (D-04a/D-06), never on the unverified submit."""

    async def test_submit_then_verify_grants_participation_once(
        self, test_client, asyncpg_pool, monkeypatch, create_test_map, create_test_user
    ):
        """A normal completion on the cycle map records an unverified row (no XP); verifying grants it once."""
        _stub_publish(monkeypatch)

        category_id = await _seed_category(asyncpg_pool, participation_xp=25)
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"Part{uuid4().hex[:6]}")
        cycle_id = await _seed_cycle(asyncpg_pool, category_id, map_id, status="active")

        async with asyncpg_pool.acquire() as conn:
            map_code = await conn.fetchval("SELECT code FROM core.maps WHERE id = $1", map_id)

        # Auto-detected tournament submission via the verified pipeline: recorded UNVERIFIED, no XP yet.
        submit = await test_client.post(
            "/api/v3/completions/",
            json={
                "user_id": user_id,
                "code": map_code,
                "time": 50.0,
                "video": None,
                "screenshot": "https://example.com/s.png",
            },
        )
        assert submit.status_code == 201
        assert await _grant_count(asyncpg_pool, cycle_id) == 0
        assert await _xp_amount(asyncpg_pool, user_id) == 0

        async with asyncpg_pool.acquire() as conn:
            tc_id = await conn.fetchval(
                "SELECT id FROM tournaments.completions WHERE cycle_id = $1 AND user_id = $2",
                cycle_id,
                user_id,
            )

        # Verifying the tournament row grants participation XP exactly once (ledger idempotent).
        first_verify = await test_client.patch(f"{BASE}/completions/{tc_id}/verify")
        assert first_verify.status_code == 200
        assert await _grant_count(asyncpg_pool, cycle_id) == 1
        assert await _xp_amount(asyncpg_pool, user_id) == 25

        second_verify = await test_client.patch(f"{BASE}/completions/{tc_id}/verify")
        assert second_verify.status_code == 200
        assert await _grant_count(asyncpg_pool, cycle_id) == 1
        assert await _xp_amount(asyncpg_pool, user_id) == 25


class TestStreakIncrementAndReset:
    """RWD-04: streaks increment for participants and reset to 0 for non-participants."""

    async def test_participant_streak_increments(
        self, asyncpg_pool, monkeypatch, create_test_map, create_test_user
    ):
        """A cycle participant's current_streak increments after cycle_completed processing."""
        _stub_publish(monkeypatch)

        category_id = await _seed_category(asyncpg_pool)
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"Streak{uuid4().hex[:6]}")
        cycle_id = await _seed_cycle(asyncpg_pool, category_id, map_id)
        await _seed_completion(asyncpg_pool, cycle_id, user_id, map_id, 42.0)
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, user_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)

        await publish_pending_transitions(State({"db_pool": asyncpg_pool}))

        assert await _streak(asyncpg_pool, user_id) == 1

    async def test_non_participant_streak_resets_to_zero(
        self, asyncpg_pool, monkeypatch, create_test_map, create_test_user
    ):
        """A tracked user who did NOT submit this cycle has current_streak reset to 0."""
        _stub_publish(monkeypatch)

        category_id = await _seed_category(asyncpg_pool)
        map_id = await create_test_map(difficulty="Easy")
        participant_id = await create_test_user(nickname=f"P{uuid4().hex[:6]}")
        absent_id = await create_test_user(nickname=f"A{uuid4().hex[:6]}")
        cycle_id = await _seed_cycle(asyncpg_pool, category_id, map_id)

        # Seed the absent user with a pre-existing positive streak; they do NOT submit.
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.streaks (user_id, current_streak, max_streak)
                VALUES ($1, 3, 3)
                """,
                absent_id,
            )

        await _seed_completion(asyncpg_pool, cycle_id, participant_id, map_id, 42.0)
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, participant_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)

        await publish_pending_transitions(State({"db_pool": asyncpg_pool}))

        assert await _streak(asyncpg_pool, participant_id) == 1
        assert await _streak(asyncpg_pool, absent_id) == 0


class TestMultiCategoryDedupe:
    """RWD-04: the global streak increments once per cycle window, not per category."""

    async def test_streak_increments_once_for_same_cycle(
        self, asyncpg_pool, monkeypatch, create_test_map, create_test_user
    ):
        """Processing the same cycle_completed event twice still leaves current_streak == 1.

        advance_streak's ``last_cycle_id IS DISTINCT FROM`` guard means a second
        advance for the SAME cycle (the multi-category / replay window) does not
        double-increment.
        """
        _stub_publish(monkeypatch)

        category_id = await _seed_category(asyncpg_pool)
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"Dedupe{uuid4().hex[:6]}")
        cycle_id = await _seed_cycle(asyncpg_pool, category_id, map_id)
        await _seed_completion(asyncpg_pool, cycle_id, user_id, map_id, 42.0)
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, user_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)

        state = State({"db_pool": asyncpg_pool})
        await publish_pending_transitions(state)
        assert await _streak(asyncpg_pool, user_id) == 1

        # Re-seed + re-run the SAME cycle's finalization: the dedupe guard holds.
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, user_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)
        await publish_pending_transitions(state)

        assert await _streak(asyncpg_pool, user_id) == 1


class TestDoubleGrantReplaySafe:
    """RWD ledger guard end-to-end: replaying cycle_completed grants no duplicate XP."""

    async def test_replay_grants_no_duplicate_xp(
        self, asyncpg_pool, monkeypatch, create_test_map, create_test_user
    ):
        """A second publish_pending_transitions over the same cycle adds no ledger rows or XP."""
        _stub_publish(monkeypatch)

        category_id = await _seed_category(
            asyncpg_pool,
            placement_xp=[{"place": 1, "xp": 100}],
            streak_xp=[{"threshold": 1, "xp": 50}],
        )
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"Replay{uuid4().hex[:6]}")
        cycle_id = await _seed_cycle(asyncpg_pool, category_id, map_id)
        await _seed_completion(asyncpg_pool, cycle_id, user_id, map_id, 42.0)
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, user_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)

        state = State({"db_pool": asyncpg_pool})
        await publish_pending_transitions(state)

        grants_after_first = await _grant_count(asyncpg_pool, cycle_id)
        xp_after_first = await _xp_amount(asyncpg_pool, user_id)
        # rank-1 placement (100) + streak threshold 1 (50) = two ledger rows, 150 XP.
        assert grants_after_first == 2
        assert xp_after_first == 150

        # Replay the SAME cycle_completed row: the ledger short-circuits every grant.
        await _seed_completed_transition(asyncpg_pool, cycle_id, category_id, [_standing(1, user_id)])
        await _clear_unpublished_except(asyncpg_pool, cycle_id)
        await publish_pending_transitions(state)

        assert await _grant_count(asyncpg_pool, cycle_id) == grants_after_first
        assert await _xp_amount(asyncpg_pool, user_id) == xp_after_first
