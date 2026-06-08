"""Unit tests for tournaments.next_grid_boundary() (D-06 / D-07).

These invoke the PL/pgSQL helper directly via
``SELECT tournaments.next_grid_boundary($1,$2,$3,$4,$5)`` (the same direct-SELECT
pattern as test_cycle_transitions.py, since pg_cron is absent in the test DB).

The helper computes the next occurrence of an anchor weekday@time-of-day in a
given timezone, stepping one period if the candidate instant is already past.
weekday convention is PostgreSQL EXTRACT(DOW): 0=Sun..6=Sat (A8).

Wave 0 RED scaffold: these FAIL LOUDLY (not skip) until migration 0024 creates
tournaments.next_grid_boundary; the asyncpg call raises UndefinedFunctionError.
"""

import datetime as dt

import asyncpg
import pytest

pytestmark = [pytest.mark.domain_tournaments]


async def _next_boundary(
    pool: asyncpg.Pool,
    p_from: dt.datetime,
    weekday: int,
    tod: dt.time,
    tz: str,
    period: dt.timedelta,
) -> dt.datetime:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT tournaments.next_grid_boundary($1, $2, $3, $4, $5)",
            p_from,
            weekday,
            tod,
            tz,
            period,
        )


class TestNextGridBoundary:
    """next_grid_boundary picks the correct next weekday@time in the anchor tz."""

    async def test_next_monday_midnight_utc(self, asyncpg_pool: asyncpg.Pool):
        """From a Wednesday, the next Monday 00:00 UTC is the upcoming Monday."""
        # 2026-06-03 is a Wednesday (DOW=3).
        p_from = dt.datetime(2026, 6, 3, 12, 0, tzinfo=dt.UTC)
        result = await _next_boundary(
            asyncpg_pool, p_from, 1, dt.time(0, 0), "UTC", dt.timedelta(weeks=1)
        )
        # Next Monday after Wed 2026-06-03 is 2026-06-08 00:00 UTC.
        assert result == dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)

    async def test_steps_one_period_when_candidate_already_past(self, asyncpg_pool: asyncpg.Pool):
        """If today IS the anchor weekday but the time has elapsed, step one period."""
        # 2026-06-08 is a Monday (DOW=1); 12:00 is past the 00:00 anchor.
        p_from = dt.datetime(2026, 6, 8, 12, 0, tzinfo=dt.UTC)
        result = await _next_boundary(
            asyncpg_pool, p_from, 1, dt.time(0, 0), "UTC", dt.timedelta(weeks=1)
        )
        # Same-day Monday 00:00 already passed -> step one week to 2026-06-15.
        assert result == dt.datetime(2026, 6, 15, 0, 0, tzinfo=dt.UTC)

    async def test_same_day_future_time_is_today(self, asyncpg_pool: asyncpg.Pool):
        """If today is the anchor weekday and the time is still ahead, pick today."""
        # 2026-06-08 Monday 00:00, anchor 18:00 same tz -> today 18:00.
        p_from = dt.datetime(2026, 6, 8, 0, 0, tzinfo=dt.UTC)
        result = await _next_boundary(
            asyncpg_pool, p_from, 1, dt.time(18, 0), "UTC", dt.timedelta(weeks=1)
        )
        assert result == dt.datetime(2026, 6, 8, 18, 0, tzinfo=dt.UTC)


class TestNextGridBoundaryDST:
    """grid boundary preserves the wall-clock slot across a DST transition (D-07)."""

    async def test_spring_forward_preserves_wall_clock(self, asyncpg_pool: asyncpg.Pool):
        """Anchor Sunday 00:00 America/Los_Angeles across spring-forward stays 00:00 local.

        2026 US spring-forward is 2026-03-08 (clocks jump 02:00 -> 03:00 PST->PDT).
        Anchoring Sunday 00:00 in LA the week of the transition must land on the
        00:00 *wall-clock* instant, NOT shifted by the offset change.
        """
        # 2026-03-04 is a Wednesday; next Sunday is 2026-03-08 (the DST day).
        p_from = dt.datetime(2026, 3, 4, 12, 0, tzinfo=dt.UTC)
        result = await _next_boundary(
            asyncpg_pool, p_from, 0, dt.time(0, 0), "America/Los_Angeles", dt.timedelta(weeks=1)
        )
        # 2026-03-08 00:00 LA is still PST (offset -08:00) since the jump is at 02:00.
        # 00:00 PST == 08:00 UTC.
        assert result == dt.datetime(2026, 3, 8, 8, 0, tzinfo=dt.UTC)
        # The instant must represent 00:00 wall-clock in LA.
        local = result.astimezone(dt.timezone(dt.timedelta(hours=-8)))
        assert (local.hour, local.minute) == (0, 0)

    async def test_week_after_spring_forward_still_midnight(self, asyncpg_pool: asyncpg.Pool):
        """The Sunday AFTER spring-forward is 00:00 PDT (offset -07:00), still 00:00 local."""
        # 2026-03-09 is the Monday after the DST day; next Sunday is 2026-03-15.
        p_from = dt.datetime(2026, 3, 9, 12, 0, tzinfo=dt.UTC)
        result = await _next_boundary(
            asyncpg_pool, p_from, 0, dt.time(0, 0), "America/Los_Angeles", dt.timedelta(weeks=1)
        )
        # 2026-03-15 00:00 LA is now PDT (offset -07:00). 00:00 PDT == 07:00 UTC.
        assert result == dt.datetime(2026, 3, 15, 7, 0, tzinfo=dt.UTC)
        local = result.astimezone(dt.timezone(dt.timedelta(hours=-7)))
        assert (local.hour, local.minute) == (0, 0)
