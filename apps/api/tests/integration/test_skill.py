"""Integration tests for the skill-score freshness/removal contract + leaderboard.

This file proves the Phase 13 acceptance matrix end-to-end against the migrated
integration DB (the ``skill.*`` schema exists only there). It exercises the real
verify / reject / suspicious-flag HTTP endpoints (which emit
``skill.recompute.requested`` post-commit, plan 13-06 Task 1) and the community
leaderboard ``skill_score`` column (Task 2), driving the deterministic snapshot
rebuild via the in-process ``SkillService.recompute_all`` (D-04, NOT RabbitMQ-gated,
so ``X-PYTEST-ENABLED=1`` does not gate it).

Each assertion is mapped to its SPEC acceptance criterion (req 6/7/8/9) in a comment.

Covered behaviors (SPEC AC):
- Verify raises a submitter's score AND shifts a second player on the same map (req 8).
- Rejecting a previously-verified run returns the score to its pre-verify value (req 9).
- Suspicious-flagging a user drops their skill score to 0 (req 9).
- GET /community/leaderboard?sort=skill_score is descending + paginated; skill_rank
  is unchanged (req 6).
- A zero-eligible player shows skill_score 0 ranked last; GET /skill/users/{id}
  returns 0 with an empty breakdown (req 6/7, D-07).
- PATCH /skill/config: 401/403 for a non-superuser, 200 for a superuser, scores
  change after (req 7, D-10).
- GET /skill/users/{id}/breakdown contributions sum to the score total (req 7).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import pytest
from genjishimada_sdk.skill import SKILL_TIER_NAMES
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pytest_databases.docker.postgres import PostgresService

from repository.skill_repository import SkillRepository
from services.skill_service import SkillService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_skill,
]

SKILL = "/api/v3/skill"
COMMUNITY = "/api/v3/community"


def _dsn(svc: PostgresService) -> str:
    return f"postgresql://{svc.user}:{svc.password}@{svc.host}:{svc.port}/{svc.database}"


async def _recompute(pool: asyncpg.Pool) -> None:
    """Deterministically rebuild the skill snapshot via the shared D-04 routine.

    The verify/reject/flag endpoints emit ``skill.recompute.requested`` as a
    fire-and-forget in-process event whose background listener runs on the app's
    OWN pool — which the ``AsyncTestClient`` may have already released, producing a
    logged (non-fatal) listener error. We yield the loop briefly so that
    best-effort background recompute settles first, THEN run the SAME
    ``recompute_all`` routine on our dedicated test pool as the authoritative,
    last-writer rebuild. The rebuild is idempotent and not RabbitMQ-gated, so this
    asserts the read/column pipeline deterministically without a timing race.
    """
    # Let any in-flight background listener (fired by the preceding HTTP call)
    # finish before we take the authoritative snapshot.
    await asyncio.sleep(0.1)
    state = type("S", (), {"db_pool": pool})()
    service = SkillService(pool, state, SkillRepository(pool))
    await service.recompute_all()


@pytest.fixture
async def seed(asyncpg_pool: asyncpg.Pool):
    """Factory: create a user / map / a verified-or-pending completion row.

    Seeds directly via the pool (deterministic, bypassing the submit pipeline's
    tournament/OCR side-effects). Returns helper closures the tests compose.
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
                # completion=FALSE => a fully verified (video) run in the scorer's
                # eligibility model; the input query gates proof multipliers on it.
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


async def _score(client: AsyncTestClient[Litestar], user_id: int) -> float:
    resp = await client.get(f"{SKILL}/users/{user_id}")
    assert resp.status_code == 200
    return float(resp.json()["skill_score"])


# ---------------------------------------------------------------------------
# req 8 / req 9 — symmetric add/remove freshness + field relativity
# ---------------------------------------------------------------------------


