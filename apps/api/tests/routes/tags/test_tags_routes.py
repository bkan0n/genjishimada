"""Integration tests for tags API routes."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.domain_tags]

GUILD_ID = 100000000000000001
OWNER_ID = 200000000000000001


class TestSearchRoute:
    """Test POST /api/v3/tags/search."""

    async def test_search_returns_201(self, test_client) -> None:
        response = await test_client.post(
            "/api/v3/tags/search",
            json={"guild_id": GUILD_ID},
        )
        assert response.status_code == 201
        data = response.json()
        assert "items" in data


class TestMutateRoute:
    """Test POST /api/v3/tags/mutate."""

    async def test_create_via_mutate(self, test_client) -> None:
        response = await test_client.post(
            "/api/v3/tags/mutate",
            json={
                "ops": [
                    {
                        "op": "create",
                        "guild_id": GUILD_ID,
                        "name": "route-test-tag",
                        "content": "hello from route test",
                        "owner_id": OWNER_ID,
                    }
                ]
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["results"]) == 1
        assert data["results"][0]["ok"] is True

    async def test_multiple_ops(self, test_client) -> None:
        response = await test_client.post(
            "/api/v3/tags/mutate",
            json={
                "ops": [
                    {
                        "op": "create",
                        "guild_id": GUILD_ID,
                        "name": "batch-route-tag",
                        "content": "batch",
                        "owner_id": OWNER_ID,
                    },
                    {
                        "op": "increment_usage",
                        "guild_id": GUILD_ID,
                        "name": "batch-route-tag",
                    },
                ]
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert len(data["results"]) == 2


class TestAutocompleteRoute:
    """Test POST /api/v3/tags/autocomplete."""

    async def test_autocomplete_returns_201(self, test_client) -> None:
        response = await test_client.post(
            "/api/v3/tags/autocomplete",
            json={"guild_id": GUILD_ID, "q": "test"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "items" in data

    async def test_autocomplete_empty_query(self, test_client) -> None:
        response = await test_client.post(
            "/api/v3/tags/autocomplete",
            json={"guild_id": GUILD_ID, "q": "  "},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["items"] == []
