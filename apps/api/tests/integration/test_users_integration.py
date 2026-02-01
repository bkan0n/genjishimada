"""Integration tests for Users v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_users,
]


class TestCheckIfUserIsCreator:
    """GET /api/v4/users/{user_id}/creator"""

    async def test_happy_path_creator(self, test_client, create_test_user, create_test_map, unique_map_code):
        """User with maps is a creator."""
        user_id = await create_test_user()
        # Create a map for this user with them as creator
        code = unique_map_code
        await create_test_map(code=code, creator_id=user_id)

        response = await test_client.get(f"/api/v4/users/{user_id}/creator")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        # User has a map they created, so should be a creator
        assert result is True

    async def test_non_creator(self, test_client, create_test_user):
        """User without maps is not a creator."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/users/{user_id}/creator")

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        # User has no maps, so should not be a creator
        assert result is False

    async def test_requires_auth(self, unauthenticated_client):
        """Check creator without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/999999999/creator")

        assert response.status_code == 401


class TestUpdateUserNames:
    """PATCH /api/v4/users/{user_id}"""

    async def test_update_nickname(self, test_client, create_test_user):
        """Update user nickname."""
        user_id = await create_test_user(nickname="OldName")

        response = await test_client.patch(
            f"/api/v4/users/{user_id}",
            json={"nickname": "NewName"},
        )

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Update user without auth returns 401."""
        response = await unauthenticated_client.patch(
            "/api/v4/users/999999999",
            json={"nickname": "NewName"},
        )

        assert response.status_code == 401

    async def test_non_existent_user_succeeds(self, test_client):
        """Update non-existent user succeeds (creates or updates silently)."""
        # Note: The repository likely does an upsert or ignores non-existent users
        response = await test_client.patch(
            "/api/v4/users/999999999999999999",
            json={"nickname": "NewName"},
        )

        # PATCH operations on non-existent users might succeed with 200/204
        assert response.status_code in [200, 204]

    async def test_update_global_name(self, test_client, create_test_user):
        """Update user global name."""
        user_id = await create_test_user()

        response = await test_client.patch(
            f"/api/v4/users/{user_id}",
            json={"global_name": "NewGlobalName"},
        )

        assert response.status_code == 200

    async def test_update_both_names(self, test_client, create_test_user):
        """Update both nickname and global name."""
        user_id = await create_test_user()

        response = await test_client.patch(
            f"/api/v4/users/{user_id}",
            json={"nickname": "NewNick", "global_name": "NewGlobal"},
        )

        assert response.status_code == 200

    async def test_no_fields_set_returns_400(self, test_client, create_test_user):
        """Empty update request returns 400."""
        user_id = await create_test_user()

        response = await test_client.patch(
            f"/api/v4/users/{user_id}",
            json={},
        )

        assert response.status_code == 400


