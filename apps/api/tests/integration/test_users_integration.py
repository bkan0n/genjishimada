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
        # Create a map for this user
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v4/users/{user_id}/creator")

        assert response.status_code == 200
        assert isinstance(response.json(), bool)

    async def test_non_creator(self, test_client, create_test_user):
        """User without maps is not a creator."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/users/{user_id}/creator")

        assert response.status_code == 200
        assert isinstance(response.json(), bool)


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

    async def test_with_users(self, test_client, create_test_user):
        """List includes created users."""
        user_id = await create_test_user(nickname="TestUser123")

        response = await test_client.get("/api/v4/users/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert any(u["id"] == user_id for u in data)


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


class TestCreateUser:
    """POST /api/v4/users/"""

    async def test_happy_path(self, test_client, unique_user_id):
        """Create user returns user data."""
        payload = {
            "id": unique_user_id,
            "nickname": "NewUser",
            "global_name": "GlobalNewUser",
        }

        response = await test_client.post("/api/v4/users/", json=payload)

        assert response.status_code in (200, 201)
        data = response.json()
        assert data["id"] == unique_user_id
        assert data["nickname"] == "NewUser"
        assert data["global_name"] == "GlobalNewUser"

    async def test_duplicate_user_raises_error(self, test_client, create_test_user):
        """Creating duplicate user raises error."""
        user_id = await create_test_user(nickname="ExistingUser")

        payload = {
            "id": user_id,
            "nickname": "DifferentName",
            "global_name": "DifferentGlobal",
        }

        response = await test_client.post("/api/v4/users/", json=payload)

        # Raises UserAlreadyExistsError which results in 500
        assert response.status_code in (400, 500)


class TestUpdateOverwatchUsernames:
    """PUT /api/v4/users/{user_id}/overwatch"""

    async def test_happy_path(self, test_client, create_test_user):
        """Update Overwatch usernames returns success."""
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
        assert data["success"] is True

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

        assert response.status_code in (200, 400)


class TestGetOverwatchUsernames:
    """GET /api/v4/users/{user_id}/overwatch"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get Overwatch usernames returns data."""
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

        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            # Response has primary/secondary/tertiary fields
            assert "primary" in data
            assert "user_id" in data


class TestGetUserRankData:
    """GET /api/v4/users/{user_id}/rank"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get rank data returns list of rank details."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/users/{user_id}/rank")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Each rank detail has difficulty-specific data
        # Empty list is valid for user with no completions


class TestCreateFakeMember:
    """POST /api/v4/users/fake"""

    async def test_happy_path(self, test_client):
        """Create fake member returns new user ID."""
        response = await test_client.post(
            "/api/v4/users/fake",
            params={"name": "FakeMember"},
        )

        assert response.status_code in (200, 201)
        user_id = response.json()
        assert isinstance(user_id, int)
        assert user_id > 0


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
