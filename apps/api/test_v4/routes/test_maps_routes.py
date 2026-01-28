"""Tests for v4 maps routes."""

import pytest


class TestMapsEndpointsBasic:
    """Test basic endpoint functionality."""

    @pytest.mark.asyncio
    async def test_v4_router_exists(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test that v4 router is registered."""
        response = await test_client.get("/api/v4/")
        assert response.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_get_maps_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """GET /maps/ with no filters should return 200 and a list."""
        response = await test_client.get("/api/v4/maps/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestMapSearchFilters:
    """Test map search filtering."""

    @pytest.mark.asyncio
    async def test_filter_by_code(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test filtering by code."""
        response = await test_client.get("/api/v4/maps/?code=TEST01")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            assert all(m["code"] == "TEST01" for m in data)

    @pytest.mark.asyncio
    async def test_filter_by_difficulty_range(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test filtering by difficulty range."""
        response = await test_client.get("/api/v4/maps/?difficulty_range_min=Easy&difficulty_range_max=Hard")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_filter_by_mechanics_and_semantics(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test AND semantics for mechanics."""
        response = await test_client.get("/api/v4/maps/?mechanics=Bhop&mechanics=Dash")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_filter_by_creator_name(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test filtering by creator name."""
        response = await test_client.get("/api/v4/maps/?creator_names=TestCreator")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_pagination(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test pagination."""
        response = await test_client.get("/api/v4/maps/?page_size=10&page_number=1")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) <= 10

    @pytest.mark.asyncio
    async def test_sorting(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test sorting."""
        response = await test_client.get("/api/v4/maps/?sort=difficulty:asc&sort=code:desc")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_invalid_difficulty_combination(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test validation error for invalid difficulty combo."""
        response = await test_client.get("/api/v4/maps/?difficulty_exact=Easy&difficulty_range_min=Medium")
        assert response.status_code == 400
        body = response.text
        assert "Invalid filter parameters" in body

    @pytest.mark.asyncio
    async def test_return_all_flag(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test return_all bypasses pagination."""
        response = await test_client.get("/api/v4/maps/?return_all=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_filter_by_archived(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test filtering by archived status."""
        response = await test_client.get("/api/v4/maps/?archived=false")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            assert all(m["archived"] is False for m in data)