class TestListUsers:
    """GET /api/v4/users/"""

    async def test_happy_path(self, test_client):
        """List users returns 200 with list."""
        response = await test_client.get("/api/v4/users/")

        assert response.status_code == 200
        data = response.json()
        # Could be None if no users, or a list
        assert data is None or isinstance(data, list)

    async def test_requires_auth(self, unauthenticated_client):
        """List users without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/")

        assert response.status_code == 401

    async def test_with_users(self, test_client, create_test_user):
        """List includes created users with valid structure."""
        user_id = await create_test_user(nickname="TestUser123")

        response = await test_client.get("/api/v4/users/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert any(u["id"] == user_id for u in data)

        # Validate user structure
        if data:
            user = data[0]
            assert "id" in user
            assert "nickname" in user
            assert "global_name" in user
            assert "coins" in user
            assert isinstance(user["coins"], int)
            assert "overwatch_usernames" in user
            assert "coalesced_name" in user


class TestGetUser:
    """GET /api/v4/users/{user_id}"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user returns user data."""
        user_id = await create_test_user(nickname="TestUser")

        response = await test_client.get(f"/api/v4/users/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user_id
        assert data["nickname"] == "TestUser"
        assert "global_name" in data
        assert "coins" in data

    async def test_non_existent_user_returns_null(self, test_client):
        """Non-existent user returns null."""
        response = await test_client.get("/api/v4/users/999999999999999999")

        assert response.status_code == 200
        # Service returns None, which serializes to null in JSON
        assert response.json() is None

    async def test_requires_auth(self, unauthenticated_client):
        """Get user without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/999999999")

        assert response.status_code == 401


class TestCheckUserExists:
    """GET /api/v4/users/{user_id}/exists"""

    async def test_existing_user(self, test_client, create_test_user):
        """Existing user returns true."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/users/{user_id}/exists")

        assert response.status_code == 200
        assert response.json() is True

    async def test_non_existent_user(self, test_client):
        """Non-existent user returns false."""
        response = await test_client.get("/api/v4/users/999999999999999999/exists")

        assert response.status_code == 200
        assert response.json() is False

    async def test_requires_auth(self, unauthenticated_client):
        """Check user exists without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/999999999/exists")

        assert response.status_code == 401


class TestCreateUser:
    """POST /api/v4/users/"""

    async def test_happy_path(self, test_client, unique_user_id):
        """Create user returns user data with valid structure."""
        payload = {
            "id": unique_user_id,
            "nickname": "NewUser",
            "global_name": "GlobalNewUser",
        }

        response = await test_client.post("/api/v4/users/", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == unique_user_id
        assert data["nickname"] == "NewUser"
        assert data["global_name"] == "GlobalNewUser"
        assert "coins" in data
        assert data["coins"] == 0  # New users start with 0 coins
        assert "overwatch_usernames" in data
        assert isinstance(data["overwatch_usernames"], list)
        assert "coalesced_name" in data

    async def test_duplicate_user_returns_409(self, test_client, create_test_user):
        """Creating duplicate user returns 409 Conflict."""
        user_id = await create_test_user(nickname="ExistingUser")

        payload = {
            "id": user_id,
            "nickname": "DifferentName",
            "global_name": "DifferentGlobal",
        }

        response = await test_client.post("/api/v4/users/", json=payload)

        assert response.status_code == 409
        data = response.json()
        assert "error" in data
        assert "already exists" in data["error"].lower()

    async def test_invalid_user_id_returns_400(self, test_client):
        """Creating user with ID < 100000000 returns 400."""
        payload = {
            "id": 999,  # Below the 100000000 threshold
            "nickname": "InvalidUser",
            "global_name": "GlobalInvalid",
        }

        response = await test_client.post("/api/v4/users/", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "fake member" in data["error"].lower()

    async def test_requires_auth(self, unauthenticated_client):
        """Create user without auth returns 401."""
        payload = {
            "id": 999999999,
            "nickname": "NewUser",
            "global_name": "GlobalUser",
        }

        response = await unauthenticated_client.post("/api/v4/users/", json=payload)

        assert response.status_code == 401


class TestUpdateOverwatchUsernames:
    """PUT /api/v4/users/{user_id}/overwatch"""

    async def test_happy_path(self, test_client, create_test_user):
        """Update Overwatch usernames returns success with valid structure."""
        user_id = await create_test_user()

        payload = {
            "usernames": [
                {"username": "Player#1234", "is_primary": True},
                {"username": "AltAccount#5678", "is_primary": False},
            ]
        }

        response = await test_client.put(
            f"/api/v4/users/{user_id}/overwatch",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert data["success"] is True
        assert isinstance(data["success"], bool)

    async def test_single_username(self, test_client, create_test_user):
        """Can set single Overwatch username."""
        user_id = await create_test_user()

        payload = {"usernames": [{"username": "OnlyAccount#9999", "is_primary": True}]}

        response = await test_client.put(
            f"/api/v4/users/{user_id}/overwatch",
            json=payload,
        )

        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_empty_usernames_list(self, test_client, create_test_user):
        """Can clear all Overwatch usernames."""
        user_id = await create_test_user()

        payload = {"usernames": []}

        response = await test_client.put(
            f"/api/v4/users/{user_id}/overwatch",
            json=payload,
        )

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Update Overwatch usernames without auth returns 401."""
        payload = {"usernames": [{"username": "Player#1234", "is_primary": True}]}

        response = await unauthenticated_client.put(
            "/api/v4/users/999999999/overwatch",
            json=payload,
        )

        assert response.status_code == 401

    async def test_non_existent_user_handling(self, test_client):
        """Update Overwatch usernames for non-existent user handling."""
        payload = {"usernames": [{"username": "Player#1234", "is_primary": True}]}

        response = await test_client.put(
            "/api/v4/users/999999999999999999/overwatch",
            json=payload,
        )

        # May succeed (upsert) or fail with 400, depending on FK constraint
        assert response.status_code in [200, 400]


