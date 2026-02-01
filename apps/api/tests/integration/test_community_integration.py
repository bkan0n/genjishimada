"""Integration tests for Community v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_community,
]


class TestGetCommunityLeaderboard:
    """GET /api/v4/community/leaderboard"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get leaderboard returns list with valid structure."""
        # Create test user to ensure data exists
        await create_test_user()

        response = await test_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Response may be empty or populated - validate structure if data exists
        if data:
            item = data[0]
            # Validate all expected fields exist
            assert "user_id" in item
            assert "nickname" in item
            assert "xp_amount" in item
            assert "prestige_level" in item
            assert "tier_name" in item
            assert "skill_rank" in item
            assert "raw_tier" in item
            assert "normalized_tier" in item
            assert "wr_count" in item
            assert "map_count" in item
            assert "playtest_count" in item
            assert "discord_tag" in item
            # Validate field types
            assert isinstance(item["user_id"], int)
            assert isinstance(item["xp_amount"], int)
            assert isinstance(item["prestige_level"], int)
            assert isinstance(item["tier_name"], str)
            assert isinstance(item["skill_rank"], str)
            assert isinstance(item["raw_tier"], int)
            assert isinstance(item["normalized_tier"], int)
            assert isinstance(item["wr_count"], int)
            assert isinstance(item["map_count"], int)
            assert isinstance(item["playtest_count"], int)
            assert isinstance(item["discord_tag"], str)

    async def test_requires_auth(self, unauthenticated_client):
        """Get leaderboard without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 1},
        )

        assert response.status_code == 401

    async def test_invalid_page_number_returns_400(self, test_client):
        """Get leaderboard with page_number < 1 returns 400."""
        response = await test_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 0},
        )

        assert response.status_code == 400

    async def test_invalid_sort_column_returns_400(self, test_client):
        """Get leaderboard with invalid sort_column returns 400."""
        response = await test_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 1, "sort_column": "invalid_column"},
        )

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "sort_column",
        [
            "xp_amount",
            "nickname",
            "prestige_level",
            "wr_count",
            "map_count",
            "playtest_count",
            "discord_tag",
            "skill_rank",
        ],
    )
    async def test_all_sort_columns(self, test_client, create_test_user, sort_column):
        """All sort_column values work correctly."""
        await create_test_user()

        response = await test_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 1, "sort_column": sort_column},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.parametrize("sort_direction", ["asc", "desc"])
    async def test_sort_directions(self, test_client, create_test_user, sort_direction):
        """Both sort_direction values work correctly."""
        await create_test_user()

        response = await test_client.get(
            "/api/v4/community/leaderboard",
            params={"page_size": 10, "page_number": 1, "sort_direction": sort_direction},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestGetPlayersPerXPTier:
    """GET /api/v4/community/statistics/xp/players"""

    async def test_happy_path(self, test_client):
        """Get players per XP tier returns list."""
        response = await test_client.get("/api/v4/community/statistics/xp/players")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "tier" in item
            assert "amount" in item
            assert isinstance(item["tier"], str)
            assert isinstance(item["amount"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get players per XP tier without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/xp/players")

        assert response.status_code == 401


class TestGetPlayersPerSkillTier:
    """GET /api/v4/community/statistics/skill/players"""

    async def test_happy_path(self, test_client):
        """Get players per skill tier returns list."""
        response = await test_client.get("/api/v4/community/statistics/skill/players")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "tier" in item
            assert "amount" in item
            assert isinstance(item["tier"], str)
            assert isinstance(item["amount"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get players per skill tier without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/skill/players")

        assert response.status_code == 401


class TestGetMapCompletionStatistics:
    """GET /api/v4/community/statistics/maps/completions"""

    async def test_happy_path(self, test_client, create_test_map, create_test_user, create_test_completion, unique_map_code):
        """Get map completion stats returns statistics."""
        # Create map with completion
        code = unique_map_code
        map_id = await create_test_map(code=code)
        user_id = await create_test_user()
        await create_test_completion(user_id=user_id, map_id=map_id, screenshot="https://example.com/screenshot.png")

        response = await test_client.get(
            "/api/v4/community/statistics/maps/completions",
            params={"code": code},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_requires_auth(self, unauthenticated_client):
        """Get map completion stats without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/community/statistics/maps/completions",
            params={"code": "TEST01"},
        )

        assert response.status_code == 401

    async def test_invalid_code_format_returns_400(self, test_client):
        """Get map completion stats with invalid code format returns 400."""
        response = await test_client.get(
            "/api/v4/community/statistics/maps/completions",
            params={"code": "abc"},  # Lowercase, too short
        )

        assert response.status_code == 400


