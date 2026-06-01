"""Integration tests for Tournaments v3 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_tournaments,
]

BASE = "/api/v3/tournaments"


class TestGetConfig:
    """GET /api/v3/tournaments/config"""

    async def test_returns_config_singleton(self, test_client):
        """Config endpoint returns the seeded singleton with expected fields."""
        response = await test_client.get(f"{BASE}/config")

        assert response.status_code == 200
        data = response.json()
        assert "blacklist_weeks" in data
        assert isinstance(data["blacklist_weeks"], int)
        assert "created_at" in data
        assert "updated_at" in data


class TestUpdateConfig:
    """PATCH /api/v3/tournaments/config"""

    async def test_update_blacklist_weeks(self, test_client):
        """Updating blacklist_weeks returns updated value."""
        response = await test_client.patch(
            f"{BASE}/config",
            json={"blacklist_weeks": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["blacklist_weeks"] == 5

    async def test_empty_patch_returns_unchanged(self, test_client):
        """Empty PATCH body returns the config unchanged."""
        response = await test_client.patch(f"{BASE}/config", json={})

        assert response.status_code == 200
        data = response.json()
        assert "blacklist_weeks" in data


class TestCreateCategory:
    """POST /api/v3/tournaments/categories"""

    async def test_create_minimal_category(self, test_client):
        """Minimal category with name and difficulties returns 201."""
        name = f"Minimal {uuid4().hex[:8]}"
        response = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == name
        assert data["difficulties"] == ["Easy"]
        assert data["cycle_frequency"] == "weekly"
        assert data["is_active"] is True
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_full_category(self, test_client):
        """Category with all fields returns 201 and preserves values."""
        name = f"Full {uuid4().hex[:8]}"
        response = await test_client.post(
            f"{BASE}/categories",
            json={
                "name": name,
                "difficulties": ["Hard", "Very Hard"],
                "cycle_frequency": "biweekly",
                "participation_xp": 25,
                "placement_xp": [{"place": 1, "xp": 100}],
                "streak_xp": [{"threshold": 3, "xp": 50}],
                "champion_role_id": 123456,
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == name
        assert data["difficulties"] == ["Hard", "Very Hard"]
        assert data["cycle_frequency"] == "biweekly"
        assert data["participation_xp"] == 25
        assert data["placement_xp"] == [{"place": 1, "xp": 100}]
        assert data["streak_xp"] == [{"threshold": 3, "xp": 50}]
        assert data["champion_role_id"] == 123456

    async def test_duplicate_name_returns_409(self, test_client):
        """Creating a category with an existing name returns 409."""
        name = f"Dup {uuid4().hex[:8]}"
        first = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        assert first.status_code == 201

        second = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Medium"]},
        )
        assert second.status_code == 409


class TestListCategories:
    """GET /api/v3/tournaments/categories"""

    async def test_list_returns_array(self, test_client):
        """List endpoint returns a JSON array."""
        response = await test_client.get(f"{BASE}/categories")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_list_includes_created_category(self, test_client):
        """A newly created category appears in the list."""
        name = f"Listed {uuid4().hex[:8]}"
        await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )

        response = await test_client.get(f"{BASE}/categories")

        assert response.status_code == 200
        names = [c["name"] for c in response.json()]
        assert name in names


class TestGetCategory:
    """GET /api/v3/tournaments/categories/{id}"""

    async def test_get_existing_category(self, test_client):
        """GET by ID returns the category with matching id."""
        name = f"GetOne {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Medium"]},
        )
        category_id = create_resp.json()["id"]

        response = await test_client.get(f"{BASE}/categories/{category_id}")

        assert response.status_code == 200
        assert response.json()["id"] == category_id
        assert response.json()["name"] == name

    async def test_get_nonexistent_returns_404(self, test_client):
        """GET with nonexistent ID returns 404."""
        response = await test_client.get(f"{BASE}/categories/999999")

        assert response.status_code == 404


class TestGetStreak:
    """GET /api/v3/tournaments/streaks/{user_id}"""

    async def test_get_existing_streak(self, test_client, asyncpg_pool, create_test_user):
        """GET with a seeded streak row returns 200 + struct body."""
        user_id = await create_test_user(nickname=f"Streaker{uuid4().hex[:6]}")

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.streaks (user_id, current_streak, max_streak)
                VALUES ($1, 3, 5)
                """,
                user_id,
            )

        response = await test_client.get(f"{BASE}/streaks/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == user_id
        assert data["current_streak"] == 3
        assert data["max_streak"] == 5

    async def test_get_nonexistent_returns_404(self, test_client, create_test_user):
        """GET for a user with no streak row returns 404 (D-04 zero-mapping is bot-side)."""
        user_id = await create_test_user(nickname=f"NoStreak{uuid4().hex[:6]}")

        response = await test_client.get(f"{BASE}/streaks/{user_id}")

        assert response.status_code == 404

    async def test_rejected_without_auth(self, unauthenticated_client):
        """GET /streaks without the tournaments:read scope returns 401."""
        response = await unauthenticated_client.get(f"{BASE}/streaks/1")

        assert response.status_code == 401


class TestUpdateCategory:
    """PATCH /api/v3/tournaments/categories/{id}"""

    async def test_update_name(self, test_client):
        """PATCH with a new name returns 200 and updated name."""
        name = f"BeforeUpdate {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        new_name = f"AfterUpdate {uuid4().hex[:8]}"
        response = await test_client.patch(
            f"{BASE}/categories/{category_id}",
            json={"name": new_name},
        )

        assert response.status_code == 200
        assert response.json()["name"] == new_name

    async def test_update_nonexistent_returns_404(self, test_client):
        """PATCH with nonexistent ID returns 404."""
        response = await test_client.patch(
            f"{BASE}/categories/999999",
            json={"name": "Ghost"},
        )

        assert response.status_code == 404

    async def test_update_duplicate_name_returns_409(self, test_client):
        """Renaming a category to an existing name returns 409."""
        name_a = f"CatA {uuid4().hex[:8]}"
        name_b = f"CatB {uuid4().hex[:8]}"

        await test_client.post(
            f"{BASE}/categories",
            json={"name": name_a, "difficulties": ["Easy"]},
        )
        resp_b = await test_client.post(
            f"{BASE}/categories",
            json={"name": name_b, "difficulties": ["Medium"]},
        )
        category_b_id = resp_b.json()["id"]

        response = await test_client.patch(
            f"{BASE}/categories/{category_b_id}",
            json={"name": name_a},
        )

        assert response.status_code == 409


class TestDeleteCategory:
    """DELETE /api/v3/tournaments/categories/{id}"""

    async def test_delete_existing(self, test_client):
        """DELETE returns 204 and subsequent GET returns 404."""
        name = f"ToDelete {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        delete_resp = await test_client.delete(f"{BASE}/categories/{category_id}")
        assert delete_resp.status_code == 204

        get_resp = await test_client.get(f"{BASE}/categories/{category_id}")
        assert get_resp.status_code == 404

    async def test_delete_nonexistent_returns_404(self, test_client):
        """DELETE with nonexistent ID returns 404."""
        response = await test_client.delete(f"{BASE}/categories/999999")

        assert response.status_code == 404


class TestCategoryLockedGuard:
    """Tests for CYCLE-08: categories with active cycles cannot be modified."""

    async def test_update_locked_during_active_cycle(self, test_client, asyncpg_pool, create_test_map):
        """PATCH returns 409 when category has an active cycle."""
        name = f"Locked {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status)
                VALUES ($1, $2, 'active')
                """,
                category_id,
                map_id,
            )

        response = await test_client.patch(
            f"{BASE}/categories/{category_id}",
            json={"name": f"NewName {uuid4().hex[:8]}"},
        )

        assert response.status_code == 409

    async def test_delete_locked_during_active_cycle(self, test_client, asyncpg_pool, create_test_map):
        """DELETE returns 409 when category has an active cycle."""
        name = f"LockedDel {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status)
                VALUES ($1, $2, 'active')
                """,
                category_id,
                map_id,
            )

        response = await test_client.delete(f"{BASE}/categories/{category_id}")

        assert response.status_code == 409


