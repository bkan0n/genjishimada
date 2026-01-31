"""Integration tests for Maps v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.

Note: Maps controller has many endpoints. This file covers the core CRUD operations
and critical search functionality.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_maps,
]


class TestSearchMaps:
    """GET /api/v4/maps/"""

    async def test_happy_path(self, test_client):
        """Search maps returns list with valid structure."""
        response = await test_client.get("/api/v4/maps/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate map structure if any maps exist
        for map_obj in data:
            assert "id" in map_obj
            assert "code" in map_obj
            assert "map_name" in map_obj
            assert "category" in map_obj
            assert "checkpoints" in map_obj
            assert isinstance(map_obj["checkpoints"], int)
            assert "difficulty" in map_obj
            assert "created_at" in map_obj

    async def test_requires_auth(self, unauthenticated_client):
        """Search maps without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/")

        assert response.status_code == 401

    async def test_with_code_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by code returns matching map with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get("/api/v4/maps/", params={"code": code})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            map_obj = data[0]
            assert map_obj["code"] == code
            assert "id" in map_obj
            assert "map_name" in map_obj
            assert "checkpoints" in map_obj
            assert isinstance(map_obj["checkpoints"], int)

    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    @pytest.mark.parametrize("page_number", [1, 2])
    async def test_pagination_variants(self, test_client, page_size, page_number):
        """Pagination parameters work without 500s."""
        response = await test_client.get(
            "/api/v4/maps/",
            params={"page_size": page_size, "page_number": page_number},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.parametrize("archived", [True, False])
    @pytest.mark.parametrize("hidden", [True, False])
    @pytest.mark.parametrize("official", [True, False])
    async def test_bool_filter_combinations(self, test_client, archived, hidden, official):
        """Boolean filters serialize correctly."""
        response = await test_client.get(
            "/api/v4/maps/",
            params={"archived": archived, "hidden": hidden, "official": official},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestGetPartialMap:
    """GET /api/v4/maps/{code}/partial"""

    #@pytest.mark.xfail(reason="BUG: Returns 500 (msgspec.ValidationError) - MapPartialResponse missing required fields in query result")
    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_playtest):
        """Get map by code returns map data."""
        code = unique_map_code
        # create_test_map fixture uses default difficulty from conftest
        map_id = await create_test_map(code=code, checkpoints=15, difficulty="Medium")
        await create_test_playtest(map_id=map_id)
        response = await test_client.get(f"/api/v4/maps/{code}/partial")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code
        assert data["checkpoints"] == 15

    async def test_non_existent_map_returns_404(self, test_client):
        """Non-existent map code returns 404."""
        response = await test_client.get("/api/v4/maps/NONEXISTENT/partial")

        assert response.status_code == 404

    async def test_requires_auth(self, unauthenticated_client):
        """Get partial map without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/ZZZZZZ/partial")

        assert response.status_code == 401


class TestCreateMap:
    """POST /api/v4/maps/"""

    #@pytest.mark.xfail(reason="BUG: create_playtest_meta_partial passes difficulty string instead of raw_difficulty numeric - asyncpg.exceptions.InvalidTextRepresentationError")
    async def test_happy_path(self, test_client, unique_map_code, create_test_user):
        """Create map returns job response."""
        user_id = await create_test_user()
        code = unique_map_code

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Classic",  # Valid MapCategory
            "creators": [{"id": user_id, "is_primary": True}],  # Correct format
            "difficulty": "Medium",
        }

        response = await test_client.post("/api/v4/maps/", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert "data" in data
        assert data["data"]["code"] == code

    async def test_duplicate_code_returns_error(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Creating map with duplicate code returns error."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Ranked",
            "creator_ids": [user_id],
        }

        response = await test_client.post("/api/v4/maps/", json=payload)

        assert response.status_code == 400

    async def test_requires_auth(self, unauthenticated_client, unique_map_code):
        """Create map without auth returns 401."""
        payload = {
            "code": unique_map_code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Ranked",
        }

        response = await unauthenticated_client.post("/api/v4/maps/", json=payload)

        assert response.status_code == 401


class TestUpdateMap:
    """PATCH /api/v4/maps/{code}"""

    async def test_update_checkpoints(self, test_client, create_test_map, unique_map_code):
        """Update map checkpoints."""
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        response = await test_client.patch(
            f"/api/v4/maps/{code}",
            json={"checkpoints": 25},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code
        assert data["checkpoints"] == 25

    async def test_update_multiple_fields(self, test_client, create_test_map, unique_map_code):
        """Update multiple map fields."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v4/maps/{code}",
            json={
                "checkpoints": 30,
                "hidden": True,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code
        assert data["checkpoints"] == 30
        assert data["hidden"] is True

    async def test_non_existent_map_returns_404(self, test_client):
        """Updating non-existent map should return 404."""
        response = await test_client.patch(
            "/api/v4/maps/ZZZZZZ",
            json={"checkpoints": 10},
        )

        assert response.status_code == 404

    async def test_requires_auth(self, unauthenticated_client):
        """Update map without auth returns 401."""
        response = await unauthenticated_client.patch(
            "/api/v4/maps/ZZZZZZ",
            json={"checkpoints": 10},
        )

        assert response.status_code == 401


class TestCheckCodeExists:
    """GET /api/v4/maps/{code}/exists"""

    async def test_existing_code(self, test_client, create_test_map, unique_map_code):
        """Existing code returns true with correct type."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v4/maps/{code}/exists")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        assert result is True

    async def test_non_existent_code(self, test_client):
        """Non-existent code returns false with correct type."""
        response = await test_client.get("/api/v4/maps/ZZZZZZ/exists")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        assert result is False

    async def test_requires_auth(self, unauthenticated_client):
        """Check code exists without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/ZZZZZZ/exists")

        assert response.status_code == 401


class TestGetGuides:
    """GET /api/v4/maps/{code}/guides"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get guides for map returns list with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v4/maps/{code}/guides")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate guide structure if any guides exist
        for guide in data:
            assert "user_id" in guide
            assert isinstance(guide["user_id"], int)
            assert "url" in guide
            assert isinstance(guide["url"], str)
            assert "created_at" in guide

    async def test_requires_auth(self, unauthenticated_client):
        """Get guides without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/ZZZZZZ/guides")

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client):
        """Get guides for non-existent map returns 404."""
        response = await test_client.get("/api/v4/maps/ZZZZZZ/guides")

        assert response.status_code == 404


class TestCreateGuide:
    """POST /api/v4/maps/{code}/guides"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Create guide returns guide data."""
        code = unique_map_code
        await create_test_map(code=code)
        user_id = await create_test_user()

        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": user_id,
            "guide_type": "video",
        }

        response = await test_client.post(f"/api/v4/maps/{code}/guides", json=payload)

        assert response.status_code == 201

    async def test_requires_auth(self, unauthenticated_client):
        """Create guide without auth returns 401."""
        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": 999,
        }

        response = await unauthenticated_client.post("/api/v4/maps/ZZZZZZ/guides", json=payload)

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client, create_test_user):
        """Create guide for non-existent map returns 404."""
        user_id = await create_test_user()
        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": user_id,
        }

        response = await test_client.post("/api/v4/maps/ZZZZZZ/guides", json=payload)

        assert response.status_code == 404

    #@pytest.mark.xfail(reason="BUG: Returns 400 (DI provider issue) before checking for duplicates")
    async def test_duplicate_guide_returns_409(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Creating duplicate guide returns 409."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": user_id,
        }

        # First guide
        response1 = await test_client.post(f"/api/v4/maps/{code}/guides", json=payload)
        assert response1.status_code == 201

        # Duplicate guide (same user + map)
        response2 = await test_client.post(f"/api/v4/maps/{code}/guides", json=payload)

        assert response2.status_code == 409