class TestGetMapsPerDifficulty:
    """GET /api/v4/community/statistics/maps/difficulty"""

    async def test_happy_path(self, test_client):
        """Get maps per difficulty returns list."""
        response = await test_client.get("/api/v4/community/statistics/maps/difficulty")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "difficulty" in item
            assert "amount" in item
            assert isinstance(item["difficulty"], str)
            assert isinstance(item["amount"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get maps per difficulty without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/maps/difficulty")

        assert response.status_code == 401


class TestGetPopularMaps:
    """GET /api/v4/community/statistics/maps/popular"""

    async def test_happy_path(self, test_client):
        """Get popular maps returns list."""
        response = await test_client.get("/api/v4/community/statistics/maps/popular")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "code" in item
            assert "difficulty" in item
            assert isinstance(item["code"], str)
            assert isinstance(item["difficulty"], str)

    async def test_requires_auth(self, unauthenticated_client):
        """Get popular maps without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/maps/popular")

        assert response.status_code == 401


class TestGetPopularCreators:
    """GET /api/v4/community/statistics/creators/popular"""

    async def test_happy_path(self, test_client):
        """Get popular creators returns list."""
        response = await test_client.get("/api/v4/community/statistics/creators/popular")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "creator_name" in item
            assert "average_quality" in item
            assert isinstance(item["creator_name"], str)

    async def test_requires_auth(self, unauthenticated_client):
        """Get popular creators without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/creators/popular")

        assert response.status_code == 401


class TestGetUnarchivedMapCount:
    """GET /api/v4/community/statistics/maps/unarchived"""

    async def test_happy_path(self, test_client):
        """Get unarchived map count returns list."""
        response = await test_client.get("/api/v4/community/statistics/maps/unarchived")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "map_name" in item
            assert "amount" in item
            assert isinstance(item["map_name"], str)
            assert isinstance(item["amount"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get unarchived map count without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/maps/unarchived")

        assert response.status_code == 401


class TestGetTotalMapCount:
    """GET /api/v4/community/statistics/maps/all"""

    async def test_happy_path(self, test_client):
        """Get total map count returns list."""
        response = await test_client.get("/api/v4/community/statistics/maps/all")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "map_name" in item
            assert "amount" in item
            assert isinstance(item["map_name"], str)
            assert isinstance(item["amount"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get total map count without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/maps/all")

        assert response.status_code == 401


class TestGetMapRecordProgression:
    """GET /api/v4/community/statistics/maps/{code}/user/{user_id}"""

    async def test_happy_path(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Get map record progression returns list."""
        code = unique_map_code
        await create_test_map(code=code)
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/community/statistics/maps/{code}/user/{user_id}"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # May be empty if user has no completions for this map

    async def test_requires_auth(self, unauthenticated_client):
        """Get map record progression without auth returns 401."""
        response = await unauthenticated_client.get(
            "/api/v4/community/statistics/maps/TEST01/user/999999999"
        )

        assert response.status_code == 401

    async def test_invalid_code_format_returns_400(self, test_client):
        """Get map record progression with invalid code format returns 400."""
        response = await test_client.get(
            "/api/v4/community/statistics/maps/xyz/user/999999999"  # Lowercase
        )

        assert response.status_code == 400


class TestGetTimePlayedPerRank:
    """GET /api/v4/community/statistics/ranks/time-played"""

    async def test_happy_path(self, test_client):
        """Get time played per rank returns list."""
        response = await test_client.get("/api/v4/community/statistics/ranks/time-played")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "difficulty" in item
            assert "total_seconds" in item
            assert isinstance(item["difficulty"], str)
            assert isinstance(item["total_seconds"], (int, float))

    async def test_requires_auth(self, unauthenticated_client):
        """Get time played per rank without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/community/statistics/ranks/time-played")

        assert response.status_code == 401
