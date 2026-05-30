"""Integration tests for tournaments.process_cycle_transitions().

These invoke the pg_cron transition function directly via
``SELECT tournaments.process_cycle_transitions()`` (pg_cron is absent in the
test DB, mirroring the store/quest direct-SELECT test pattern). They assert the
full transition state machine, due-cycle detection (weekly=7d / biweekly=14d),
advisory-lock no-op under concurrency, the placement snapshot round-trip into
the SDK structs, the submission-rejection regression guard, and the
missing-pending-cycle edge.
"""

import datetime as dt

import asyncpg
import msgspec
import pytest
from genjishimada_sdk.tournaments import (
    TournamentCompletionCreateRequest,
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
)
from litestar.datastructures import State

from repository.tournaments_repository import TournamentRepository
from services.exceptions.tournaments import CycleNotActiveError
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]

_LOCK_ID = 2025070100  # tournaments.process_cycle_transitions advisory lock (07-01)


def _days_ago(days: int) -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(days=days)


async def _run_transitions(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT tournaments.process_cycle_transitions()")


async def _status(pool: asyncpg.Pool, cycle_id: int) -> str:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT status FROM tournaments.cycles WHERE id = $1", cycle_id)


async def _row(pool: asyncpg.Pool, cycle_id: int) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM tournaments.cycles WHERE id = $1", cycle_id)
        return dict(row)


async def _transitions(pool: asyncpg.Pool, category_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pt.*
            FROM tournaments.pending_transitions pt
            JOIN tournaments.cycles cy ON cy.id = pt.cycle_id
            WHERE cy.category_id = $1
            ORDER BY pt.created_at ASC, pt.id ASC
            """,
            category_id,
        )
        return [dict(r) for r in rows]


async def _count_status(pool: asyncpg.Pool, category_id: int, status: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM tournaments.cycles WHERE category_id = $1 AND status = $2",
            category_id,
            status,
        )


class TestDueDetection:
    """End-time detection accuracy (weekly/biweekly interval math)."""

    async def test_detects_due_cycle(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """Weekly: only the 8-days-old cycle transitions; the 1-day-old stays active."""
        # weekly category
        weekly_cat = await create_test_category(cycle_frequency="weekly")
        overdue_map = await create_test_map()
        recent_map = await create_test_map()
        overdue = await create_test_cycle(weekly_cat, overdue_map, status="active", started_at=_days_ago(8))
        recent = await create_test_cycle(weekly_cat, recent_map, status="active", started_at=_days_ago(1))

        # biweekly category: 8 days old is within the 14d window (stays), 15 days transitions
        biweekly_cat = await create_test_category(cycle_frequency="biweekly")
        bw_within_map = await create_test_map()
        bw_over_map = await create_test_map()
        bw_within = await create_test_cycle(biweekly_cat, bw_within_map, status="active", started_at=_days_ago(8))
        bw_over = await create_test_cycle(biweekly_cat, bw_over_map, status="active", started_at=_days_ago(15))

        await _run_transitions(asyncpg_pool)

        # weekly assertions
        assert await _status(asyncpg_pool, overdue) == "completed"
        assert await _status(asyncpg_pool, recent) == "active"

        # biweekly assertions
        assert await _status(asyncpg_pool, bw_within) == "active"
        assert await _status(asyncpg_pool, bw_over) == "completed"


class TestStateMachine:
    """Transition atomically sets finalizing->completed + promotes pending->active."""

    async def test_transition_state_machine(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """Due active completes; pending promotes to active; a fresh pending is pre-rolled."""
        category = await create_test_category(cycle_frequency="weekly")
        # several eligible maps so the pre-roll has something to pick
        active_map = await create_test_map(difficulty="Medium")
        pending_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")

        active = await create_test_cycle(category, active_map, status="active", started_at=_days_ago(8))
        pending = await create_test_cycle(category, pending_map, status="pending")

        await _run_transitions(asyncpg_pool)

        # original active -> completed with ended_at set
        completed = await _row(asyncpg_pool, active)
        assert completed["status"] == "completed"
        assert completed["ended_at"] is not None

        # previously-pending -> active with a fresh started_at
        promoted = await _row(asyncpg_pool, pending)
        assert promoted["status"] == "active"
        assert promoted["started_at"] is not None

        # a NEW pending cycle exists for the category (pre-roll, D-06)
        assert await _count_status(asyncpg_pool, category, "pending") == 1
        assert await _count_status(asyncpg_pool, category, "active") == 1

        # exactly two transition rows for the completed cycle's category:
        # cycle_completed (for `active`) + cycle_started (for `pending`)
        rows = await _transitions(asyncpg_pool, category)
        event_types = sorted(r["event_type"] for r in rows)
        assert event_types == ["cycle_completed", "cycle_started"]


class TestCompletedPayload:
    """Placement snapshot embedded in cycle_completed payload matches leaderboard ranking."""

    async def test_completed_payload_standings(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
    ):
        """Standings rank verified-above-partial, fastest-first within tier, and round-trip."""
        category = await create_test_category(cycle_frequency="weekly")
        active_map = await create_test_map(difficulty="Medium")
        pending_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")

        active = await create_test_cycle(category, active_map, status="active", started_at=_days_ago(8))
        await create_test_cycle(category, pending_map, status="pending")

        u_fast_verified = await create_test_user()
        u_slow_verified = await create_test_user()
        u_unverified = await create_test_user()

        # verified fast (should be rank 1), verified slow (rank 2), unverified (rank 3)
        await create_test_tournament_completion(active, u_fast_verified, active_map, time=10.0, verified=True)
        await create_test_tournament_completion(active, u_slow_verified, active_map, time=20.0, verified=True)
        await create_test_tournament_completion(active, u_unverified, active_map, time=5.0, verified=False)

        await _run_transitions(asyncpg_pool)

        rows = await _transitions(asyncpg_pool, category)
        completed_rows = [r for r in rows if r["event_type"] == "cycle_completed"]
        started_rows = [r for r in rows if r["event_type"] == "cycle_started"]
        assert len(completed_rows) == 1
        assert len(started_rows) == 1

        payload = completed_rows[0]["payload"]
        standings = payload["standings"]
        # verified users rank above the unverified one; fastest verified first
        assert [s["user_id"] for s in standings] == [u_fast_verified, u_slow_verified, u_unverified]
        assert standings[0]["rank"] == 1
        assert standings[1]["rank"] == 2
        # unverified ranks last (tier below verified) regardless of its faster time
        assert standings[2]["user_id"] == u_unverified
        assert standings[2]["verified"] is False
        assert payload["winner_user_id"] == u_fast_verified

        # round-trip: payload deserializes into the SDK struct (Pitfall 5)
        completed_event = msgspec.convert(payload, TournamentCycleCompletedEvent)
        assert completed_event.cycle_id == active
        assert completed_event.winner_user_id == u_fast_verified
        assert len(completed_event.standings) == 3

        # cycle_started payload round-trips and carries map + timing fields
        started_event = msgspec.convert(started_rows[0]["payload"], TournamentCycleStartedEvent)
        assert started_event.map_code is not None
        assert started_event.map_name is not None
        assert isinstance(started_event.started_at, dt.datetime)
        assert isinstance(started_event.ends_at, dt.datetime)


class TestAdvisoryLock:
    """Advisory-lock concurrency safety (no double transition)."""

    async def test_advisory_lock_concurrency(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A held advisory lock makes the function no-op; the cycle transitions only after release."""
        category = await create_test_category(cycle_frequency="weekly")
        active_map = await create_test_map(difficulty="Medium")
        pending_map = await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")
        active = await create_test_cycle(category, active_map, status="active", started_at=_days_ago(8))
        await create_test_cycle(category, pending_map, status="pending")

        conn_a = await asyncpg_pool.acquire()
        try:
            tx = conn_a.transaction()
            await tx.start()
            # Connection A holds the transaction-level lock.
            await conn_a.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_ID)

            # Connection B's transition no-ops because pg_try_advisory_xact_lock fails.
            await _run_transitions(asyncpg_pool)
            assert await _status(asyncpg_pool, active) == "active"

            # Release A's lock.
            await tx.rollback()
        finally:
            await asyncpg_pool.release(conn_a)

        # Now the transition completes.
        await _run_transitions(asyncpg_pool)
        assert await _status(asyncpg_pool, active) == "completed"


class TestSubmissionRejection:
    """Submissions rejected once status is finalizing/completed (regression guard)."""

    async def test_submission_rejected_during_finalizing(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
    ):
        """submit_completion raises CycleNotActiveError when the cycle is finalizing."""
        category = await create_test_category(cycle_frequency="weekly")
        map_id = await create_test_map(difficulty="Medium")
        cycle = await create_test_cycle(category, map_id, status="finalizing", started_at=_days_ago(1))
        user_id = await create_test_user()

        service = TournamentService(asyncpg_pool, State({}), TournamentRepository(asyncpg_pool))
        request = TournamentCompletionCreateRequest(
            user_id=user_id,
            time=12.34,
            screenshot="https://example.com/s.png",
        )

        with pytest.raises(CycleNotActiveError):
            await service.submit_completion(cycle, request)


class TestMissingPendingEdge:
    """Edge: no pending cycle -> inline select + warning (D-07), run still completes."""

    async def test_missing_pending_cycle_edge(
        self,
        asyncpg_pool: asyncpg.Pool,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        """A due cycle with no pending cycle still completes without erroring."""
        category = await create_test_category(cycle_frequency="weekly")
        active_map = await create_test_map(difficulty="Medium")
        # extra eligible maps so the inline-select / pre-roll can find one
        await create_test_map(difficulty="Medium")
        await create_test_map(difficulty="Medium")
        active = await create_test_cycle(category, active_map, status="active", started_at=_days_ago(8))

        # no pending cycle exists for this category
        assert await _count_status(asyncpg_pool, category, "pending") == 0

        # must not raise
        await _run_transitions(asyncpg_pool)

        # the due cycle is completed; the run finished
        assert await _status(asyncpg_pool, active) == "completed"
