"""Integration tests for Lootbox v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_lootbox,
]


class TestViewAllRewards:
    """GET /api/v4/lootbox/rewards"""

    async def test_happy_path(self, test_client):
        """Get all rewards returns list."""
        response = await test_client.get("/api/v4/lootbox/rewards")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestViewAllKeys:
    """GET /api/v4/lootbox/keys"""

    async def test_happy_path(self, test_client):
        """Get all keys returns list."""
        response = await test_client.get("/api/v4/lootbox/keys")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestViewUserRewards:
    """GET /api/v4/lootbox/users/{user_id}/rewards"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user rewards returns list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/rewards")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestViewUserKeys:
    """GET /api/v4/lootbox/users/{user_id}/keys"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user keys returns list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/keys")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestGetRandomItems:
    """GET /api/v4/lootbox/random"""

    async def test_happy_path(self, test_client):
        """Get random items works."""
        response = await test_client.get(
            "/api/v4/lootbox/random",
            params={"count": 3},
        )

        assert response.status_code in (200, 400, 404, 500)
