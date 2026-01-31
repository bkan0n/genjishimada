"""Integration tests for Lootbox v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_lootbox,
]


class TestViewAllRewards:
    """GET /api/v4/lootbox/rewards"""

    async def test_happy_path(self, test_client):
        """Get all rewards returns list."""
        response = await test_client.get("/api/v4/lootbox/rewards")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestViewAllKeys:
    """GET /api/v4/lootbox/keys"""

    async def test_happy_path(self, test_client):
        """Get all keys returns list."""
        response = await test_client.get("/api/v4/lootbox/keys")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestViewUserRewards:
    """GET /api/v4/lootbox/users/{user_id}/rewards"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user rewards returns list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/rewards")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestViewUserKeys:
    """GET /api/v4/lootbox/users/{user_id}/keys"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user keys returns list."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/keys")

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.parametrize("key_type", ["common", "rare", "epic", "legendary"])
    async def test_filter_by_key_type(self, test_client, create_test_user, key_type):
        """Filter user keys by type."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/lootbox/users/{user_id}/keys",
            params={"key_type": key_type},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestDrawRandomRewards:
    """GET /api/v4/lootbox/users/{user_id}/keys/{key_type} - Draw random rewards"""

    async def test_insufficient_keys_returns_400(self, test_client, create_test_user):
        """Drawing rewards without keys returns 400."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/keys/common")

        # Should fail due to insufficient keys
        assert response.status_code == 400


class TestGrantRewardToUser:
    """POST /api/v4/lootbox/users/{user_id}/{key_type}/{reward_type}/{reward_name}"""

    async def test_insufficient_keys_returns_error(self, test_client, create_test_user):
        """Grant reward without keys returns error."""
        user_id = await create_test_user()

        response = await test_client.post(
            f"/api/v4/lootbox/users/{user_id}/common/badge/test_badge"
        )

        # Should fail due to insufficient keys
        assert response.status_code == 400


class TestGrantKeyToUser:
    """POST /api/v4/lootbox/users/{user_id}/keys/{key_type}"""

    @pytest.mark.parametrize("key_type", ["common", "rare", "epic", "legendary"])
    async def test_grant_key_types(self, test_client, create_test_user, key_type):
        """Grant different key types to user."""
        user_id = await create_test_user()

        response = await test_client.post(
            f"/api/v4/lootbox/users/{user_id}/keys/{key_type}"
        )

        assert response.status_code == 204


class TestGrantActiveKey:
    """POST /api/v4/lootbox/users/{user_id}/keys"""

    async def test_grant_active_key(self, test_client, create_test_user):
        """Grant active key to user."""
        user_id = await create_test_user()

        response = await test_client.post(f"/api/v4/lootbox/users/{user_id}/keys")

        assert response.status_code == 204


class TestDebugGrantReward:
    """POST /api/v4/lootbox/users/debug/{user_id}/{key_type}/{reward_type}/{reward_name}"""

    async def test_debug_grant_no_key_check(self, test_client, create_test_user):
        """Debug grant reward without key check."""
        user_id = await create_test_user()

        response = await test_client.post(
            f"/api/v4/lootbox/users/debug/{user_id}/common/badge/debug_badge"
        )

        assert response.status_code in (200, 201)


class TestUpdateActiveKey:
    """PATCH /api/v4/lootbox/keys/{key_type}"""

    @pytest.mark.parametrize("key_type", ["common", "rare", "epic"])
    async def test_update_active_key(self, test_client, key_type):
        """Update active key type."""
        response = await test_client.patch(f"/api/v4/lootbox/keys/{key_type}")

        assert response.status_code in (200, 204)


class TestGetUserCoins:
    """GET /api/v4/lootbox/users/{user_id}/coins"""

    async def test_get_user_coin_balance(self, test_client, create_test_user):
        """Get user coin balance."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/lootbox/users/{user_id}/coins")

        assert response.status_code == 200


class TestGrantUserXp:
    """POST /api/v4/lootbox/users/{user_id}/xp"""

    async def test_grant_xp_to_user(self, test_client, create_test_user):
        """Grant XP to user."""
        user_id = await create_test_user()

        payload = {"amount": 100, "reason": "test"}
        response = await test_client.post(
            f"/api/v4/lootbox/users/{user_id}/xp",
            json=payload,
        )

        assert response.status_code in (200, 201)


class TestGetXpTierChange:
    """GET /api/v4/lootbox/xp/tier"""

    async def test_get_tier_change(self, test_client):
        """Get XP tier change information."""
        response = await test_client.get(
            "/api/v4/lootbox/xp/tier",
            params={"current_xp": 100, "xp_to_grant": 50},
        )

        assert response.status_code == 200


class TestUpdateXpMultiplier:
    """POST /api/v4/lootbox/xp/multiplier"""

    async def test_set_xp_multiplier(self, test_client):
        """Set XP multiplier."""
        payload = {"multiplier": 1.5, "expiration_hours": 24}
        response = await test_client.post("/api/v4/lootbox/xp/multiplier", json=payload)

        assert response.status_code in (200, 201, 204)


class TestGetXpMultiplier:
    """GET /api/v4/lootbox/xp/multiplier"""

    async def test_get_active_multiplier(self, test_client):
        """Get active XP multiplier."""
        response = await test_client.get("/api/v4/lootbox/xp/multiplier")

        assert response.status_code == 200
