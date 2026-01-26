"""Tests for v4 change requests routes."""

import pytest


class TestPermissionEndpoint:
    """Test GET /api/v4/change-requests/permission."""

    @pytest.mark.asyncio
    async def test_permission_check_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test permission endpoint returns 200."""
        response = await test_client.get(
            "/api/v4/change-requests/permission?thread_id=1000000001&user_id=100000000000000001&code=1EASY"
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, bool)


class TestCreateEndpoint:
    """Test POST /api/v4/change-requests/."""

    @pytest.mark.asyncio
    async def test_create_change_request_returns_201(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test creating change request returns 201."""
        response = await test_client.post(
            "/api/v4/change-requests/",
            json={
                "thread_id": 9000000001,
                "code": "1EASY",
                "user_id": 400,
                "content": "Test request",
                "change_request_type": "Difficulty Change",
                "creator_mentions": "100000000000000001",
            },
        )
        assert response.status_code == 201