class TestVerifyRejectFlagFreshness:
    """The verify -> reject -> flag symmetric-removal contract (SPEC req 8/9)."""

    async def test_verify_raises_and_reject_restores(self, test_client, asyncpg_pool, seed):
        """Verifying raises the score; rejecting returns it to the pre-verify value (req 9)."""
        user_id = await seed.make_user()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        msg_id = int(uuid4().int % 9_000_000_000)
        await seed.make_completion(
            user_id=user_id, map_id=map_id, time=30.0, verified=False, message_id=msg_id
        )
        completion_id = await asyncpg_pool.fetchval(
            "SELECT id FROM core.completions WHERE message_id = $1", msg_id
        )

        # Pre-verification: a pending run is not eligible -> score 0 (req 9 baseline).
        await _recompute(asyncpg_pool)
        pre_score = await _score(test_client, user_id)
        assert pre_score == 0.0

        # Verify via the real endpoint (emits skill.recompute.requested post-commit).
        verify = await test_client.put(
            f"/api/v3/completions/{completion_id}/verification",
            json={"verified": True, "verified_by": user_id, "reason": None},
        )
        assert verify.status_code == 200
        await _recompute(asyncpg_pool)
        verified_score = await _score(test_client, user_id)
        # req 8: verifying a pending run raises the submitter's score on the next read.
        assert verified_score > pre_score

        # Reject (un-verify) via the same endpoint (symmetric removal).
        reject = await test_client.put(
            f"/api/v3/completions/{completion_id}/verification",
            json={"verified": False, "verified_by": user_id, "reason": "rejected"},
        )
        assert reject.status_code == 200
        await _recompute(asyncpg_pool)
        rejected_score = await _score(test_client, user_id)
        # req 9: rejecting returns the score to its pre-verification value (float tolerance).
        assert math.isclose(rejected_score, pre_score, abs_tol=1e-6)

    async def test_moderate_verify_change_refreshes_score(self, test_client, asyncpg_pool, seed):
        """Moderation verify/un-verify is a fifth state-change path and refreshes the score (CR-01, req 8/9).

        Mirrors ``test_verify_raises_and_reject_restores`` but drives the verify flip
        through ``PUT /completions/{id}/moderate`` (the moderation endpoint) instead
        of the verification endpoint, proving ``moderate_completion`` now emits
        ``skill.recompute.requested`` (the snapshot no longer waits for the nightly backstop).
        """
        user_id = await seed.make_user()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        msg_id = int(uuid4().int % 9_000_000_000)
        await seed.make_completion(
            user_id=user_id, map_id=map_id, time=30.0, verified=False, message_id=msg_id
        )
        completion_id = await asyncpg_pool.fetchval(
            "SELECT id FROM core.completions WHERE message_id = $1", msg_id
        )

        # Pre-moderation: a pending run is not eligible -> score 0 (req 9 baseline).
        await _recompute(asyncpg_pool)
        pre_score = await _score(test_client, user_id)
        assert pre_score == 0.0

        # Verify via the MODERATION endpoint (emits skill.recompute.requested post-commit, CR-01).
        verify = await test_client.put(
            f"/api/v3/completions/{completion_id}/moderate",
            json={"moderated_by": user_id, "verified": True},
        )
        assert verify.status_code == 200
        await _recompute(asyncpg_pool)
        verified_score = await _score(test_client, user_id)
        # req 8: moderation-verifying a pending run raises the submitter's score on the next read.
        assert verified_score > pre_score

        # Un-verify via the same moderation endpoint (symmetric removal).
        unverify = await test_client.put(
            f"/api/v3/completions/{completion_id}/moderate",
            json={"moderated_by": user_id, "verified": False, "verification_reason": "rejected"},
        )
        assert unverify.status_code == 200
        await _recompute(asyncpg_pool)
        unverified_score = await _score(test_client, user_id)
        # req 9: un-verifying returns the score to its pre-verification value (float tolerance).
        assert math.isclose(unverified_score, pre_score, abs_tol=1e-6)

    async def test_field_relativity_second_player_updates(self, test_client, asyncpg_pool, seed):
        """A second player on the same map updates when the field shifts (req 8)."""
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        player_a = await seed.make_user()
        player_b = await seed.make_user()

        msg_a = int(uuid4().int % 9_000_000_000)
        msg_b = int(uuid4().int % 9_000_000_000)
        # B is already verified (slower); A is pending (faster).
        await seed.make_completion(
            user_id=player_b, map_id=map_id, time=50.0, verified=True, message_id=msg_b
        )
        await seed.make_completion(
            user_id=player_a, map_id=map_id, time=20.0, verified=False, message_id=msg_a
        )
        completion_a = await asyncpg_pool.fetchval(
            "SELECT id FROM core.completions WHERE message_id = $1", msg_a
        )

        await _recompute(asyncpg_pool)
        b_before = await _score(test_client, player_b)
        assert b_before > 0  # B is the sole verified run -> time_pct 1.0 (fastest of field).

        # Verifying A (faster) demotes B from fastest -> B's time_pct drops -> score shifts.
        verify = await test_client.put(
            f"/api/v3/completions/{completion_a}/verification",
            json={"verified": True, "verified_by": player_a, "reason": None},
        )
        assert verify.status_code == 200
        await _recompute(asyncpg_pool)
        b_after = await _score(test_client, player_b)
        # req 8: the same-map second player's score updates after the field changes.
        assert not math.isclose(b_after, b_before, abs_tol=1e-6)
        assert b_after < b_before

    async def test_suspicious_flag_drops_score_to_zero(self, test_client, asyncpg_pool, seed):
        """Suspicious-flagging a user drops their skill score to 0 (req 9)."""
        user_id = await seed.make_user()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        msg_id = int(uuid4().int % 9_000_000_000)
        await seed.make_completion(
            user_id=user_id, map_id=map_id, time=30.0, verified=True, message_id=msg_id
        )

        await _recompute(asyncpg_pool)
        assert await _score(test_client, user_id) > 0

        # Flag via the real endpoint (emits skill.recompute.requested post-commit).
        flag = await test_client.post(
            "/api/v3/completions/suspicious",
            json={"message_id": msg_id, "context": "test", "flag_type": "Cheating", "flagged_by": user_id},
        )
        assert flag.status_code == 201
        await _recompute(asyncpg_pool)
        # req 9: the flagged user's only eligible run is excluded -> score 0.
        assert await _score(test_client, user_id) == 0.0

        # Un-flagging restores eligibility -> score returns (symmetric removal, req 9).
        unflag = await test_client.request(
            "DELETE",
            "/api/v3/completions/suspicious",
            json={"message_id": msg_id},
        )
        assert unflag.status_code == 200
        await _recompute(asyncpg_pool)
        assert await _score(test_client, user_id) > 0