class TestUpdateGuide:
    """PATCH /api/v4/maps/{code}/guides/{user_id}"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Update guide for non-existent map returns 404."""
        response = await test_client.patch(
            "/api/v4/maps/ZZZZZZ/guides/999",
            params={"url": "https://youtube.com/watch?v=updated"},
        )

        assert response.status_code == 404

    async def test_non_existent_guide_returns_404(self, test_client, create_test_map, unique_map_code):
        """Update non-existent guide returns 404."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v4/maps/{code}/guides/999",
            params={"url": "https://youtube.com/watch?v=updated"},
        )

        assert response.status_code == 404


class TestDeleteGuide:
    """DELETE /api/v4/maps/{code}/guides/{user_id}"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Delete guide for non-existent map returns 404."""
        response = await test_client.delete("/api/v4/maps/ZZZZZZ/guides/999")

        assert response.status_code == 404

    async def test_non_existent_guide_returns_404(self, test_client, create_test_map, unique_map_code):
        """Delete non-existent guide returns 404."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.delete(f"/api/v4/maps/{code}/guides/999")

        assert response.status_code == 404


class TestGetMastery:
    """GET /api/v4/maps/mastery"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get mastery data returns info."""
        user_id = await create_test_user()

        response = await test_client.get("/api/v4/maps/mastery", params={"user_id": user_id})

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_requires_auth(self, unauthenticated_client):
        """Get mastery without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/mastery", params={"user_id": 999})

        assert response.status_code == 401


class TestUpdateMastery:
    """POST /api/v4/maps/mastery"""

    async def test_happy_path(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Create/update mastery."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, map_name="Nepal")

        payload = {
            "user_id": user_id,  # Required field
            "map_name": "Nepal",  # Required field (OverwatchMap literal)
            "level": "gold",  # Required field
        }

        response = await test_client.post("/api/v4/maps/mastery", json=payload)

        assert response.status_code == 201
        data = response.json()
        if data is not None:
            assert "map_name" in data
            assert data["map_name"] == "Nepal"

    async def test_requires_auth(self, unauthenticated_client):
        """Update mastery without auth returns 401."""
        payload = {
            "user_id": 999,
            "map_name": "Nepal",
            "level": "bronze",
        }

        response = await unauthenticated_client.post("/api/v4/maps/mastery", json=payload)

        assert response.status_code == 401


class TestSetArchiveStatus:
    """PATCH /api/v4/maps/archive"""

    async def test_archive_map(self, test_client, create_test_map, unique_map_code):
        """Archive a map and verify response."""
        code = unique_map_code
        await create_test_map(code=code, archived=False)

        response = await test_client.patch(
            "/api/v4/maps/archive",
            json={"codes": [code], "status": "Archive"},
        )

        assert response.status_code == 200
        # Endpoint returns None (JSON null) with 200 status
        assert response.json() is None

    async def test_unarchive_map(self, test_client, create_test_map, unique_map_code):
        """Unarchive a map and verify response."""
        code = unique_map_code
        await create_test_map(code=code, archived=True)

        response = await test_client.patch(
            "/api/v4/maps/archive",
            json={"codes": [code], "status": "Unarchived"},
        )

        assert response.status_code == 200
        # Endpoint returns None (JSON null) with 200 status
        assert response.json() is None

    async def test_requires_auth(self, unauthenticated_client):
        """Set archive status without auth returns 401."""
        response = await unauthenticated_client.patch(
            "/api/v4/maps/archive",
            json={"codes": ["ZZZZZZ"], "status": "Archive"},
        )

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client):
        """Archive non-existent map returns 404."""
        response = await test_client.patch(
            "/api/v4/maps/archive",
            json={"codes": ["ZZZZZZ"], "status": "Archive"},
        )

        assert response.status_code == 404


class TestConvertToLegacy:
    """POST /api/v4/maps/{code}/legacy"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Convert non-existent map to legacy returns 404."""
        response = await test_client.post(
            "/api/v4/maps/ZZZZZZ/legacy",
            params={"reason": "Map is outdated"},
        )

        assert response.status_code == 404