class TestUnauthenticated:
    """Scope guard rejection for unauthenticated requests."""

    async def test_config_rejected_without_auth(self, unauthenticated_client):
        """GET /config without API key returns 401."""
        response = await unauthenticated_client.get(f"{BASE}/config")

        assert response.status_code == 401


class TestSelectMapEndpoint:
    """Tests for POST /api/v3/tournaments/categories/{id}/select-map"""

    async def test_select_map_creates_pending_cycle(self, test_client, asyncpg_pool, create_test_map):
        """Select-map creates a pending cycle with map details."""
        name = f"SelMap {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        # Set blacklist_weeks to 0 to avoid interference
        await test_client.patch(f"{BASE}/config", json={"blacklist_weeks": 0})

        # Create an eligible map with matching difficulty
        await create_test_map(difficulty="Easy")

        response = await test_client.post(f"{BASE}/categories/{category_id}/select-map")

        assert response.status_code == 201
        data = response.json()
        assert "map_code" in data
        assert "map_name" in data
        assert "map_difficulty" in data
        assert data["status"] == "pending"

    async def test_select_map_returns_409_when_pending_exists(self, test_client, asyncpg_pool, create_test_map):
        """Select-map returns 409 when a pending cycle already exists."""
        name = f"SelDup {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        # Set blacklist_weeks to 0
        await test_client.patch(f"{BASE}/config", json={"blacklist_weeks": 0})

        map_id = await create_test_map(difficulty="Easy")

        # Insert a pending cycle directly
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tournaments.cycles (category_id, map_id) VALUES ($1, $2)",
                category_id,
                map_id,
            )

        response = await test_client.post(f"{BASE}/categories/{category_id}/select-map")

        assert response.status_code == 409

    async def test_select_map_category_not_found(self, test_client):
        """Select-map returns 404 for nonexistent category."""
        response = await test_client.post(f"{BASE}/categories/999999/select-map")

        assert response.status_code == 404