# ---------------------------------------------------------------------------
# req 6 — sortable skill_score leaderboard column; skill_rank untouched
# ---------------------------------------------------------------------------


class TestLeaderboardSkillScore:
    """GET /community/leaderboard?sort=skill_score (SPEC req 6, D-07/D-08)."""

    async def test_sort_descending_and_pagination(self, test_client, asyncpg_pool, seed):
        """Descending skill_score order + working pagination; skill_rank column intact."""
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        # Three players with strictly decreasing field times -> distinct skill scores.
        for i, t in enumerate((15.0, 35.0, 55.0)):
            uid = await seed.make_user()
            await seed.make_completion(
                user_id=uid,
                map_id=map_id,
                time=t,
                verified=True,
                message_id=int(uuid4().int % 9_000_000_000) + i,
            )
        await _recompute(asyncpg_pool)

        resp = await test_client.get(
            f"{COMMUNITY}/leaderboard",
            params={"sort_column": "skill_score", "sort_direction": "desc", "page_size": 50},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert rows, "leaderboard returned no rows"

        scores = [float(r["skill_score"]) for r in rows]
        # req 6: descending skill_score sort.
        assert scores == sorted(scores, reverse=True)
        # req 6: the skill_rank label column is unchanged (still present on every row).
        assert all("skill_rank" in r and isinstance(r["skill_rank"], str) for r in rows)

        # Pagination: a smaller page is a strict prefix of the full descending order.
        page1 = await test_client.get(
            f"{COMMUNITY}/leaderboard",
            params={"sort_column": "skill_score", "sort_direction": "desc", "page_size": 2, "page_number": 1},
        )
        assert page1.status_code == 200
        page1_scores = [float(r["skill_score"]) for r in page1.json()]
        assert len(page1.json()) <= 2
        assert page1_scores == scores[: len(page1_scores)]

    async def test_zero_eligible_player_ranked_last(self, test_client, asyncpg_pool, seed):
        """A zero-eligible player shows skill_score 0, ranked last under skill sort (D-07)."""
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        scorer = await seed.make_user()
        await seed.make_completion(
            user_id=scorer,
            map_id=map_id,
            time=20.0,
            verified=True,
            message_id=int(uuid4().int % 9_000_000_000),
        )
        empty = await seed.make_user()  # no completions -> no snapshot row (lean, D-07)
        await _recompute(asyncpg_pool)

        resp = await test_client.get(
            f"{COMMUNITY}/leaderboard",
            params={"sort_column": "skill_score", "sort_direction": "desc", "page_size": 50},
        )
        assert resp.status_code == 200
        rows = resp.json()
        by_user = {int(r["user_id"]): float(r["skill_score"]) for r in rows}
        # req 6/D-07: the zero-eligible player is present with an explicit 0 score.
        assert by_user.get(empty) == 0.0
        assert by_user.get(scorer, 0.0) > 0.0
        # COALESCE(0) places the zero-eligible player at/after the scorer (ranked last).
        scores = [float(r["skill_score"]) for r in rows]
        assert scores[-1] == 0.0


# ---------------------------------------------------------------------------
# req 6 / req 7 — empty-player read + breakdown-sums-to-total
# ---------------------------------------------------------------------------


class TestSkillReads:
    """GET /skill/users/{id} (+ /breakdown) — empty-player rule + sum invariant."""

    async def test_empty_player_zero_and_empty_breakdown(self, test_client, asyncpg_pool, seed):
        """A zero-eligible player returns score 0 and an empty breakdown (req 6/7, D-07)."""
        empty = await seed.make_user()
        await _recompute(asyncpg_pool)

        score_resp = await test_client.get(f"{SKILL}/users/{empty}")
        assert score_resp.status_code == 200
        assert float(score_resp.json()["skill_score"]) == 0.0

        breakdown_resp = await test_client.get(f"{SKILL}/users/{empty}/breakdown")
        assert breakdown_resp.status_code == 200
        assert breakdown_resp.json() == []

    async def test_breakdown_contributions_sum_to_total(self, test_client, asyncpg_pool, seed):
        """Gamma-decayed per-map contributions sum to the user's score total (req 7)."""
        user_id = await seed.make_user()
        # Several maps so the gamma decay (Σ sᵢ/iᵞ) is exercised across ranks.
        for raw, t in ((9.0, 20.0), (7.0, 25.0), (5.0, 30.0)):
            map_id = await seed.make_map(difficulty="Hell", raw=raw)
            await seed.make_completion(
                user_id=user_id,
                map_id=map_id,
                time=t,
                verified=True,
                message_id=int(uuid4().int % 9_000_000_000),
            )
        await _recompute(asyncpg_pool)

        total = await _score(test_client, user_id)
        breakdown = await test_client.get(f"{SKILL}/users/{user_id}/breakdown")
        assert breakdown.status_code == 200
        rows = breakdown.json()
        assert len(rows) == 3
        contribution_sum = sum(float(r["contribution"]) for r in rows)
        # req 7: contributions (already gamma-decayed during recompute) sum to the total.
        assert math.isclose(contribution_sum, total, rel_tol=1e-6, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# req 7 — PATCH /skill/config authz (401/403 non-superuser vs 200 superuser)
# ---------------------------------------------------------------------------


@pytest.fixture
async def read_only_client(
    postgres_service: PostgresService,
    asyncpg_pool: asyncpg.Pool,
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Client authenticated as a NON-superuser holding only a read scope.

    The seeded ``testing`` token is a superuser and bypasses scope checks, so a
    dedicated scoped token is required to exercise the superuser-only guard on
    PATCH /skill/config (req 7, D-10).
    """
    from app import create_app

    api_key = f"ro-{uuid4().hex[:12]}"
    async with asyncpg_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO public.auth_users (username, info) VALUES ($1, $2) RETURNING id",
            f"readonly-{uuid4().hex[:8]}",
            "skill:read only",
        )
        await conn.execute(
            """
            INSERT INTO public.api_tokens (user_id, api_key, is_superuser, scopes)
            VALUES ($1, $2, FALSE, $3)
            """,
            user_id,
            api_key,
            ["completions:read"],
        )

    app = create_app(psql_dsn=_dsn(postgres_service))
    async with AsyncTestClient(app=app) as client:
        client.headers.update({"x-pytest-enabled": "1", "X-API-KEY": api_key})
        yield client


class TestConfigPatchAuthz:
    """PATCH /skill/config superuser-only (SPEC req 7, D-10)."""

    async def test_unauthenticated_rejected(self, unauthenticated_client):
        """No API key -> 401."""
        resp = await unauthenticated_client.patch(f"{SKILL}/config", json={"gamma": 0.7})
        assert resp.status_code == 401

    async def test_non_superuser_rejected(self, read_only_client):
        """A scoped non-superuser caller is rejected (401/403)."""
        resp = await read_only_client.patch(f"{SKILL}/config", json={"gamma": 0.7})
        assert resp.status_code in (401, 403)

    async def test_superuser_patch_changes_scores(self, test_client, asyncpg_pool, seed):
        """A superuser PATCH succeeds (200) and a subsequent score read reflects new weights."""
        user_id = await seed.make_user()
        for raw, t in ((9.0, 20.0), (7.0, 25.0), (5.0, 30.0)):
            map_id = await seed.make_map(difficulty="Hell", raw=raw)
            await seed.make_completion(
                user_id=user_id,
                map_id=map_id,
                time=t,
                verified=True,
                message_id=int(uuid4().int % 9_000_000_000),
            )
        await _recompute(asyncpg_pool)
        before = await _score(test_client, user_id)
        assert before > 0

        # Read the current gamma so we can restore it afterwards (shared config row).
        cfg = await test_client.get(f"{SKILL}/config")
        assert cfg.status_code == 200
        original_gamma = float(cfg.json()["gamma"])

        # Lower gamma -> weaker diminishing returns -> a multi-map player's total rises.
        # The PATCH itself triggers an immediate recompute (D-10).
        patch = await test_client.patch(f"{SKILL}/config", json={"gamma": 0.5})
        assert patch.status_code == 200
        after = await _score(test_client, user_id)
        # req 7/D-10: scores change after the superuser-applied weight change.
        assert not math.isclose(after, before, abs_tol=1e-6)

        # Restore the original gamma so sibling tests see the seeded config.
        restore = await test_client.patch(f"{SKILL}/config", json={"gamma": original_gamma})
        assert restore.status_code == 200


# ---------------------------------------------------------------------------
# cold-start — snapshot_is_empty() guard for the one-time initial population
# ---------------------------------------------------------------------------


class TestSnapshotIsEmpty:
    """SkillRepository.snapshot_is_empty() — the cold-start population guard (QUICK-260612-oqg)."""

    async def test_empty_before_recompute_false_after_population(self, asyncpg_pool, seed):
        """True on a fresh/empty snapshot; False after recompute_all populates an eligible run."""
        repo = SkillRepository(asyncpg_pool)

        # Fresh DB / post-truncate: no rows in skill.snapshot -> empty.
        # Truncate first so a sibling test that populated the shared snapshot does not
        # leak into this assertion (the snapshot is a single global cache table).
        await asyncpg_pool.execute("TRUNCATE skill.snapshot")
        assert await repo.snapshot_is_empty() is True

        # Seed one eligible (verified, video) completion, then run the shared rebuild.
        user_id = await seed.make_user()
        map_id = await seed.make_map(difficulty="Hell", raw=9.0)
        await seed.make_completion(
            user_id=user_id,
            map_id=map_id,
            time=30.0,
            verified=True,
            message_id=int(uuid4().int % 9_000_000_000),
        )
        await _recompute(asyncpg_pool)

        # After population, the snapshot has at least one row -> not empty.
        assert await repo.snapshot_is_empty() is False


# ---------------------------------------------------------------------------
# PYO-TIER — percentile-based tier system (boundaries / tier / percentile / floor)
# ---------------------------------------------------------------------------


class TestSkillTiers:
    """Percentile tier system: assignment, legend, Unranked/0 case, and population floor.

    The tier boundaries are computed from ``skill.snapshot`` (``skill_score > 0`` rows) by
    ``SkillRepository.compute_tier_boundaries`` — the SAME routine ``_do_recompute`` calls
    after ``replace_snapshot``. ``recompute_all`` rebuilds the WHOLE snapshot from every row
    in ``core.completions`` (shared across the integration DB), so these tests seed
    ``skill.snapshot`` DIRECTLY and invoke the real boundary routine to get a deterministic,
    isolated non-zero population — then exercise the real read endpoints (``/skill/tiers``,
    ``/skill/users/{id}``, ``/community/leaderboard``) over the resulting boundaries.
    """

    @staticmethod
    async def _seed_snapshot(pool: asyncpg.Pool, scores: dict[int, float]) -> None:
        """Replace skill.snapshot with the given user_id -> skill_score rows, then compute boundaries."""
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE skill.snapshot")
            for uid, score in scores.items():
                await conn.execute(
                    """
                    INSERT INTO skill.snapshot
                        (user_id, skill_score, maps_cleared, video_clears, hardest_raw, breakdown, computed_at)
                    VALUES ($1, $2, 1, 1, 9.0, '[]'::jsonb, now())
                    """,
                    uid,
                    score,
                )
        # Drive the SAME boundary routine _do_recompute uses (no fork).
        await SkillRepository(pool).compute_tier_boundaries()

    async def test_tier_assignment_and_legend(self, test_client, asyncpg_pool, seed):
        """>=20 scored players -> 7 increasing boundaries; per-user tier matches the leaderboard (PYO-TIER-02/03/04/05)."""
        # Seed >= 20 distinct non-zero scores (a clean increasing spread) so percentile_cont
        # yields strictly increasing cut-points.
        users = [await seed.make_user() for _ in range(24)]
        scores = {uid: float(10 + i) for i, uid in enumerate(users)}  # 10.0 .. 33.0, all distinct
        await self._seed_snapshot(asyncpg_pool, scores)

        # PYO-TIER-05: the legend exposes 7 percentiles + 7 boundaries.
        tiers_resp = await test_client.get(f"{SKILL}/tiers")
        assert tiers_resp.status_code == 200
        legend = tiers_resp.json()
        assert len(legend["percentiles"]) == 7
        assert len(legend["boundaries"]) == 7
        # PYO-TIER-02: boundaries are strictly increasing (monotone cut-points).
        boundaries = [float(b) for b in legend["boundaries"]]
        assert boundaries == sorted(boundaries)
        assert all(b2 > b1 for b1, b2 in zip(boundaries[:-1], boundaries[1:], strict=True))

        # The top-scoring seeded user.
        top_user = max(scores, key=lambda u: scores[u])

        # PYO-TIER-03: the top scorer's per-user read carries a real tier (1..8) + percentile,
        # plus a non-empty skill_tier_name consistent with the integer tier.
        user_resp = await test_client.get(f"{SKILL}/users/{top_user}")
        assert user_resp.status_code == 200
        user_json = user_resp.json()
        assert 1 <= int(user_json["tier"]) <= 8
        assert 0.0 <= float(user_json["percentile"]) <= 1.0
        assert user_json["skill_tier_name"] == SKILL_TIER_NAMES[int(user_json["tier"])]

        # PYO-TIER-04: the same user's leaderboard row carries the SAME tier, and the
        # skill_rank / skill_score columns are still present/unchanged.
        lb = await test_client.get(
            f"{COMMUNITY}/leaderboard",
            params={"sort_column": "skill_score", "sort_direction": "desc", "page_size": 50},
        )
        assert lb.status_code == 200
        lb_rows = lb.json()
        assert lb_rows
        assert all("skill_rank" in r and isinstance(r["skill_rank"], str) for r in lb_rows)
        assert all("skill_score" in r for r in lb_rows)
        # Renamed columns: skill_tier / skill_percentile, plus the mapped skill_tier_name.
        assert all("skill_tier_name" in r for r in lb_rows)
        assert all(r["skill_tier_name"] == SKILL_TIER_NAMES[int(r["skill_tier"])] for r in lb_rows)
        # Unranked rows (skill_tier 0) map to "Unranked".
        for r in lb_rows:
            if int(r["skill_tier"]) == 0:
                assert r["skill_tier_name"] == "Unranked"
        lb_tier_by_user = {int(r["user_id"]): int(r["skill_tier"]) for r in lb_rows}
        assert top_user in lb_tier_by_user
        assert lb_tier_by_user[top_user] == int(user_json["tier"])

    async def test_unranked_zero_eligible(self, test_client, asyncpg_pool, seed):
        """A user with no eligible score is tier 0 / Unranked on both the user read and leaderboard (PYO-TIER-03)."""
        # Populate a valid >=20 non-zero population (so boundaries exist), then add one
        # user who is NOT in the snapshot at all -> tier 0 / Unranked.
        users = [await seed.make_user() for _ in range(20)]
        scores = {uid: float(10 + i) for i, uid in enumerate(users)}
        await self._seed_snapshot(asyncpg_pool, scores)

        empty = await seed.make_user()  # never inserted into skill.snapshot
        user_resp = await test_client.get(f"{SKILL}/users/{empty}")
        assert user_resp.status_code == 200
        user_json = user_resp.json()
        assert int(user_json["tier"]) == 0
        assert float(user_json["skill_score"]) == 0.0
        assert user_json["skill_tier_name"] == "Unranked"

        lb = await test_client.get(
            f"{COMMUNITY}/leaderboard",
            params={"sort_column": "skill_score", "sort_direction": "desc", "page_size": 50},
        )
        assert lb.status_code == 200
        rows_by_user = {int(r["user_id"]): r for r in lb.json()}
        # If present on this page, the zero-eligible player is Unranked (skill_tier 0).
        if empty in rows_by_user:
            assert int(rows_by_user[empty]["skill_tier"]) == 0
            assert rows_by_user[empty]["skill_tier_name"] == "Unranked"

    async def test_population_floor_fallback(self, test_client, asyncpg_pool, seed):
        """Fewer than 20 scored players -> empty boundaries -> everyone Unranked, no crash (PYO-TIER-06)."""
        # Seed only a few (< 20) scored users so the population floor is not met.
        users = [await seed.make_user() for _ in range(5)]
        scores = {uid: float(10 + i) for i, uid in enumerate(users)}
        await self._seed_snapshot(asyncpg_pool, scores)

        # PYO-TIER-06: below the floor the legend has empty boundaries.
        tiers_resp = await test_client.get(f"{SKILL}/tiers")
        assert tiers_resp.status_code == 200
        assert tiers_resp.json()["boundaries"] == []

        # Every scored user is Unranked (tier 0) with no crash, even with a positive score.
        for uid in users:
            user_resp = await test_client.get(f"{SKILL}/users/{uid}")
            assert user_resp.status_code == 200
            assert int(user_resp.json()["tier"]) == 0
            assert float(user_resp.json()["skill_score"]) > 0


# ---------------------------------------------------------------------------
# U82-TIER-PATCH — PATCH /skill/tiers (auth gate, validation-rejection, happy path)
# ---------------------------------------------------------------------------


class TestTiersPatch:
    """PATCH /skill/tiers: superuser-only percentile retune + boundary re-derivation (U82-TIER-PATCH-01).

    Mirrors ``TestConfigPatchAuthz`` for the scope gate and ``TestSkillTiers`` for the
    deterministic >=20 non-zero population (so ``compute_tier_boundaries`` mints real
    cut-points). The single-row ``skill.tier_config`` is shared across the integration
    DB, so the happy-path test RESTORES the seeded default percentiles afterward.
    """

    _VALID = [0.40, 0.55, 0.70, 0.80, 0.90, 0.95, 0.99]
    _SEEDED_DEFAULT = [0.50, 0.70, 0.85, 0.93, 0.97, 0.99, 0.995]

    async def test_unauthenticated_rejected(self, unauthenticated_client):
        """No API key -> 401."""
        resp = await unauthenticated_client.patch(f"{SKILL}/tiers", json={"percentiles": self._VALID})
        assert resp.status_code == 401

    async def test_non_superuser_rejected(self, read_only_client):
        """A scoped non-superuser caller is rejected (401/403) by the skill:admin sentinel."""
        resp = await read_only_client.patch(f"{SKILL}/tiers", json={"percentiles": self._VALID})
        assert resp.status_code in (401, 403)

    async def test_superuser_patch_persists_and_rederives(self, test_client, asyncpg_pool, seed):
        """A superuser PATCH persists new percentiles and re-derives boundaries (U82-TIER-PATCH-01)."""
        # Seed >= 20 distinct non-zero scores so a qualifying population exists for boundaries.
        users = [await seed.make_user() for _ in range(24)]
        scores = {uid: float(10 + i) for i, uid in enumerate(users)}
        await TestSkillTiers._seed_snapshot(asyncpg_pool, scores)

        before = await test_client.get(f"{SKILL}/tiers")
        assert before.status_code == 200
        boundaries_before = [float(b) for b in before.json()["boundaries"]]
        assert len(boundaries_before) == 7  # population floor met -> real cut-points

        # PATCH a NEW valid strictly-increasing array in (0, 1) as the superuser.
        patch = await test_client.patch(f"{SKILL}/tiers", json={"percentiles": self._VALID})
        assert patch.status_code == 200
        assert [float(p) for p in patch.json()["percentiles"]] == self._VALID

        # GET reflects the new percentiles; boundaries were re-derived (present + monotone).
        after = await test_client.get(f"{SKILL}/tiers")
        assert after.status_code == 200
        after_json = after.json()
        assert [float(p) for p in after_json["percentiles"]] == self._VALID
        boundaries_after = [float(b) for b in after_json["boundaries"]]
        assert len(boundaries_after) == 7
        assert boundaries_after == sorted(boundaries_after)
        assert all(b2 > b1 for b1, b2 in zip(boundaries_after[:-1], boundaries_after[1:], strict=True))
        # New percentiles over the same population produce different cut-points.
        assert boundaries_after != boundaries_before

        # Restore the seeded default percentiles (shared single-row config).
        restore = await test_client.patch(f"{SKILL}/tiers", json={"percentiles": self._SEEDED_DEFAULT})
        assert restore.status_code == 200

    async def test_superuser_invalid_rejected_nothing_persisted(self, test_client, asyncpg_pool, seed):
        """Invalid percentiles -> 400, and a re-read confirms nothing was persisted."""
        # Establish a known config first (a valid PATCH), so the unchanged assertion is precise.
        users = [await seed.make_user() for _ in range(24)]
        scores = {uid: float(10 + i) for i, uid in enumerate(users)}
        await TestSkillTiers._seed_snapshot(asyncpg_pool, scores)
        seeded = await test_client.patch(f"{SKILL}/tiers", json={"percentiles": self._VALID})
        assert seeded.status_code == 200

        before = await test_client.get(f"{SKILL}/tiers")
        assert before.status_code == 200
        percentiles_before = [float(p) for p in before.json()["percentiles"]]

        # Invalid: wrong length AND not strictly increasing AND out of range.
        bad = await test_client.patch(f"{SKILL}/tiers", json={"percentiles": [0.5, 0.4, 1.2]})
        assert bad.status_code == 400

        after = await test_client.get(f"{SKILL}/tiers")
        assert after.status_code == 200
        assert [float(p) for p in after.json()["percentiles"]] == percentiles_before

        # Restore the seeded default percentiles (shared single-row config).
        restore = await test_client.patch(f"{SKILL}/tiers", json={"percentiles": self._SEEDED_DEFAULT})
        assert restore.status_code == 200
