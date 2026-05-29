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