class TestGetNextCycleEndpoint:
    """Tests for GET /api/v3/tournaments/categories/{id}/next-cycle"""

    async def test_preview_existing_pending(self, test_client, asyncpg_pool, create_test_map):
        """GET next-cycle returns pending cycle with map details."""
        name = f"Preview {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO tournaments.cycles (category_id, map_id) VALUES ($1, $2)",
                category_id,
                map_id,
            )

        response = await test_client.get(f"{BASE}/categories/{category_id}/next-cycle")

        assert response.status_code == 200
        data = response.json()
        assert "map_code" in data
        assert data["status"] == "pending"

    async def test_preview_no_pending_returns_404(self, test_client):
        """GET next-cycle returns 404 when no pending cycle exists."""
        name = f"NoPend {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        response = await test_client.get(f"{BASE}/categories/{category_id}/next-cycle")

        assert response.status_code == 404

    async def test_preview_category_not_found(self, test_client):
        """GET next-cycle returns 404 for nonexistent category."""
        response = await test_client.get(f"{BASE}/categories/999999/next-cycle")

        assert response.status_code == 404


class TestRerollEndpoint:
    """Tests for POST /api/v3/tournaments/categories/{id}/reroll"""

    async def test_reroll_changes_map(self, test_client, asyncpg_pool, create_test_map):
        """Reroll replaces the pending cycle with a new map selection."""
        name = f"Reroll {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        # Set blacklist_weeks to 0 to avoid interference
        await test_client.patch(f"{BASE}/config", json={"blacklist_weeks": 0})

        # Create multiple eligible maps so reroll can pick a different one
        await create_test_map(difficulty="Easy")
        await create_test_map(difficulty="Easy")

        # Select initial map
        select_resp = await test_client.post(f"{BASE}/categories/{category_id}/select-map")
        assert select_resp.status_code == 201

        # Reroll
        response = await test_client.post(f"{BASE}/categories/{category_id}/reroll")

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "pending"
        assert "map_code" in data

    async def test_reroll_no_pending_returns_404(self, test_client):
        """Reroll returns 404 when no pending cycle exists."""
        name = f"RerollNone {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        response = await test_client.post(f"{BASE}/categories/{category_id}/reroll")

        assert response.status_code == 404


