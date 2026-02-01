"""Integration tests for Rank Card v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_rank_card,
]


class TestGetRankCard:
    """GET /api/v3/users/{user_id}/rank-card/"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get rank card returns complete structure."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/")

        assert response.status_code == 200
        data = response.json()
        # Validate response structure
        assert "rank_name" in data
        assert "nickname" in data
        assert "background" in data
        assert "total_maps_created" in data
        assert "total_playtests" in data
        assert "world_records" in data
        assert "difficulties" in data
        assert "avatar_skin" in data
        assert "avatar_pose" in data
        assert "badges" in data
        assert "xp" in data
        assert "community_rank" in data
        assert "prestige_level" in data
        assert "background_url" in data
        assert "rank_url" in data
        assert "avatar_url" in data
        # Validate field types
        assert isinstance(data["rank_name"], str)
        assert isinstance(data["nickname"], str)
        assert isinstance(data["background"], str)
        assert isinstance(data["total_maps_created"], int)
        assert isinstance(data["total_playtests"], int)
        assert isinstance(data["world_records"], int)
        assert isinstance(data["difficulties"], dict)
        assert isinstance(data["avatar_skin"], str)
        assert isinstance(data["avatar_pose"], str)
        assert isinstance(data["badges"], dict)
        assert isinstance(data["xp"], int)
        assert isinstance(data["community_rank"], str)
        assert isinstance(data["prestige_level"], int)

    async def test_requires_auth(self, unauthenticated_client):
        """Get rank card without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/users/999999999/rank-card/")

        assert response.status_code == 401

    async def test_user_not_found_returns_404(self, test_client):
        """Get rank card for non-existent user returns 404."""
        response = await test_client.get("/api/v3/users/999999999/rank-card/")

        assert response.status_code == 404


class TestGetBackground:
    """GET /api/v3/users/{user_id}/rank-card/background"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get background returns name and URL."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/background")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "url" in data
        assert isinstance(data["name"], str)
        assert isinstance(data["url"], str)
        # Default background should be "placeholder"
        assert data["name"] == "placeholder"

    async def test_requires_auth(self, unauthenticated_client):
        """Get background without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/users/999999999/rank-card/background")

        assert response.status_code == 401


class TestSetBackground:
    """PUT /api/v3/users/{user_id}/rank-card/background"""

    async def test_happy_path(self, test_client, create_test_user):
        """Set background returns updated name and URL."""
        user_id = await create_test_user()
        payload = {"name": "sunset"}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/background",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "url" in data
        assert data["name"] == "sunset"
        assert isinstance(data["url"], str)
        # Verify URL is properly generated
        assert "cdn.genji.pk" in data["url"]
        assert "background" in data["url"]
        assert ".webp" in data["url"]

    async def test_requires_auth(self, unauthenticated_client):
        """Set background without auth returns 401."""
        payload = {"name": "sunset"}
        response = await unauthenticated_client.put(
            "/api/v3/users/999999999/rank-card/background",
            json=payload,
        )

        assert response.status_code == 401

    async def test_user_not_found_returns_404(self, test_client):
        """Set background for non-existent user returns 404."""
        payload = {"name": "sunset"}
        response = await test_client.put(
            "/api/v3/users/999999999/rank-card/background",
            json=payload,
        )

        assert response.status_code == 404

    async def test_missing_name_returns_400(self, test_client, create_test_user):
        """Set background with missing name field returns 400."""
        user_id = await create_test_user()
        payload = {}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/background",
            json=payload,
        )

        assert response.status_code == 400


class TestGetAvatarSkin:
    """GET /api/v3/users/{user_id}/rank-card/avatar/skin"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get avatar skin returns skin and URL."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/avatar/skin")

        assert response.status_code == 200
        data = response.json()
        assert "skin" in data
        assert "url" in data
        assert isinstance(data["skin"], str)
        assert isinstance(data["url"], str)
        # Default skin should be "Overwatch 1"
        assert data["skin"] == "Overwatch 1"

    async def test_requires_auth(self, unauthenticated_client):
        """Get avatar skin without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/users/999999999/rank-card/avatar/skin")

        assert response.status_code == 401


class TestSetAvatarSkin:
    """PUT /api/v3/users/{user_id}/rank-card/avatar/skin"""

    async def test_happy_path(self, test_client, create_test_user):
        """Set avatar skin returns updated skin and URL."""
        user_id = await create_test_user()
        payload = {"skin": "Overwatch 2"}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/avatar/skin",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "skin" in data
        assert "url" in data
        assert data["skin"] == "Overwatch 2"
        assert isinstance(data["url"], str)
        # Verify URL is properly generated
        assert "cdn.genji.pk" in data["url"]
        assert "avatar" in data["url"]
        assert ".webp" in data["url"]

    async def test_requires_auth(self, unauthenticated_client):
        """Set avatar skin without auth returns 401."""
        payload = {"skin": "Overwatch 2"}
        response = await unauthenticated_client.put(
            "/api/v3/users/999999999/rank-card/avatar/skin",
            json=payload,
        )

        assert response.status_code == 401

    async def test_user_not_found_returns_404(self, test_client):
        """Set avatar skin for non-existent user returns 404."""
        payload = {"skin": "Overwatch 2"}
        response = await test_client.put(
            "/api/v3/users/999999999/rank-card/avatar/skin",
            json=payload,
        )

        assert response.status_code == 404

    async def test_missing_skin_returns_400(self, test_client, create_test_user):
        """Set avatar skin with missing skin field returns 400."""
        user_id = await create_test_user()
        payload = {}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/avatar/skin",
            json=payload,
        )

        assert response.status_code == 400


class TestGetAvatarPose:
    """GET /api/v3/users/{user_id}/rank-card/avatar/pose"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get avatar pose returns pose and URL."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/avatar/pose")

        assert response.status_code == 200
        data = response.json()
        assert "pose" in data
        assert "url" in data
        assert isinstance(data["pose"], str)
        assert isinstance(data["url"], str)
        # Default pose should be "Heroic"
        assert data["pose"] == "Heroic"

    async def test_requires_auth(self, unauthenticated_client):
        """Get avatar pose without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/users/999999999/rank-card/avatar/pose")

        assert response.status_code == 401


class TestSetAvatarPose:
    """PUT /api/v3/users/{user_id}/rank-card/avatar/pose"""

    async def test_happy_path(self, test_client, create_test_user):
        """Set avatar pose returns updated pose and URL."""
        user_id = await create_test_user()
        payload = {"pose": "Sitting"}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/avatar/pose",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "pose" in data
        assert "url" in data
        assert data["pose"] == "Sitting"
        assert isinstance(data["url"], str)
        # Verify URL is properly generated
        assert "cdn.genji.pk" in data["url"]
        assert "avatar" in data["url"]
        assert ".webp" in data["url"]

    async def test_requires_auth(self, unauthenticated_client):
        """Set avatar pose without auth returns 401."""
        payload = {"pose": "Sitting"}
        response = await unauthenticated_client.put(
            "/api/v3/users/999999999/rank-card/avatar/pose",
            json=payload,
        )

        assert response.status_code == 401

    async def test_user_not_found_returns_404(self, test_client):
        """Set avatar pose for non-existent user returns 404."""
        payload = {"pose": "Sitting"}
        response = await test_client.put(
            "/api/v3/users/999999999/rank-card/avatar/pose",
            json=payload,
        )

        assert response.status_code == 404

    async def test_missing_pose_returns_400(self, test_client, create_test_user):
        """Set avatar pose with missing pose field returns 400."""
        user_id = await create_test_user()
        payload = {}

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/avatar/pose",
            json=payload,
        )

        assert response.status_code == 400


class TestGetBadges:
    """GET /api/v3/users/{user_id}/rank-card/badges"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get badges returns badge settings structure."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/badges")

        assert response.status_code == 200
        data = response.json()
        # All badge fields should exist (6 slots with name, type, url)
        for i in range(1, 7):
            assert f"badge_name{i}" in data
            assert f"badge_type{i}" in data
            assert f"badge_url{i}" in data
        # Default values should be None
        assert data["badge_name1"] is None
        assert data["badge_type1"] is None
        assert data["badge_url1"] is None

    async def test_requires_auth(self, unauthenticated_client):
        """Get badges without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/users/999999999/rank-card/badges")

        assert response.status_code == 401


class TestSetBadges:
    """PUT /api/v3/users/{user_id}/rank-card/badges"""

    async def test_happy_path(self, test_client, create_test_user):
        """Set badges returns 204 No Content."""
        user_id = await create_test_user()
        payload = {
            "badge_name1": "test_badge",
            "badge_type1": "custom",
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }

        response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/badges",
            json=payload,
        )

        assert response.status_code == 204

    async def test_requires_auth(self, unauthenticated_client):
        """Set badges without auth returns 401."""
        payload = {
            "badge_name1": "test_badge",
            "badge_type1": "custom",
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }
        response = await unauthenticated_client.put(
            "/api/v3/users/999999999/rank-card/badges",
            json=payload,
        )

        assert response.status_code == 401

    async def test_user_not_found_returns_404(self, test_client):
        """Set badges for non-existent user returns 404."""
        payload = {
            "badge_name1": "test_badge",
            "badge_type1": "custom",
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }
        response = await test_client.put(
            "/api/v3/users/999999999/rank-card/badges",
            json=payload,
        )

        assert response.status_code == 404

    async def test_set_and_get_badges(self, test_client, create_test_user):
        """Set badges and verify they can be retrieved."""
        user_id = await create_test_user()

        # Set badges
        payload = {
            "badge_name1": "test_badge_1",
            "badge_type1": "custom",
            "badge_name2": "test_badge_2",
            "badge_type2": "spray",
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }

        set_response = await test_client.put(
            f"/api/v3/users/{user_id}/rank-card/badges",
            json=payload,
        )
        assert set_response.status_code == 204

        # Get badges and verify
        get_response = await test_client.get(f"/api/v3/users/{user_id}/rank-card/badges")
        assert get_response.status_code == 200
        data = get_response.json()

        # Verify badge 1
        assert data["badge_name1"] == "test_badge_1"
        assert data["badge_type1"] == "custom"

        # Verify badge 2
        assert data["badge_name2"] == "test_badge_2"
        assert data["badge_type2"] == "spray"
        # Spray type should have URL populated
        assert data["badge_url2"] is not None
        assert "cdn.genji.pk" in data["badge_url2"]
        assert "spray" in data["badge_url2"]

        # Verify empty badges
        assert data["badge_name3"] is None
        assert data["badge_type3"] is None
        assert data["badge_url3"] is None