class TestOverrideQualityVotes:
    """POST /api/v4/maps/{code}/quality"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Override quality for non-existent map returns 404."""
        response = await test_client.post(
            "/api/v4/maps/ZZZZZZ/quality",
            json={"value": 5},
        )

        assert response.status_code == 404


class TestSendToPlaytest:
    """POST /api/v4/maps/{code}/playtest"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Send non-existent map to playtest returns 404."""
        response = await test_client.post(
            "/api/v4/maps/ZZZZZZ/playtest",
            json={"initial_difficulty": "Medium"},
        )

        assert response.status_code == 404


class TestGetAffectedUsers:
    """GET /api/v4/maps/{code}/affected"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Get affected users for non-existent map returns 404."""
        response = await test_client.get("/api/v4/maps/ZZZZZZ/affected")

        assert response.status_code == 404


class TestGetMapPlot:
    """GET /api/v4/maps/{code}/plot"""

    async def test_non_existent_map_returns_404(self, test_client):
        """Get plot for non-existent map returns 404."""
        response = await test_client.get("/api/v4/maps/ZZZZZZ/plot")

        assert response.status_code == 404


class TestGetTrendingMaps:
    """GET /api/v4/maps/trending"""

    async def test_happy_path(self, test_client):
        """Get trending maps returns list with valid structure."""
        response = await test_client.get("/api/v4/maps/trending")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate trending map structure if any exist
        for trending_map in data:
            assert "code" in trending_map
            assert "map_name" in trending_map
            assert "score" in trending_map
            assert isinstance(trending_map["score"], (int, float))
            assert "difficulty" in trending_map

    async def test_requires_auth(self, unauthenticated_client):
        """Get trending maps without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/maps/trending")

        assert response.status_code == 401