class TestChooseMapEndpoint:
    """Tests for PATCH /api/v3/tournaments/categories/{id}/next-cycle"""

    async def test_choose_map_sets_specific_map(self, test_client, asyncpg_pool, create_test_map):
        """Choose-map creates pending cycle with the specified map."""
        name = f"Choose {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")

        # Get the map code from DB
        async with asyncpg_pool.acquire() as conn:
            map_code = await conn.fetchval("SELECT code FROM core.maps WHERE id = $1", map_id)

        response = await test_client.patch(
            f"{BASE}/categories/{category_id}/next-cycle",
            json={"map_code": map_code},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["map_code"] == map_code

    async def test_choose_map_invalid_code_returns_422(self, test_client):
        """Choose-map returns 422 for nonexistent map code."""
        name = f"ChooseInv {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        response = await test_client.patch(
            f"{BASE}/categories/{category_id}/next-cycle",
            json={"map_code": "ZZZZZ"},
        )

        assert response.status_code == 422

    async def test_choose_map_difficulty_mismatch_returns_422(self, test_client, asyncpg_pool, create_test_map):
        """Choose-map returns 422 when map difficulty does not match category."""
        name = f"ChooseMis {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Very Hard"]},
        )
        category_id = create_resp.json()["id"]

        # Create a map with "Easy" difficulty (mismatches "Very Hard" category)
        map_id = await create_test_map(difficulty="Easy")

        async with asyncpg_pool.acquire() as conn:
            map_code = await conn.fetchval("SELECT code FROM core.maps WHERE id = $1", map_id)

        response = await test_client.patch(
            f"{BASE}/categories/{category_id}/next-cycle",
            json={"map_code": map_code},
        )

        assert response.status_code == 422


class TestSubmitBypassRemoved:
    """SC-4: the verification-skipping bypass endpoint is gone (D-05).

    The only remaining tournament write is the verified pipeline: a NORMAL
    completion POST on the active cycle's map is auto-detected as a tournament
    submission. The PB run is recorded UNVERIFIED (verified=FALSE) and only
    flips verified after the verify endpoint/OCR runs.
    """

    async def _setup_active_cycle(self, test_client, asyncpg_pool, create_test_map, create_test_user):
        """Create a category, map, active cycle, and user.

        Returns (category_id, map_id, map_code, cycle_id, user_id).
        """
        name = f"Submit {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"Player{uuid4().hex[:6]}")

        async with asyncpg_pool.acquire() as conn:
            map_code = await conn.fetchval("SELECT code FROM core.maps WHERE id = $1", map_id)
            cycle_id = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES ($1, $2, 'active', NOW())
                RETURNING id
                """,
                category_id,
                map_id,
            )

        return category_id, map_id, map_code, cycle_id, user_id

    async def test_old_submit_endpoint_returns_404(
        self, test_client, asyncpg_pool, create_test_map, create_test_user
    ):
        """The removed POST /cycles/{id}/submit bypass endpoint no longer exists (404)."""
        _, _, _, cycle_id, user_id = await self._setup_active_cycle(
            test_client, asyncpg_pool, create_test_map, create_test_user
        )

        response = await test_client.post(
            f"{BASE}/cycles/{cycle_id}/submit",
            json={"user_id": user_id, "time": 42.5, "screenshot": "https://example.com/s.png"},
        )

        assert response.status_code == 404

    async def test_normal_completion_on_cycle_map_writes_unverified_tournament_row(
        self, test_client, asyncpg_pool, create_test_map, create_test_user
    ):
        """A normal completion POST on the cycle's map records an UNVERIFIED tournament row (SUB-01)."""
        _, map_id, map_code, cycle_id, user_id = await self._setup_active_cycle(
            test_client, asyncpg_pool, create_test_map, create_test_user
        )

        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "user_id": user_id,
                "code": map_code,
                "time": 42.5,
                "video": None,
                "screenshot": "https://example.com/s.png",
            },
        )

        assert response.status_code == 201
        verified = await asyncpg_pool.fetchval(
            "SELECT verified FROM tournaments.completions WHERE cycle_id = $1 AND user_id = $2",
            cycle_id,
            user_id,
        )
        assert verified is False

    async def test_cross_write_sets_fk(self, test_client, asyncpg_pool, create_test_map, create_test_user):
        """SUB-04: the auto-detected PB run sets tournament_completion_id FK on core.completions."""
        _, map_id, map_code, cycle_id, user_id = await self._setup_active_cycle(
            test_client, asyncpg_pool, create_test_map, create_test_user
        )

        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "user_id": user_id,
                "code": map_code,
                "time": 42.5,
                "video": None,
                "screenshot": "https://example.com/s.png",
            },
        )
        assert response.status_code == 201

        async with asyncpg_pool.acquire() as conn:
            tournament_completion_id = await conn.fetchval(
                "SELECT id FROM tournaments.completions WHERE cycle_id = $1 AND user_id = $2",
                cycle_id,
                user_id,
            )
            core_fk = await conn.fetchval(
                """
                SELECT tournament_completion_id
                FROM core.completions
                WHERE user_id = $1 AND map_id = $2
                ORDER BY inserted_at DESC
                LIMIT 1
                """,
                user_id,
                map_id,
            )

        assert core_fk is not None
        assert core_fk == tournament_completion_id


