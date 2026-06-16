"""Integration tests for the skill-score DASHBOARD endpoints (Phase 14).

Proves the three GET dashboard routes end-to-end against the migrated integration DB
(the ``skill.*`` schema + the 0031 capture tables exist only there):

- ``GET /skill/users/{id}/history?window=…`` — ordered points + summary (Req 1/3/6).
- ``GET /skill/users/{id}/changes?window=…&limit=…&offset=…`` — newest-first feed (Req 4).
- ``GET /skill/users/{id}/changes/{change_id}`` — drill-down with conservation (Req 5).

Each capture row is produced by the SAME single ``_do_recompute`` routine the event /
nightly / PATCH paths use (D-04), driven deterministically here via ``_recompute(pool)``
as the authoritative last-writer (mirroring ``test_skill.py``). For the known-series
anchoring (Req 3) and the five-window filtering (Req 6) — which need rows at precise
``captured_at`` offsets — history rows are inserted DIRECTLY at known timestamps, then
read back through the real HTTP route.

The empty/zero/404 edge behavior (Req 7) is asserted on every endpoint: an empty user
returns 200 with empty points + a zeroed summary on /history, 200 ``[]`` on /changes,
and 404 on /changes/{any} — never a 500. The actor-vs-bystander cause split + SYSTEM
coalescing (Req 2, e2e angle) is asserted from real recompute capture rows.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient

from repository.skill_repository import SkillRepository
from services.skill_service import SkillService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_skill,
]

SKILL = "/api/v3/skill"


async def _recompute(pool: asyncpg.Pool) -> None:
    """Deterministically rebuild the skill snapshot + capture rows via the shared D-04 routine.

    Yields the loop briefly so any in-flight background listener (fired by a preceding
    HTTP call) settles first, THEN runs the SAME ``recompute_all`` on our dedicated test
    pool as the authoritative last-writer. The rebuild is idempotent and not RabbitMQ-gated,
    so the read pipeline is asserted without a timing race (matches ``test_skill.py``).
    """
    await asyncio.sleep(0.1)
    state = type("S", (), {"db_pool": pool})()
    service = SkillService(pool, state, SkillRepository(pool))
    await service.recompute_all()


@pytest.fixture
async def seed(asyncpg_pool: asyncpg.Pool):
    """Factory: create a user / map / a verified-or-pending completion row.

    Seeds directly via the pool (deterministic, bypassing the submit pipeline's
    tournament/OCR side-effects). Returns helper closures the tests compose. Mirrors
    the ``seed`` factory in ``test_skill.py``.
    """

    async def make_user(nickname: str | None = None) -> int:
        uid = int(uuid4().int % 9_000_000_000_000_000) + 100_000_000_000_000_000
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
                uid,
                nickname or f"skill-{uid % 100000}",
                nickname or f"skill-{uid % 100000}",
            )
        return uid

    async def make_map(*, difficulty: str = "Hard", raw: float = 6.5) -> int:
        code = f"S{uuid4().hex[:5].upper()}"
        creator = await make_user()
        async with asyncpg_pool.acquire() as conn:
            map_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, hidden, archived
                )
                VALUES ($1, 'Hanamura', 'Classic', 10, TRUE, 'Approved', $2, $3, FALSE, FALSE)
                RETURNING id
                """,
                code,
                difficulty,
                raw,
            )
            await conn.execute(
                "INSERT INTO maps.creators (map_id, user_id, is_primary) VALUES ($1, $2, TRUE)",
                map_id,
                creator,
            )
        return map_id

    async def make_completion(
        *,
        user_id: int,
        map_id: int,
        time: float,
        verified: bool,
        message_id: int,
        video: bool = True,
    ) -> int:
        async with asyncpg_pool.acquire() as conn:
            return await conn.fetchval(
                """
                INSERT INTO core.completions (
                    map_id, user_id, time, screenshot, video, verified,
                    message_id, completion, legacy
                )
                VALUES ($1, $2, $3, 'https://example.com/s.png', $4, $5, $6, $7, FALSE)
                RETURNING id
                """,
                map_id,
                user_id,
                time,
                "https://youtube.com/watch?v=x" if video else None,
                verified,
                message_id,
                not video,
            )

    return type(
        "Seed",
        (),
        {
            "make_user": staticmethod(make_user),
            "make_map": staticmethod(make_map),
            "make_completion": staticmethod(make_completion),
        },
    )()


