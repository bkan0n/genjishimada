from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestCommunityEndpoints:
    """Tests for community statistics and leaderboard endpoints."""

    # =========================================================================
    # LEADERBOARD TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_leaderboard_default(self, test_client: AsyncTestClient[Litestar]):
        """Test getting leaderboard with default parameters."""
        response = await test_client.get("/api/v3/community/leaderboard")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Default page size is 10
        assert len(data) <= 10

    @pytest.mark.asyncio
    async def test_get_leaderboard_sort_by_xp(self, test_client: AsyncTestClient[Litestar]):
        """Test leaderboard sorted by XP amount."""
        response = await test_client.get("/api/v3/community/leaderboard?sort_column=xp_amount&sort_direction=desc")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should be sorted by xp_amount descending
        if len(data) > 1:
            assert data[0]["xp_amount"] >= data[1]["xp_amount"]

    @pytest.mark.asyncio
    async def test_get_leaderboard_filter_by_name(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering leaderboard by name."""
        response = await test_client.get("/api/v3/community/leaderboard?name=Shadow")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should only return users matching "Shadow"
        for user in data:
            assert "shadow" in user["nickname"].lower() or "shadow" in user["global_name"].lower()

    @pytest.mark.asyncio
    async def test_get_leaderboard_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test leaderboard pagination."""
        # Page 1
        response = await test_client.get("/api/v3/community/leaderboard?page_size=10&page_number=1")
        assert response.status_code == HTTP_200_OK
        page1_data = response.json()

        # Page 2
        response = await test_client.get("/api/v3/community/leaderboard?page_size=10&page_number=2")
        assert response.status_code == HTTP_200_OK
        page2_data = response.json()

        # Pages should be different (if there are enough users)
        if len(page1_data) > 0 and len(page2_data) > 0:
            assert page1_data[0]["id"] != page2_data[0]["id"]

    # =========================================================================
    # XP TIER STATISTICS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_players_per_xp_tier(self, test_client: AsyncTestClient[Litestar]):
        """Test getting player counts per XP tier."""
        response = await test_client.get("/api/v3/community/statistics/xp/players")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Each item should have tier info and count
        for tier in data:
            assert "tier" in tier
            assert "amount" in tier

    # =========================================================================
    # SKILL TIER STATISTICS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_players_per_skill_tier(self, test_client: AsyncTestClient[Litestar]):
        """Test getting player counts per skill rank."""
        response = await test_client.get("/api/v3/community/statistics/skill/players")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    # =========================================================================
    # MAP STATISTICS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_map_completion_statistics(self, test_client: AsyncTestClient[Litestar]):
        """Test getting completion time statistics for a map."""
        response = await test_client.get("/api/v3/community/statistics/maps/completions?code=1EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should have min/max/avg times if completions exist
        if data:
            assert "min" in data[0] or "max" in data[0] or "avg" in data[0]

    @pytest.mark.asyncio
    async def test_get_maps_per_difficulty(self, test_client: AsyncTestClient[Litestar]):
        """Test getting map counts per difficulty."""
        response = await test_client.get("/api/v3/community/statistics/maps/difficulty")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Each should have difficulty and count
        for item in data:
            assert "difficulty" in item or "count" in item

    @pytest.mark.asyncio
    async def test_get_popular_maps(self, test_client: AsyncTestClient[Litestar]):
        """Test getting popular maps by difficulty."""
        response = await test_client.get("/api/v3/community/statistics/maps/popular")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Top 5 maps per difficulty

    @pytest.mark.asyncio
    async def test_get_popular_creators(self, test_client: AsyncTestClient[Litestar]):
        """Test getting top creators by average quality."""
        response = await test_client.get("/api/v3/community/statistics/creators/popular")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Creators with ≥3 rated maps

    @pytest.mark.asyncio
    async def test_get_unarchived_map_count(self, test_client: AsyncTestClient[Litestar]):
        """Test getting unarchived map counts."""
        response = await test_client.get("/api/v3/community/statistics/maps/unarchived")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_total_map_count(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all map counts."""
        response = await test_client.get("/api/v3/community/statistics/maps/all")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    # =========================================================================
    # USER MAP PROGRESSION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_map_record_progression(self, test_client: AsyncTestClient[Litestar]):
        """Test getting user's record progression for a map."""
        response = await test_client.get("/api/v3/community/statistics/maps/1EASY/user/200")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Time-series of records

    @pytest.mark.asyncio
    async def test_get_map_record_progression_no_records(self, test_client: AsyncTestClient[Litestar]):
        """Test getting progression for user with no records."""
        response = await test_client.get("/api/v3/community/statistics/maps/1EASY/user/999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    # =========================================================================
    # TIME PLAYED STATISTICS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_time_played_per_rank(self, test_client: AsyncTestClient[Litestar]):
        """Test getting total playtime per rank."""
        response = await test_client.get("/api/v3/community/statistics/ranks/time-played")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Total seconds by base difficulty
