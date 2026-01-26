"""Tests for v4 completions routes."""

import pytest


class TestCompletionsReadEndpoints:
    """Basic read endpoint tests."""

    @pytest.mark.asyncio
    async def test_get_pending_verifications_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Pending verifications should return 200 and a list."""
        response = await test_client.get("/api/v4/completions/pending")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_world_records_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """World records endpoint should return 200 and a list."""
        response = await test_client.get("/api/v4/completions/world-records?user_id=1")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_user_completions_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """User completions endpoint should return 200 and a list."""
        response = await test_client.get("/api/v4/completions/?user_id=1")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_upvotes_from_message_id_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Upvote count endpoint should return 200 and an int."""
        response = await test_client.get("/api/v4/completions/upvoting/1")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, int)
