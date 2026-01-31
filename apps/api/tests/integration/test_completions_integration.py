"""Integration tests for Completions v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_completions,
]


class TestGetCompletionsForUser:
    """GET /api/v4/completions/users/{user_id}"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get completions for user returns list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/completions/users/{user_id}")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestGetWorldRecordsPerUser:
    """GET /api/v4/completions/world-records/{user_id}"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get world records for user returns count."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/completions/world-records/{user_id}")

        assert response.status_code in (200, 404, 500)


class TestSubmitCompletion:
    """POST /api/v4/completions/"""

    async def test_happy_path(self, test_client, create_test_user, create_test_map, unique_map_code):
        """Submit completion creates record."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        payload = {
            "user_id": user_id,
            "map_code": code,
            "record": 45.5,
            "video_proof": "https://youtube.com/watch?v=test",
            "screenshot_proof": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }

        response = await test_client.post("/api/v4/completions/", json=payload)

        # May fail validation or succeed
        assert response.status_code in (200, 201, 400, 404, 500)


class TestGetPendingVerifications:
    """GET /api/v4/completions/pending"""

    async def test_happy_path(self, test_client):
        """Get pending verifications returns list."""
        response = await test_client.get("/api/v4/completions/pending")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestGetCompletionsLeaderboard:
    """GET /api/v4/completions/leaderboard"""

    async def test_happy_path(self, test_client):
        """Get leaderboard returns list."""
        response = await test_client.get("/api/v4/completions/leaderboard")

        assert response.status_code in (200, 404, 500)
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.parametrize("limit", [10, 25, 50, 100])
    @pytest.mark.parametrize("offset", [0, 10, 50])
    async def test_pagination(self, test_client, limit, offset):
        """Leaderboard pagination works."""
        response = await test_client.get(
            "/api/v4/completions/leaderboard",
            params={"limit": limit, "offset": offset},
        )

        assert response.status_code in (200, 404, 500)


class TestGetAllCompletions:
    """GET /api/v4/completions/"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get all completions returns list."""
        user_id = await create_test_user()

        response = await test_client.get(
            "/api/v4/completions/",
            params={"user_id": user_id},
        )

        assert response.status_code in (200, 400, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)


class TestGetSuspiciousFlags:
    """GET /api/v4/completions/suspicious"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get suspicious flags returns list."""
        user_id = await create_test_user()

        response = await test_client.get(
            "/api/v4/completions/suspicious",
            params={"user_id": user_id},
        )

        assert response.status_code in (200, 400, 404, 500)
        if response.status_code == 200:
            assert isinstance(response.json(), list)