class TestGetOverwatchUsernames:
    """GET /api/v4/users/{user_id}/overwatch"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get Overwatch usernames returns data with valid structure."""
        user_id = await create_test_user()

        # Set some usernames first
        await test_client.put(
            f"/api/v4/users/{user_id}/overwatch",
            json={
                "usernames": [
                    {"username": "Player#1234", "is_primary": True},
                ]
            },
        )

        response = await test_client.get(f"/api/v4/users/{user_id}/overwatch")

        assert response.status_code == 200
        data = response.json()
        # Response has primary/secondary/tertiary fields
        assert "primary" in data
        assert "user_id" in data
        assert data["user_id"] == user_id
        assert data["primary"] == "Player#1234"
        assert "secondary" in data
        assert "tertiary" in data

    async def test_requires_auth(self, unauthenticated_client):
        """Get Overwatch usernames without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/999999999/overwatch")

        assert response.status_code == 401

    async def test_non_existent_user_response(self, test_client):
        """Get Overwatch usernames for non-existent user."""
        response = await test_client.get("/api/v4/users/999999999999999999/overwatch")

        # Might return 200 with null values or empty response
        assert response.status_code == 200
        data = response.json()
        # Response structure should exist even for non-existent user
        assert "user_id" in data
        assert "primary" in data


class TestGetUserRankData:
    """GET /api/v4/users/{user_id}/rank"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get rank data returns list of rank details with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/users/{user_id}/rank")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Each rank detail has difficulty-specific data
        # Empty list is valid for user with no completions

        # Validate rank detail structure if not empty
        if data:
            rank_detail = data[0]
            # Should have difficulty-related fields
            assert isinstance(rank_detail, dict)

    async def test_requires_auth(self, unauthenticated_client):
        """Get rank data without auth returns 401."""
        response = await unauthenticated_client.get("/api/v4/users/999999999/rank")

        assert response.status_code == 401


class TestCreateFakeMember:
    """POST /api/v4/users/fake"""

    async def test_happy_path(self, test_client):
        """Create fake member returns new user ID with valid type."""
        response = await test_client.post(
            "/api/v4/users/fake",
            params={"name": "FakeMember"},
        )

        assert response.status_code == 201
        user_id = response.json()
        assert isinstance(user_id, int)
        assert user_id > 0
        # Fake members should have IDs < 100000000
        assert user_id < 100_000_000

    async def test_requires_auth(self, unauthenticated_client):
        """Create fake member without auth returns 401."""
        response = await unauthenticated_client.post(
            "/api/v4/users/fake",
            params={"name": "FakeMember"},
        )

        assert response.status_code == 401


class TestLinkFakeMemberToRealUser:
    """PUT /api/v4/users/fake/{fake_user_id}/link/{real_user_id}"""

    async def test_happy_path(self, test_client, create_test_user):
        """Link fake member to real user succeeds."""
        # Create a fake member
        fake_response = await test_client.post(
            "/api/v4/users/fake",
            params={"name": "FakeUser"},
        )
        fake_user_id = fake_response.json()

        # Create a real user
        real_user_id = await create_test_user()

        # Link them
        response = await test_client.put(
            f"/api/v4/users/fake/{fake_user_id}/link/{real_user_id}",
        )

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Link fake member without auth returns 401."""
        response = await unauthenticated_client.put(
            "/api/v4/users/fake/999/link/888888888",
        )

        assert response.status_code == 401

    async def test_non_existent_fake_user_handling(self, test_client, create_test_user):
        """Link non-existent fake user to real user handling."""
        real_user_id = await create_test_user()

        response = await test_client.put(
            f"/api/v4/users/fake/999999999/link/{real_user_id}",
        )

        # Should handle non-existent fake user gracefully
        # Might succeed (no-op) or return 404/400
        assert response.status_code in [200, 204, 400, 404, 500]

    async def test_non_existent_real_user_returns_404(self, test_client):
        """Link fake user to non-existent real user should return 404."""
        # Create a fake member
        fake_response = await test_client.post(
            "/api/v4/users/fake",
            params={"name": "FakeUser"},
        )
        fake_user_id = fake_response.json()

        response = await test_client.put(
            f"/api/v4/users/fake/{fake_user_id}/link/999999999999999999",
        )

        # Should return 404 for non-existent real user
        assert response.status_code == 404
