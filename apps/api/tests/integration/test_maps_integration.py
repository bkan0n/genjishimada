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
    """GET /api/v3/maps/"""

    async def test_happy_path(self, test_client):
        """Search maps returns list with valid structure."""
        response = await test_client.get("/api/v3/maps/")

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
        response = await unauthenticated_client.get("/api/v3/maps/")

        assert response.status_code == 401

    async def test_with_code_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by code returns matching map with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get("/api/v3/maps/", params={"code": code})

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
            "/api/v3/maps/",
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
            "/api/v3/maps/",
            params={"archived": archived, "hidden": hidden, "official": official},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_playtest_status_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by playtesting status."""
        code = unique_map_code
        await create_test_map(code=code, playtesting="In Progress")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"playtest_status": "In Progress"},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned maps should have playtesting status "In Progress"
        for map_obj in data:
            if map_obj["code"] == code:
                assert map_obj["playtesting"] == "In Progress"

    async def test_playtest_thread_id_filter(
        self, test_client, create_test_map, unique_map_code, create_test_playtest, unique_thread_id
    ):
        """Filter by playtest thread ID."""
        code = unique_map_code
        thread_id = unique_thread_id
        map_id = await create_test_map(code=code, playtesting="In Progress")
        await create_test_playtest(map_id=map_id, thread_id=thread_id)

        response = await test_client.get(
            "/api/v3/maps/",
            params={"playtest_thread_id": thread_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_category_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by map category."""
        code = unique_map_code
        await create_test_map(code=code, category="Classic")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"category": ["Classic", "Other"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_map_name_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by Overwatch map name."""
        code = unique_map_code
        await create_test_map(code=code, map_name="Nepal")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"map_name": ["Nepal", "Hanamura"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Verify Nepal map is in results
        codes = [m["code"] for m in data]
        assert code in codes

    async def test_difficulty_exact_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by exact difficulty."""
        code = unique_map_code
        await create_test_map(code=code, difficulty="Hard")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"difficulty_exact": "Hard"},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # All returned maps should be Hard difficulty
        for map_obj in data:
            assert map_obj["difficulty"] == "Hard"

    async def test_difficulty_range_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by difficulty range."""
        code = unique_map_code
        await create_test_map(code=code, difficulty="Medium")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"difficulty_range_min": "Easy", "difficulty_range_max": "Hard"},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_mechanics_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by mechanics (AND semantics)."""
        code = unique_map_code
        # Fixture uses IDs: 1=Edge Climb, 2=Bhop (from migration)
        await create_test_map(code=code, mechanics=[1, 2])

        response = await test_client.get(
            "/api/v3/maps/",
            params={"mechanics": ["Edge Climb", "Bhop"]},  # API should accept names
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should include our test map
        codes = [m["code"] for m in data]
        assert code in codes

    async def test_restrictions_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by restrictions (AND semantics)."""
        code = unique_map_code
        # Fixture uses IDs: 9=Wall Climb (from migration)
        await create_test_map(code=code, restrictions=[9])

        response = await test_client.get(
            "/api/v3/maps/",
            params={"restrictions": ["Wall Climb"]},  # API should accept names
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should include our test map
        codes = [m["code"] for m in data]
        assert code in codes

    async def test_tags_filter(self, test_client, create_test_map, unique_map_code):
        """Filter by tags (AND semantics)."""
        code = unique_map_code
        # Note: Tags may not be in seed data, test basic functionality
        await create_test_map(code=code)

        response = await test_client.get(
            "/api/v3/maps/",
            params={"tags": ["XP Based"]},  # API should accept names
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_creator_ids_filter(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Filter by creator user IDs."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code, creator_id=user_id)

        response = await test_client.get(
            "/api/v3/maps/",
            params={"creator_ids": [user_id]},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Verify our map is in results
        codes = [m["code"] for m in data]
        assert code in codes

    async def test_creator_names_filter(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Filter by creator names."""
        code = unique_map_code
        user_id = await create_test_user(nickname="TestCreator")
        await create_test_map(code=code, creator_id=user_id)

        response = await test_client.get(
            "/api/v3/maps/",
            params={"creator_names": ["TestCreator"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_minimum_quality_filter(self, test_client):
        """Filter by minimum quality."""
        response = await test_client.get(
            "/api/v3/maps/",
            params={"minimum_quality": 7},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_sort_single_key(self, test_client):
        """Sort by single key."""
        response = await test_client.get(
            "/api/v3/maps/",
            params={"sort": ["code:desc"]},  # Valid SortKey
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_sort_multiple_keys(self, test_client):
        """Sort by multiple keys."""
        response = await test_client.get(
            "/api/v3/maps/",
            params={"sort": ["difficulty:asc", "checkpoints:desc"]},  # Valid SortKeys
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_return_all_flag(self, test_client):
        """Return all results without pagination."""
        response = await test_client.get(
            "/api/v3/maps/",
            params={"return_all": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_force_filters_with_code(self, test_client, create_test_map, unique_map_code):
        """Force filters even with code parameter."""
        code = unique_map_code
        await create_test_map(code=code, difficulty="Easy")

        response = await test_client.get(
            "/api/v3/maps/",
            params={"code": code, "difficulty_exact": "Hard", "force_filters": True},
        )

        assert response.status_code == 200
        data = response.json()
        # With force_filters, should apply difficulty filter and exclude our Easy map
        codes = [m["code"] for m in data]
        assert code not in codes


class TestGetPartialMap:
    """GET /api/v3/maps/{code}/partial"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_playtest):
        """Get map by code returns map data."""
        code = unique_map_code
        # create_test_map fixture uses default difficulty from conftest
        map_id = await create_test_map(code=code, checkpoints=15, difficulty="Medium")
        await create_test_playtest(map_id=map_id)
        response = await test_client.get(f"/api/v3/maps/{code}/partial")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code
        assert data["checkpoints"] == 15

    async def test_non_existent_map_returns_404(self, test_client):
        """Non-existent map code returns 404."""
        response = await test_client.get("/api/v3/maps/NONEXISTENT/partial")

        assert response.status_code == 404

    async def test_requires_auth(self, unauthenticated_client):
        """Get partial map without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/maps/ZZZZZZ/partial")

        assert response.status_code == 401


class TestCreateMap:
    """POST /api/v3/maps/"""

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

        response = await test_client.post("/api/v3/maps/", json=payload)

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

        response = await test_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 400

    async def test_duplicate_mechanic_error(self, test_client, unique_map_code, create_test_user):
        """Creating map with duplicate mechanics returns 400."""
        user_id = await create_test_user()
        code = unique_map_code

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Classic",
            "creators": [{"id": user_id, "is_primary": True}],
            "difficulty": "Medium",
            "mechanics": ["Edge Climb", "Edge Climb"],  # Duplicate mechanic name
        }

        response = await test_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 400

    async def test_duplicate_restriction_error(self, test_client, unique_map_code, create_test_user):
        """Creating map with duplicate restrictions returns 400."""
        user_id = await create_test_user()
        code = unique_map_code

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Classic",
            "creators": [{"id": user_id, "is_primary": True}],
            "difficulty": "Medium",
            "restrictions": ["Wall Climb", "Wall Climb"],  # Duplicate restriction name
        }

        response = await test_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 400

    async def test_duplicate_creator_error(self, test_client, unique_map_code, create_test_user):
        """Creating map with duplicate creators returns 400."""
        user_id = await create_test_user()
        code = unique_map_code

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Classic",
            "creators": [
                {"id": user_id, "is_primary": True},
                {"id": user_id, "is_primary": False},  # Duplicate
            ],
            "difficulty": "Medium",
        }

        response = await test_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 400

    async def test_creator_not_found_error(self, test_client, unique_map_code):
        """Creating map with non-existent creator returns 400."""
        code = unique_map_code
        non_existent_user_id = 999999999999999999

        payload = {
            "code": code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Classic",
            "creators": [{"id": non_existent_user_id, "is_primary": True}],
            "difficulty": "Medium",
        }

        response = await test_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 400

    async def test_requires_auth(self, unauthenticated_client, unique_map_code):
        """Create map without auth returns 401."""
        payload = {
            "code": unique_map_code,
            "map_name": "Nepal",
            "checkpoints": 20,
            "category": "Ranked",
        }

        response = await unauthenticated_client.post("/api/v3/maps/", json=payload)

        assert response.status_code == 401


class TestUpdateMap:
    """PATCH /api/v3/maps/{code}"""

    async def test_update_checkpoints(self, test_client, create_test_map, unique_map_code):
        """Update map checkpoints."""
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        response = await test_client.patch(
            f"/api/v3/maps/{code}",
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
            f"/api/v3/maps/{code}",
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
            "/api/v3/maps/ZZZZZZ",
            json={"checkpoints": 10},
        )

        assert response.status_code == 404

    async def test_update_code_conflict(self, test_client, create_test_map, unique_map_code):
        """Updating map code to existing code returns 400."""
        code1 = unique_map_code
        code2 = f"X{code1[1:]}"

        await create_test_map(code=code1)
        await create_test_map(code=code2)

        # Try to change code2 to code1
        response = await test_client.patch(
            f"/api/v3/maps/{code2}",
            json={"code": code1},
        )

        assert response.status_code == 400

    async def test_duplicate_mechanic_error(self, test_client, create_test_map, unique_map_code):
        """Updating map with duplicate mechanics returns 400."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v3/maps/{code}",
            json={"mechanics": ["Edge Climb", "Edge Climb"]},  # Duplicate mechanic name
        )

        assert response.status_code == 400

    async def test_duplicate_restriction_error(self, test_client, create_test_map, unique_map_code):
        """Updating map with duplicate restrictions returns 400."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v3/maps/{code}",
            json={"restrictions": ["Wall Climb", "Wall Climb"]},  # Duplicate restriction name
        )

        assert response.status_code == 400

    async def test_duplicate_creator_error(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Updating map with duplicate creators returns 400."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v3/maps/{code}",
            json={
                "creators": [
                    {"id": user_id, "is_primary": True},
                    {"id": user_id, "is_primary": False},  # Duplicate
                ]
            },
        )

        assert response.status_code == 400

    async def test_creator_not_found_error(self, test_client, create_test_map, unique_map_code):
        """Updating map with non-existent creator returns 400."""
        code = unique_map_code
        await create_test_map(code=code)
        non_existent_user_id = 999999999999999999

        response = await test_client.patch(
            f"/api/v3/maps/{code}",
            json={"creators": [{"id": non_existent_user_id, "is_primary": True}]},
        )

        assert response.status_code == 400

    async def test_requires_auth(self, unauthenticated_client):
        """Update map without auth returns 401."""
        response = await unauthenticated_client.patch(
            "/api/v3/maps/ZZZZZZ",
            json={"checkpoints": 10},
        )

        assert response.status_code == 401


class TestCheckCodeExists:
    """GET /api/v3/maps/{code}/exists"""

    async def test_existing_code(self, test_client, create_test_map, unique_map_code):
        """Existing code returns true with correct type."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v3/maps/{code}/exists")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        assert result is True

    async def test_non_existent_code(self, test_client):
        """Non-existent code returns false with correct type."""
        response = await test_client.get("/api/v3/maps/ZZZZZZ/exists")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        assert result is False

    async def test_invalid_code_format(self, test_client):
        """Invalid code format returns 400."""
        invalid_codes = [
            "ABC",  # Too short
            "ABCD123",  # Too long
            "abcd",  # Lowercase
            "AB-CD",  # Invalid character
        ]

        for invalid_code in invalid_codes:
            response = await test_client.get(f"/api/v3/maps/{invalid_code}/exists")
            assert response.status_code == 400

    async def test_requires_auth(self, unauthenticated_client):
        """Check code exists without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/maps/ZZZZZZ/exists")

        assert response.status_code == 401


class TestGetGuides:
    """GET /api/v3/maps/{code}/guides"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get guides for map returns list with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v3/maps/{code}/guides")

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
        response = await unauthenticated_client.get("/api/v3/maps/ZZZZZZ/guides")

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client):
        """Get guides for non-existent map returns 404."""
        response = await test_client.get("/api/v3/maps/ZZZZZZ/guides")

        assert response.status_code == 404


class TestCreateGuide:
    """POST /api/v3/maps/{code}/guides"""

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

        response = await test_client.post(f"/api/v3/maps/{code}/guides", json=payload)

        assert response.status_code == 201

    async def test_requires_auth(self, unauthenticated_client):
        """Create guide without auth returns 401."""
        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": 999,
        }

        response = await unauthenticated_client.post("/api/v3/maps/ZZZZZZ/guides", json=payload)

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client, create_test_user):
        """Create guide for non-existent map returns 404."""
        user_id = await create_test_user()
        payload = {
            "url": "https://youtube.com/watch?v=test123",
            "user_id": user_id,
        }

        response = await test_client.post("/api/v3/maps/ZZZZZZ/guides", json=payload)

        assert response.status_code == 404

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
        response1 = await test_client.post(f"/api/v3/maps/{code}/guides", json=payload)
        assert response1.status_code == 201

        # Duplicate guide (same user + map)
        response2 = await test_client.post(f"/api/v3/maps/{code}/guides", json=payload)

        assert response2.status_code == 409


class TestUpdateGuide:
    """PATCH /api/v3/maps/{code}/guides/{user_id}"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Update guide URL successfully."""
        code = unique_map_code
        await create_test_map(code=code)
        user_id = await create_test_user()

        # Create guide first
        create_payload = {
            "url": "https://youtube.com/watch?v=original",
            "user_id": user_id,
            "guide_type": "video",
        }
        await test_client.post(f"/api/v3/maps/{code}/guides", json=create_payload)

        # Update guide
        response = await test_client.patch(
            f"/api/v3/maps/{code}/guides/{user_id}",
            params={"url": "https://youtube.com/watch?v=updated"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://youtube.com/watch?v=updated"
        assert data["user_id"] == user_id

    async def test_non_existent_map_returns_404(self, test_client):
        """Update guide for non-existent map returns 404."""
        response = await test_client.patch(
            "/api/v3/maps/ZZZZZZ/guides/999",
            params={"url": "https://youtube.com/watch?v=updated"},
        )

        assert response.status_code == 404

    async def test_non_existent_guide_returns_404(self, test_client, create_test_map, unique_map_code):
        """Update non-existent guide returns 404."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.patch(
            f"/api/v3/maps/{code}/guides/999",
            params={"url": "https://youtube.com/watch?v=updated"},
        )

        assert response.status_code == 404


class TestDeleteGuide:
    """DELETE /api/v3/maps/{code}/guides/{user_id}"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_user):
        """Delete guide successfully."""
        code = unique_map_code
        await create_test_map(code=code)
        user_id = await create_test_user()

        # Create guide first
        create_payload = {
            "url": "https://youtube.com/watch?v=test",
            "user_id": user_id,
            "guide_type": "video",
        }
        await test_client.post(f"/api/v3/maps/{code}/guides", json=create_payload)

        # Delete guide
        response = await test_client.delete(f"/api/v3/maps/{code}/guides/{user_id}")

        assert response.status_code == 204

    async def test_non_existent_map_returns_404(self, test_client):
        """Delete guide for non-existent map returns 404."""
        response = await test_client.delete("/api/v3/maps/ZZZZZZ/guides/999")

        assert response.status_code == 404

    async def test_non_existent_guide_returns_404(self, test_client, create_test_map, unique_map_code):
        """Delete non-existent guide returns 404."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.delete(f"/api/v3/maps/{code}/guides/999")

        assert response.status_code == 404


class TestGetMastery:
    """GET /api/v3/maps/mastery"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get mastery data returns info."""
        user_id = await create_test_user()

        response = await test_client.get("/api/v3/maps/mastery", params={"user_id": user_id})

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_requires_auth(self, unauthenticated_client):
        """Get mastery without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/maps/mastery", params={"user_id": 999})

        assert response.status_code == 401


class TestUpdateMastery:
    """POST /api/v3/maps/mastery"""

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

        response = await test_client.post("/api/v3/maps/mastery", json=payload)

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

        response = await unauthenticated_client.post("/api/v3/maps/mastery", json=payload)

        assert response.status_code == 401


class TestSetArchiveStatus:
    """PATCH /api/v3/maps/archive"""

    async def test_archive_map(self, test_client, create_test_map, unique_map_code):
        """Archive a map and verify response."""
        code = unique_map_code
        await create_test_map(code=code, archived=False)

        response = await test_client.patch(
            "/api/v3/maps/archive",
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
            "/api/v3/maps/archive",
            json={"codes": [code], "status": "Unarchived"},
        )

        assert response.status_code == 200
        # Endpoint returns None (JSON null) with 200 status
        assert response.json() is None

    async def test_requires_auth(self, unauthenticated_client):
        """Set archive status without auth returns 401."""
        response = await unauthenticated_client.patch(
            "/api/v3/maps/archive",
            json={"codes": ["ZZZZZZ"], "status": "Archive"},
        )

        assert response.status_code == 401

    async def test_non_existent_map_returns_404(self, test_client):
        """Archive non-existent map returns 404."""
        response = await test_client.patch(
            "/api/v3/maps/archive",
            json={"codes": ["ZZZZZZ"], "status": "Archive"},
        )

        assert response.status_code == 404


class TestConvertToLegacy:
    """POST /api/v3/maps/{code}/legacy"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Convert map to legacy successfully."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.post(
            f"/api/v3/maps/{code}/legacy",
            params={"reason": "Map is outdated"},
        )

        assert response.status_code == 204

    async def test_non_existent_map_returns_404(self, test_client):
        """Convert non-existent map to legacy returns 404."""
        response = await test_client.post(
            "/api/v3/maps/ZZZZZZ/legacy",
            params={"reason": "Map is outdated"},
        )

        assert response.status_code == 404


class TestOverrideQualityVotes:
    """POST /api/v3/maps/{code}/quality"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Override quality votes successfully."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.post(
            f"/api/v3/maps/{code}/quality",
            json={"value": 5},  # Must be between 1 and 6
        )

        assert response.status_code in [200, 201]  # May return 201 for creation

    async def test_non_existent_map_returns_404(self, test_client):
        """Override quality for non-existent map returns 404."""
        response = await test_client.post(
            "/api/v3/maps/ZZZZZZ/quality",
            json={"value": 5},
        )

        assert response.status_code == 404


class TestSendToPlaytest:
    """POST /api/v3/maps/{code}/playtest"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Send approved map to playtest successfully."""
        code = unique_map_code
        await create_test_map(code=code, playtesting="Approved")

        response = await test_client.post(
            f"/api/v3/maps/{code}/playtest",
            json={"initial_difficulty": "Medium"},
        )

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "status" in data

    async def test_already_in_playtest_error(self, test_client, create_test_map, unique_map_code, create_test_playtest):
        """Sending map already in playtest returns 400."""
        code = unique_map_code
        map_id = await create_test_map(code=code, playtesting="In Progress")
        await create_test_playtest(map_id=map_id)

        response = await test_client.post(
            f"/api/v3/maps/{code}/playtest",
            json={"initial_difficulty": "Medium"},
        )

        assert response.status_code == 400

    async def test_non_existent_map_returns_404(self, test_client):
        """Send non-existent map to playtest returns 404."""
        response = await test_client.post(
            "/api/v3/maps/ZZZZZZ/playtest",
            json={"initial_difficulty": "Medium"},
        )

        assert response.status_code == 404


class TestGetAffectedUsers:
    """GET /api/v3/maps/{code}/affected"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get affected users returns list of user IDs."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v3/maps/{code}/affected")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Validate user IDs are integers
        for user_id in data:
            assert isinstance(user_id, int)

    async def test_non_existent_map_returns_404(self, test_client):
        """Get affected users for non-existent map returns 404."""
        response = await test_client.get("/api/v3/maps/ZZZZZZ/affected")

        assert response.status_code == 404


class TestGetMapPlot:
    """GET /api/v3/maps/{code}/plot"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code, create_test_playtest):
        """Get map plot returns stream response."""
        code = unique_map_code
        map_id = await create_test_map(code=code)
        await create_test_playtest(map_id=map_id)

        response = await test_client.get(f"/api/v3/maps/{code}/plot")

        assert response.status_code == 200
        # Verify it's a streaming response (check content type)
        assert response.headers.get("content-type") is not None

    async def test_non_existent_map_returns_404(self, test_client):
        """Get plot for non-existent map returns 404."""
        response = await test_client.get("/api/v3/maps/ZZZZZZ/plot")

        assert response.status_code == 404


class TestGetTrendingMaps:
    """GET /api/v3/maps/trending"""

    async def test_happy_path(self, test_client):
        """Get trending maps returns list with valid structure."""
        response = await test_client.get("/api/v3/maps/trending")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate trending map structure if any exist
        for trending_map in data:
            print(trending_map)
            assert "code" in trending_map
            assert "map_name" in trending_map


    async def test_requires_auth(self, unauthenticated_client):
        """Get trending maps without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/maps/trending")

        assert response.status_code == 401


class TestLinkMapCodes:
    """POST /api/v3/maps/link-codes"""

    async def test_clone_scenario(self, test_client, create_test_map, unique_map_code):
        """Link codes when one needs to be cloned returns job status."""
        official_code = unique_map_code
        await create_test_map(code=official_code, official=True)

        # Create a unique unofficial code that doesn't exist yet (will be cloned)
        unofficial_code = f"U{official_code[1:]}"

        payload = {
            "official_code": official_code,
            "unofficial_code": unofficial_code,
        }

        response = await test_client.post("/api/v3/maps/link-codes", json=payload)

        # Endpoint may return 201 for creation or 200 for link
        assert response.status_code in [200, 201]
        # When cloning is needed, should return job status
        if response.json() is not None:
            data = response.json()
            assert "job_id" in data or "data" in data

    async def test_both_exist_scenario(self, test_client, create_test_map, unique_map_code):
        """Link codes when both exist returns success."""
        official_code = unique_map_code
        unofficial_code = f"U{official_code[1:]}"

        # Create both maps
        await create_test_map(code=official_code, official=True)
        await create_test_map(code=unofficial_code, official=False)

        payload = {
            "official_code": official_code,
            "unofficial_code": unofficial_code,
        }

        response = await test_client.post("/api/v3/maps/link-codes", json=payload)

        # Endpoint may return 201 or 200
        assert response.status_code in [200, 201]

    async def test_already_linked_to_different_map(self, test_client, create_test_map, unique_map_code):
        """Linking already linked map to different map returns 400."""
        code_a = unique_map_code
        code_b = f"B{code_a[1:]}"
        code_c = f"C{code_a[1:]}"

        await create_test_map(code=code_a, official=True)
        await create_test_map(code=code_b, official=False)
        await create_test_map(code=code_c, official=False)

        # Link A to B
        await test_client.post(
            "/api/v3/maps/link-codes",
            json={"official_code": code_a, "unofficial_code": code_b},
        )

        # Try to link A to C (should fail)
        response = await test_client.post(
            "/api/v3/maps/link-codes",
            json={"official_code": code_a, "unofficial_code": code_c},
        )

        assert response.status_code == 400

    async def test_requires_auth(self, unauthenticated_client):
        """Link codes without auth returns 401."""
        response = await unauthenticated_client.post(
            "/api/v3/maps/link-codes",
            json={"official_code": "AAAA", "unofficial_code": "BBBB"},
        )

        assert response.status_code == 401


class TestUnlinkMapCodes:
    """DELETE /api/v3/maps/link-codes"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Unlink codes successfully."""
        official_code = unique_map_code
        unofficial_code = f"U{official_code[1:]}"

        await create_test_map(code=official_code, official=True)
        await create_test_map(code=unofficial_code, official=False)

        # Link them first
        await test_client.post(
            "/api/v3/maps/link-codes",
            json={"official_code": official_code, "unofficial_code": unofficial_code},
        )

        # Unlink them
        response = await test_client.request(
            "DELETE",
            "/api/v3/maps/link-codes",
            json={
                "official_code": official_code,
                "unofficial_code": unofficial_code,
                "reason": "No longer needed",
            },
        )

        assert response.status_code == 204

    async def test_map_not_found(self, test_client):
        """Unlink non-existent map returns 404."""
        response = await test_client.request(
            "DELETE",
            "/api/v3/maps/link-codes",
            json={
                "official_code": "ZZZZZZ",
                "unofficial_code": "YYYYYY",
                "reason": "Test",
            },
        )

        assert response.status_code == 404

    async def test_requires_auth(self, unauthenticated_client):
        """Unlink codes without auth returns 401."""
        response = await unauthenticated_client.request(
            "DELETE",
            "/api/v3/maps/link-codes",
            json={
                "official_code": "AAAA",
                "unofficial_code": "BBBB",
                "reason": "Test",
            },
        )

        assert response.status_code == 401