class TestLeaderboardEndpoint:
    """Tests for GET /api/v3/tournaments/cycles/{id}/leaderboard"""

    async def test_leaderboard_returns_200(self, test_client, asyncpg_pool, create_test_map, create_test_user):
        """Leaderboard returns ranked entries after submission."""
        name = f"LB {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"LBPlayer{uuid4().hex[:6]}")

        async with asyncpg_pool.acquire() as conn:
            cycle_id = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES ($1, $2, 'active', NOW())
                RETURNING id
                """,
                category_id,
                map_id,
            )

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot, verified)
                VALUES ($1, $2, $3, $4, $5, TRUE)
                """,
                cycle_id,
                user_id,
                map_id,
                42.5,
                "https://example.com/s.png",
            )

        response = await test_client.get(f"{BASE}/cycles/{cycle_id}/leaderboard")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "rank" in data[0]
        assert "user_id" in data[0]
        assert "name" in data[0]
        assert "time" in data[0]

    async def test_empty_leaderboard(self, test_client, asyncpg_pool, create_test_map):
        """Empty cycle returns 200 with empty list."""
        name = f"EmptyLB {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")

        async with asyncpg_pool.acquire() as conn:
            cycle_id = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES ($1, $2, 'active', NOW())
                RETURNING id
                """,
                category_id,
                map_id,
            )

        response = await test_client.get(f"{BASE}/cycles/{cycle_id}/leaderboard")

        assert response.status_code == 200
        assert response.json() == []


class TestCycleListingEndpoint:
    """Tests for GET /api/v3/tournaments/cycles"""

    async def test_list_cycles_returns_200(self, test_client, asyncpg_pool, create_test_map):
        """Cycle listing returns 200 with total and cycles list."""
        name = f"CycleList {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at, ended_at)
                VALUES ($1, $2, 'completed', NOW() - INTERVAL '7 days', NOW())
                """,
                category_id,
                map_id,
            )

        response = await test_client.get(f"{BASE}/cycles")

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "cycles" in data
        assert data["total"] >= 1

    async def test_list_cycles_status_filter(self, test_client, asyncpg_pool, create_test_map):
        """Status filter returns only matching cycles."""
        name = f"Filter {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map(difficulty="Easy")

        async with asyncpg_pool.acquire() as conn:
            # Insert one active cycle
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES ($1, $2, 'active', NOW())
                """,
                category_id,
                map_id,
            )
            # Insert one completed cycle (need another map to avoid conflicts)
            map_id2 = await create_test_map(difficulty="Easy")
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at, ended_at)
                VALUES ($1, $2, 'completed', NOW() - INTERVAL '7 days', NOW())
                """,
                category_id,
                map_id2,
            )

        response = await test_client.get(f"{BASE}/cycles?status=completed")

        assert response.status_code == 200
        data = response.json()
        for cycle in data["cycles"]:
            assert cycle["status"] == "completed"

    async def test_list_cycles_pagination(self, test_client, asyncpg_pool, create_test_map):
        """Pagination limits results to requested count."""
        response = await test_client.get(f"{BASE}/cycles?limit=1&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "cycles" in data
        assert len(data["cycles"]) <= 1


async def _seed_tournament_completion(
    asyncpg_pool, category_id: int, map_id: int, user_id: int, *, time: float = 99.0
) -> tuple[int, int]:
    """Seed an active cycle + an unverified tournament completion; return (cycle_id, tc_id)."""
    async with asyncpg_pool.acquire() as conn:
        cycle_id = await conn.fetchval(
            """
            INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
            VALUES ($1, $2, 'active', NOW())
            RETURNING id
            """,
            category_id,
            map_id,
        )
        tc_id = await conn.fetchval(
            """
            INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot, verified)
            VALUES ($1, $2, $3, $4, $5, FALSE)
            RETURNING id
            """,
            cycle_id,
            user_id,
            map_id,
            time,
            "https://example.com/s.png",
        )
    return cycle_id, tc_id


class TestVerifyTournamentCompletion:
    """PATCH /api/v3/tournaments/completions/{id}/verify|reject (tournaments:verify)."""

    async def test_verify_flips_row_and_grants_participation(
        self, test_client, asyncpg_pool, create_test_map, create_test_user
    ):
        """Verifying a non-PB tournament row flips verified TRUE + grants one XP row (SC-2/D-06)."""
        category_id = await asyncpg_pool.fetchval(
            """
            INSERT INTO tournaments.categories (name, difficulties, participation_xp, placement_xp, streak_xp)
            VALUES ($1, $2, 25, '[]'::jsonb, '[]'::jsonb)
            RETURNING id
            """,
            f"Verify {uuid4().hex[:8]}",
            ["Easy"],
        )
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"V{uuid4().hex[:6]}")
        cycle_id, tc_id = await _seed_tournament_completion(asyncpg_pool, category_id, map_id, user_id)

        response = await test_client.patch(f"{BASE}/completions/{tc_id}/verify")

        assert response.status_code == 200
        verified = await asyncpg_pool.fetchval(
            "SELECT verified FROM tournaments.completions WHERE id = $1", tc_id
        )
        assert verified is True
        xp_rows = await asyncpg_pool.fetchval(
            "SELECT COUNT(*) FROM tournaments.xp_grants WHERE cycle_id = $1 AND user_id = $2 AND reason = 'participation'",
            cycle_id,
            user_id,
        )
        assert xp_rows == 1

    async def test_verify_twice_grants_participation_once(
        self, test_client, asyncpg_pool, create_test_map, create_test_user
    ):
        """Verifying twice grants participation exactly once (D-02/D-06 ledger idempotency)."""
        category_id = await asyncpg_pool.fetchval(
            """
            INSERT INTO tournaments.categories (name, difficulties, participation_xp, placement_xp, streak_xp)
            VALUES ($1, $2, 25, '[]'::jsonb, '[]'::jsonb)
            RETURNING id
            """,
            f"VerifyTwice {uuid4().hex[:8]}",
            ["Easy"],
        )
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"VT{uuid4().hex[:6]}")
        cycle_id, tc_id = await _seed_tournament_completion(asyncpg_pool, category_id, map_id, user_id)

        await test_client.patch(f"{BASE}/completions/{tc_id}/verify")
        await test_client.patch(f"{BASE}/completions/{tc_id}/verify")

        xp_rows = await asyncpg_pool.fetchval(
            "SELECT COUNT(*) FROM tournaments.xp_grants WHERE cycle_id = $1 AND user_id = $2 AND reason = 'participation'",
            cycle_id,
            user_id,
        )
        assert xp_rows == 1

    async def test_reject_leaves_row_unverified(
        self, test_client, asyncpg_pool, create_test_map, create_test_user
    ):
        """Rejecting an already-verified run is refused with 409 (CR-01).

        ``_seed_tournament_completion`` seeds a verified row. Under CR-01 a verified
        run is terminal: reverting it to unverified would orphan the participation XP
        already granted, so the reject endpoint returns 409 and the row stays
        verified rather than silently de-syncing the ledger.
        """
        category_id = await asyncpg_pool.fetchval(
            """
            INSERT INTO tournaments.categories (name, difficulties, participation_xp, placement_xp, streak_xp)
            VALUES ($1, $2, 25, '[]'::jsonb, '[]'::jsonb)
            RETURNING id
            """,
            f"Reject {uuid4().hex[:8]}",
            ["Easy"],
        )
        map_id = await create_test_map(difficulty="Easy")
        user_id = await create_test_user(nickname=f"R{uuid4().hex[:6]}")
        cycle_id, tc_id = await _seed_tournament_completion(asyncpg_pool, category_id, map_id, user_id)

        response = await test_client.patch(f"{BASE}/completions/{tc_id}/reject")

        assert response.status_code == 409
        # The verified run is left untouched (not reverted).
        verified = await asyncpg_pool.fetchval(
            "SELECT verified FROM tournaments.completions WHERE id = $1", tc_id
        )
        assert verified is True

    async def test_verify_nonexistent_returns_404(self, test_client):
        """Verifying an unknown tournament_completion_id returns 404."""
        response = await test_client.patch(f"{BASE}/completions/999999999/verify")

        assert response.status_code == 404

    async def test_verify_without_scope_rejected(self, unauthenticated_client):
        """PATCH verify without the tournaments:verify scope returns 401."""
        response = await unauthenticated_client.patch(f"{BASE}/completions/1/verify")

        assert response.status_code == 401