async def _insert_history(
    pool: asyncpg.Pool, user_id: int, samples: list[tuple[datetime, float]]
) -> None:
    """Insert known (captured_at, skill_score) history rows directly (Req 3/6 fixtures)."""
    async with pool.acquire() as conn:
        for captured_at, score in samples:
            await conn.execute(
                """
                INSERT INTO skill.score_history (user_id, captured_at, skill_score)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, captured_at) DO UPDATE SET skill_score = EXCLUDED.skill_score
                """,
                user_id,
                captured_at,
                score,
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Req 1 — history capture: >= 2 distinct-captured_at rows after two recomputes
# ---------------------------------------------------------------------------


class TestHistoryCapture:
    """Req 1: every recompute that touches a user appends a forward-only history row."""

    async def test_two_recomputes_yield_two_distinct_captured_at(self, test_client, asyncpg_pool, seed):
        """Two recomputes (field changed between them) → >= 2 history rows, distinct captured_at, forward-only."""
        test_start = _now()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        player_a = await seed.make_user()
        player_b = await seed.make_user()

        # B verified (sole run); A pending (faster) — verifying A later shifts the field.
        await seed.make_completion(
            user_id=player_b, map_id=map_id, time=50.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )
        msg_a = int(uuid4().int % 9_000_000_000)
        await seed.make_completion(
            user_id=player_a, map_id=map_id, time=20.0, verified=False, message_id=msg_a
        )
        completion_a = await asyncpg_pool.fetchval(
            "SELECT id FROM core.completions WHERE message_id = $1", msg_a
        )

        await _recompute(asyncpg_pool)
        # Change the field: verify A (faster) → B's score moves → second capture differs.
        verify = await test_client.put(
            f"/api/v3/completions/{completion_a}/verification",
            json={"verified": True, "verified_by": player_a, "reason": None},
        )
        assert verify.status_code == 200
        # A small delay ensures the two recomputes mint distinct captured_at timestamps.
        await asyncio.sleep(0.01)
        await _recompute(asyncpg_pool)

        rows = await asyncpg_pool.fetch(
            "SELECT captured_at FROM skill.score_history WHERE user_id = $1 ORDER BY captured_at ASC",
            player_b,
        )
        captured = [r["captured_at"] for r in rows]
        # Req 1: at least two history rows after two recomputes.
        assert len(captured) >= 2
        # Distinct captured_at across recomputes.
        assert len(set(captured)) == len(captured)
        # Forward-only: no row predates the test start.
        assert all(c >= test_start for c in captured)


# ---------------------------------------------------------------------------
# Req 3 — history + summary anchoring + invalid window + empty user
# ---------------------------------------------------------------------------


class TestHistorySummary:
    """Req 3: known-series best/lowest/average + first-vs-last point/percent change."""

    async def test_known_series_summary(self, test_client, asyncpg_pool, seed):
        """A known in-window series yields correct best/lowest/average + point/percent change."""
        user_id = await seed.make_user()
        base = _now()
        # Oldest → newest within 30d: first=10, last=40, best=40, lowest=10, avg=(10+30+40)/3.
        samples = [
            (base - timedelta(days=25), 10.0),
            (base - timedelta(days=15), 30.0),
            (base - timedelta(days=5), 40.0),
        ]
        await _insert_history(asyncpg_pool, user_id, samples)

        resp = await test_client.get(f"{SKILL}/users/{user_id}/history", params={"window": "30d"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["points"]) == 3
        # Oldest-first ordering.
        assert [p["skill_score"] for p in body["points"]] == [10.0, 30.0, 40.0]
        summary = body["summary"]
        # point_change = last - first = 40 - 10 = 30; percent = 30/10*100 = 300.
        assert math.isclose(summary["point_change"], 30.0, abs_tol=1e-6)
        assert math.isclose(summary["percent_change"], 300.0, abs_tol=1e-6)
        assert math.isclose(summary["best"]["score"], 40.0, abs_tol=1e-6)
        assert math.isclose(summary["lowest"]["score"], 10.0, abs_tol=1e-6)
        assert math.isclose(summary["average"], (10.0 + 30.0 + 40.0) / 3.0, abs_tol=1e-6)
        assert summary["best"]["date"] is not None
        assert summary["lowest"]["date"] is not None

    async def test_invalid_window_rejected(self, test_client, seed):
        """An unknown window value is rejected at decode (4xx), never interpolated into SQL (T-14-13)."""
        user_id = await seed.make_user()
        resp = await test_client.get(f"{SKILL}/users/{user_id}/history", params={"window": "bogus"})
        assert resp.status_code >= 400

    async def test_empty_user_history_zero(self, test_client, seed):
        """A user with no history → 200 with empty points + an all-zero summary (Req 7, never 500)."""
        empty = await seed.make_user()
        resp = await test_client.get(f"{SKILL}/users/{empty}/history", params={"window": "all"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["points"] == []
        summary = body["summary"]
        assert summary["point_change"] == 0.0
        assert summary["percent_change"] == 0.0
        assert summary["best"]["score"] == 0.0
        assert summary["best"]["date"] is None
        assert summary["lowest"]["score"] == 0.0
        assert summary["lowest"]["date"] is None
        assert summary["average"] == 0.0


# ---------------------------------------------------------------------------
# Req 4 — change feed: descending, limit-bounded, window-respected, empty
# ---------------------------------------------------------------------------


class TestChangeFeed:
    """Req 4: newest-first paginated feed; limit bounds; window respected; empty → []."""

    async def test_feed_descending_and_limit(self, test_client, asyncpg_pool, seed):
        """The feed is newest-first by captured_at and bounded by the limit param."""
        user_id = await seed.make_user()
        base = _now()
        # Insert several change rows at known (descending) captured_at.
        async with asyncpg_pool.acquire() as conn:
            for i in range(5):
                await conn.execute(
                    """
                    INSERT INTO skill.score_change
                        (user_id, captured_at, previous_score, new_score, delta, cause_category, reason, diff)
                    VALUES ($1, $2, $3, $4, $5, 'SYSTEM', 'global recalculation', '{}'::jsonb)
                    """,
                    user_id,
                    base - timedelta(minutes=i),
                    float(i),
                    float(i + 1),
                    1.0,
                )

        resp = await test_client.get(f"{SKILL}/users/{user_id}/changes", params={"window": "all"})
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 5
        captured = [datetime.fromisoformat(r["captured_at"]) for r in rows]
        # Req 4: descending by captured_at (newest first).
        assert captured == sorted(captured, reverse=True)

        # limit bounds the page size.
        limited = await test_client.get(
            f"{SKILL}/users/{user_id}/changes", params={"window": "all", "limit": 2}
        )
        assert limited.status_code == 200
        assert len(limited.json()) == 2

    async def test_feed_window_respected(self, test_client, asyncpg_pool, seed):
        """A 7d window excludes a change captured 60 days ago."""
        user_id = await seed.make_user()
        base = _now()
        async with asyncpg_pool.acquire() as conn:
            for offset_days in (2, 60):
                await conn.execute(
                    """
                    INSERT INTO skill.score_change
                        (user_id, captured_at, previous_score, new_score, delta, cause_category, reason, diff)
                    VALUES ($1, $2, 1.0, 2.0, 1.0, 'SYSTEM', 'global recalculation', '{}'::jsonb)
                    """,
                    user_id,
                    base - timedelta(days=offset_days),
                )

        seven_day = await test_client.get(f"{SKILL}/users/{user_id}/changes", params={"window": "7d"})
        assert seven_day.status_code == 200
        assert len(seven_day.json()) == 1  # only the 2-days-ago row is in-window

        all_window = await test_client.get(f"{SKILL}/users/{user_id}/changes", params={"window": "all"})
        assert all_window.status_code == 200
        assert len(all_window.json()) == 2  # all returns both

    async def test_empty_user_feed(self, test_client, seed):
        """A user with no changes → 200 [] (Req 7, never 500)."""
        empty = await seed.make_user()
        resp = await test_client.get(f"{SKILL}/users/{empty}/changes", params={"window": "all"})
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Req 5 — drill-down conservation + IDOR 404
# ---------------------------------------------------------------------------


class TestChangeDetailConservation:
    """Req 5: sum(main_causes.impact) + other_factors == delta within 1e-6; foreign id → 404."""

    async def test_conservation_from_real_recompute(self, test_client, asyncpg_pool, seed):
        """From a real recompute, EVERY captured change row conserves: Σ impact + other_factors == delta.

        Conservation is a per-row invariant of ``_build_diff`` (``Σ impact == delta`` by
        construction, D-04), so it holds for every ``skill.score_change`` row this user owns —
        independent of which recompute (mine or a sibling test's global rebuild on the shared
        DB) produced it. Asserting it on ALL of the user's rows (read through the real HTTP
        drill-down route) is therefore race-free.
        """
        user_id = await seed.make_user()
        # A single map keeps the diff a clean per-map entry (the seed factory's maps all share
        # the display name "Hanamura", which the breakdown join keys on — multiple maps would
        # collapse, exercising a scorer edge unrelated to the route under test).
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        await seed.make_completion(
            user_id=user_id, map_id=map_id, time=20.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )
        await _recompute(asyncpg_pool)

        change_ids = [
            r["change_id"]
            for r in await asyncpg_pool.fetch(
                "SELECT change_id FROM skill.score_change WHERE user_id = $1", user_id
            )
        ]
        assert change_ids, "expected at least one change row from the recompute"

        for change_id in change_ids:
            detail = await test_client.get(f"{SKILL}/users/{user_id}/changes/{change_id}")
            assert detail.status_code == 200
            body = detail.json()
            impact_sum = sum(float(c["impact"]) for c in body["main_causes"]) + float(body["other_factors"])
            # Req 5 / D-07: exact conservation (residual IS the untruncated tail).
            assert math.isclose(impact_sum, float(body["delta"]), abs_tol=1e-6), change_id

    async def test_foreign_change_id_404(self, test_client, asyncpg_pool, seed):
        """A change_id belonging to another user (queried under user_id) returns 404 (T-14-06 IDOR)."""
        owner = await seed.make_user()
        other = await seed.make_user()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        await seed.make_completion(
            user_id=owner, map_id=map_id, time=20.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )
        await _recompute(asyncpg_pool)

        change_id = await asyncpg_pool.fetchval(
            "SELECT change_id FROM skill.score_change WHERE user_id = $1 LIMIT 1", owner
        )
        assert change_id is not None
        # The owner can read it.
        owner_resp = await test_client.get(f"{SKILL}/users/{owner}/changes/{change_id}")
        assert owner_resp.status_code == 200
        # Another user requesting the SAME real change_id → 404 (no existence confirmation).
        foreign = await test_client.get(f"{SKILL}/users/{other}/changes/{change_id}")
        assert foreign.status_code == 404
        # A non-existent change_id → also 404.
        missing = await test_client.get(f"{SKILL}/users/{owner}/changes/999999999")
        assert missing.status_code == 404


# ---------------------------------------------------------------------------
# Req 6 — five-window in-range filtering + `all` full + unknown → 4xx
# ---------------------------------------------------------------------------


class TestWindows:
    """Req 6: each window returns only in-range points; `all` returns every row; unknown → 4xx."""

    async def test_five_windows_filter_in_range(self, test_client, asyncpg_pool, seed):
        """History rows at 3d/20d/60d/200d/400d ago filter correctly per window."""
        user_id = await seed.make_user()
        base = _now()
        offsets_days = [3, 20, 60, 200, 400]
        samples = [(base - timedelta(days=d), float(100 - d)) for d in offsets_days]
        await _insert_history(asyncpg_pool, user_id, samples)

        # window → expected count of in-range points.
        expected = {
            "7d": 1,  # 3d
            "30d": 2,  # 3d, 20d
            "90d": 3,  # 3d, 20d, 60d
            "1y": 4,  # 3d, 20d, 60d, 200d
            "all": 5,  # everything
        }
        for window, count in expected.items():
            resp = await test_client.get(f"{SKILL}/users/{user_id}/history", params={"window": window})
            assert resp.status_code == 200, window
            assert len(resp.json()["points"]) == count, window

    async def test_unknown_window_rejected(self, test_client, seed):
        """An unknown window literal → 4xx (msgspec decode rejection)."""
        user_id = await seed.make_user()
        resp = await test_client.get(f"{SKILL}/users/{user_id}/history", params={"window": "5d"})
        assert resp.status_code >= 400


# ---------------------------------------------------------------------------
# Req 7 — empty/zero/404, never 500 across all three endpoints
# ---------------------------------------------------------------------------


class TestEmptyUserNever500:
    """Req 7: an empty user → 200 empty/zero on /history, 200 [] on /changes, 404 on drill-down."""

    async def test_all_endpoints_empty_user(self, test_client, seed):
        """No endpoint returns 500 for a user with no snapshot/history/changes."""
        empty = await seed.make_user()

        history = await test_client.get(f"{SKILL}/users/{empty}/history", params={"window": "all"})
        assert history.status_code == 200
        assert history.json()["points"] == []

        changes = await test_client.get(f"{SKILL}/users/{empty}/changes", params={"window": "all"})
        assert changes.status_code == 200
        assert changes.json() == []

        detail = await test_client.get(f"{SKILL}/users/{empty}/changes/12345")
        assert detail.status_code == 404

        for resp in (history, changes, detail):
            assert resp.status_code != 500


# ---------------------------------------------------------------------------
# Req 2 (e2e angle) — actor PLAYER_ACTION vs bystander MAP_ENVIRONMENT; SYSTEM coalesced
# ---------------------------------------------------------------------------


class TestCauseAttributionEndToEnd:
    """Req 2 (end-to-end): the verify of user X's run tags X PLAYER_ACTION, bystander MAP_ENVIRONMENT.

    Service-level cause coverage lives in ``test_skill_service.py`` (Plan 04); this is the
    end-to-end angle reading the captured ``skill.score_change`` rows after a real recompute.
    """

    async def test_actor_player_action_bystander_map_environment(self, test_client, asyncpg_pool, seed):
        """Verifying A's run via the recompute descriptor tags A PLAYER_ACTION; bystander B MAP_ENVIRONMENT."""
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        player_a = await seed.make_user()
        player_b = await seed.make_user()
        # B verified (sole run) so B has a snapshot/score before A's verify shifts the field.
        await seed.make_completion(
            user_id=player_b, map_id=map_id, time=50.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )
        await seed.make_completion(
            user_id=player_a, map_id=map_id, time=20.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )

        # Drive a single-actor PLAYER_ACTION recompute on the test pool (A is the actor).
        from services.skill_service import TriggerDescriptor

        state = type("S", (), {"db_pool": asyncpg_pool})()
        service = SkillService(asyncpg_pool, state, SkillRepository(asyncpg_pool))
        await service.recompute_all()  # baseline snapshot
        await asyncio.sleep(0.01)
        await service.recompute_all(
            TriggerDescriptor(cause_category="PLAYER_ACTION", actor_user_id=player_a)
        )

        a_cause = await asyncpg_pool.fetchval(
            "SELECT cause_category FROM skill.score_change WHERE user_id = $1 ORDER BY captured_at DESC LIMIT 1",
            player_a,
        )
        b_cause = await asyncpg_pool.fetchval(
            "SELECT cause_category FROM skill.score_change WHERE user_id = $1 ORDER BY captured_at DESC LIMIT 1",
            player_b,
        )
        # Req 2: actor → PLAYER_ACTION; bystander-with-data → MAP_ENVIRONMENT.
        assert a_cause == "PLAYER_ACTION"
        assert b_cause == "MAP_ENVIRONMENT"

    async def test_system_coalesced_global_recalculation(self, test_client, asyncpg_pool, seed):
        """A SYSTEM-tagged recompute tags every user-with-data SYSTEM 'global recalculation' (D-09)."""
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        user_id = await seed.make_user()
        await seed.make_completion(
            user_id=user_id, map_id=map_id, time=20.0, verified=True, message_id=int(uuid4().int % 9_000_000_000)
        )

        from services.skill_service import TriggerDescriptor

        state = type("S", (), {"db_pool": asyncpg_pool})()
        service = SkillService(asyncpg_pool, state, SkillRepository(asyncpg_pool))
        await service.recompute_all()  # baseline
        await asyncio.sleep(0.01)
        await service.recompute_all(TriggerDescriptor(cause_category="SYSTEM"))

        row = await asyncpg_pool.fetchrow(
            """
            SELECT cause_category, reason FROM skill.score_change
            WHERE user_id = $1 ORDER BY captured_at DESC LIMIT 1
            """,
            user_id,
        )
        assert row is not None
        assert row["cause_category"] == "SYSTEM"
        assert row["reason"] == "global recalculation"
