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
    """GET /api/v3/lootbox/rewards"""

    async def test_happy_path(self, test_client):
        """Get all rewards returns list with valid structure."""
        response = await test_client.get("/api/v3/lootbox/rewards")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:  # If rewards exist, validate structure
            reward = data[0]
            assert "name" in reward
            assert "key_type" in reward
            assert "rarity" in reward
            assert "type" in reward


class TestViewAllKeys:
    """GET /api/v3/lootbox/keys"""

    async def test_happy_path(self, test_client):
        """Get all keys returns list with valid structure."""
        response = await test_client.get("/api/v3/lootbox/keys")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0  # Should have Classic and Winter at minimum
        for key in data:
            assert "name" in key
            assert key["name"] in ["Classic", "Winter"]


class TestViewUserRewards:
    """GET /api/v3/lootbox/users/{user_id}/rewards"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user rewards returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/rewards")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # User may not have rewards yet, so only validate if data exists
        for reward in data:
            assert "user_id" in reward
            assert "earned_at" in reward
            assert "name" in reward
            assert "type" in reward
            assert "rarity" in reward
            assert reward["user_id"] == user_id

    async def test_nonexistent_user_returns_empty_list(self, test_client):
        """Get rewards for non-existent user returns empty list."""
        response = await test_client.get("/api/v3/lootbox/users/999999999/rewards")

        assert response.status_code == 200
        assert response.json() == []


class TestViewUserKeys:
    """GET /api/v3/lootbox/users/{user_id}/keys"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get user keys returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/keys")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # User may not have keys yet, so only validate if data exists
        for key_amount in data:
            assert "key_type" in key_amount
            assert "amount" in key_amount
            assert isinstance(key_amount["amount"], int)
            assert key_amount["amount"] >= 0

    @pytest.mark.parametrize("key_type", ["Classic", "Winter"])
    async def test_filter_by_key_type(self, test_client, create_test_user, key_type):
        """Filter user keys by type."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v3/lootbox/users/{user_id}/keys",
            params={"key_type": key_type},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_nonexistent_user_returns_empty_list(self, test_client):
        """Get keys for non-existent user returns empty list."""
        response = await test_client.get("/api/v3/lootbox/users/999999999/keys")

        assert response.status_code == 200
        assert response.json() == []

    async def test_invalid_key_type_returns_400(self, test_client, create_test_user):
        """Filter by invalid key type returns 400."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v3/lootbox/users/{user_id}/keys",
            params={"key_type": "invalid"},
        )

        assert response.status_code == 400


class TestDrawRandomRewards:
    """GET /api/v3/lootbox/users/{user_id}/keys/{key_type} - Draw random rewards"""

    async def test_insufficient_keys_returns_400(self, test_client, create_test_user):
        """Drawing rewards without keys returns 400."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/keys/Classic")

        # Should fail due to insufficient keys
        assert response.status_code == 400

    async def test_invalid_key_type_returns_400(self, test_client, create_test_user):
        """Draw rewards with invalid key type returns 400."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/keys/invalid")

        assert response.status_code == 400

    async def test_draw_with_amount_parameter(self, test_client, create_test_user):
        """Draw rewards with amount parameter works correctly."""
        user_id = await create_test_user()

        # Grant user 3 keys
        for _ in range(3):
            await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys/Classic")

        # Draw 3 rewards
        response = await test_client.get(
            f"/api/v3/lootbox/users/{user_id}/keys/Classic",
            params={"amount": 3}
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 3


class TestGrantRewardToUser:
    """POST /api/v3/lootbox/users/{user_id}/{key_type}/{reward_type}/{reward_name}

    Note: This endpoint does NOT consume keys. Key consumption happens in
    get_random_items (preview endpoint). This endpoint only grants the chosen reward.
    """

    async def test_grant_reward_succeeds(self, test_client, create_test_user):
        """Grant reward succeeds without needing a key (key consumed in preview)."""
        user_id = await create_test_user()

        # No key needed - key consumption happens in get_random_items
        # Use actual reward from migrations: "God Of War" spray
        response = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/Classic/spray/God Of War"
        )

        # Should succeed and return reward details
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "God Of War"
        assert data["type"] == "spray"
        assert data["key_type"] == "Classic"

    async def test_grant_duplicate_reward_returns_coins(self, test_client, create_test_user):
        """Grant same reward twice - second time returns coins instead."""
        user_id = await create_test_user()

        # No keys needed - key consumption happens in get_random_items

        # Grant reward first time - should succeed and not be duplicate
        response1 = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/Classic/spray/God Of War"
        )
        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["duplicate"] is False
        assert data1["coin_amount"] == 0

        # Grant same reward second time - should return coins for duplicate
        response2 = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/Classic/spray/God Of War"
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["duplicate"] is True
        assert data2["coin_amount"] > 0  # Should get coins for common duplicate


class TestGrantKeyToUser:
    """POST /api/v3/lootbox/users/{user_id}/keys/{key_type}"""

    @pytest.mark.parametrize("key_type", ["Classic", "Winter"])
    async def test_grant_key_types(self, test_client, create_test_user, key_type):
        """Grant different key types to user."""
        user_id = await create_test_user()

        response = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/keys/{key_type}"
        )

        assert response.status_code == 204

    async def test_invalid_key_type_returns_400(self, test_client, create_test_user):
        """Grant invalid key type returns 400."""
        user_id = await create_test_user()

        response = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys/invalid")

        assert response.status_code == 400

    async def test_grant_duplicate_keys_succeeds(self, test_client, create_test_user):
        """Grant multiple keys to same user succeeds."""
        user_id = await create_test_user()

        # Grant first key
        response1 = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys/Classic")
        assert response1.status_code == 204

        # Grant second key
        response2 = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys/Classic")
        assert response2.status_code == 204

        # Verify user now has 2 keys
        keys_response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/keys")
        keys_data = keys_response.json()
        classic_keys = [k for k in keys_data if k["key_type"] == "Classic"]
        assert len(classic_keys) == 1
        assert classic_keys[0]["amount"] == 2


class TestGrantActiveKey:
    """POST /api/v3/lootbox/users/{user_id}/keys"""

    async def test_grant_active_key(self, test_client, create_test_user):
        """Grant active key to user."""
        user_id = await create_test_user()

        response = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys")

        assert response.status_code == 204

    async def test_grant_active_key_multiple_times(self, test_client, create_test_user):
        """Grant active key multiple times to same user succeeds."""
        user_id = await create_test_user()

        # Grant first active key
        response1 = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys")
        assert response1.status_code == 204

        # Grant second active key
        response2 = await test_client.post(f"/api/v3/lootbox/users/{user_id}/keys")
        assert response2.status_code == 204

        # Verify user has keys (active key should be one of Classic or Winter)
        keys_response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/keys")
        keys_data = keys_response.json()
        total_keys = sum(k["amount"] for k in keys_data)
        assert total_keys >= 2


class TestDebugGrantReward:
    """POST /api/v3/lootbox/users/debug/{user_id}/{key_type}/{reward_type}/{reward_name}"""

    async def test_debug_grant_with_valid_reward(self, test_client, create_test_user):
        """Debug grant reward without key check succeeds with valid reward."""
        user_id = await create_test_user()

        # Use actual reward from migrations: "Cinnabar" skin
        response = await test_client.post(
            f"/api/v3/lootbox/users/debug/{user_id}/Classic/skin/Cinnabar"
        )

        assert response.status_code == 204

    async def test_debug_grant_multiple_rewards(self, test_client, create_test_user):
        """Debug grant multiple different rewards to user."""
        user_id = await create_test_user()

        # Grant first reward
        response1 = await test_client.post(
            f"/api/v3/lootbox/users/debug/{user_id}/Classic/skin/Cinnabar"
        )
        assert response1.status_code == 204

        # Grant second reward
        response2 = await test_client.post(
            f"/api/v3/lootbox/users/debug/{user_id}/Classic/spray/God Of War"
        )
        assert response2.status_code == 204

        # Grant third reward
        response3 = await test_client.post(
            f"/api/v3/lootbox/users/debug/{user_id}/Classic/background/New Queen Street"
        )
        assert response3.status_code == 204

        # Verify user has all three rewards
        rewards_response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/rewards")
        rewards_data = rewards_response.json()
        assert len(rewards_data) == 3
        reward_names = {r["name"] for r in rewards_data}
        assert reward_names == {"Cinnabar", "God Of War", "New Queen Street"}


class TestUpdateActiveKey:
    """PATCH /api/v3/lootbox/keys/{key_type}"""

    @pytest.mark.parametrize("key_type", ["Classic", "Winter"])
    async def test_update_active_key(self, test_client, key_type):
        """Update active key type."""
        response = await test_client.patch(f"/api/v3/lootbox/keys/{key_type}")

        assert response.status_code == 204

    async def test_invalid_key_type_returns_400(self, test_client):
        """Update active key with invalid type returns 400."""
        response = await test_client.patch("/api/v3/lootbox/keys/invalid")

        assert response.status_code == 400


class TestGetUserCoins:
    """GET /api/v3/lootbox/users/{user_id}/coins"""

    async def test_get_user_coin_balance(self, test_client, create_test_user):
        """Get user coin balance returns integer."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/lootbox/users/{user_id}/coins")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, int)
        assert data >= 0

    async def test_nonexistent_user_returns_zero(self, test_client):
        """Get coins for non-existent user returns 0."""
        response = await test_client.get("/api/v3/lootbox/users/999999999/coins")

        assert response.status_code == 200
        assert response.json() == 0


class TestGrantUserXp:
    """POST /api/v3/lootbox/users/{user_id}/xp"""

    async def test_grant_xp_to_user(self, test_client, create_test_user):
        """Grant XP to user returns XP amounts."""
        user_id = await create_test_user()

        payload = {"amount": 100, "type": "Completion"}
        response = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/xp",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "previous_amount" in data
        assert "new_amount" in data
        assert isinstance(data["previous_amount"], int)
        assert isinstance(data["new_amount"], int)
        assert data["new_amount"] >= data["previous_amount"]

    async def test_invalid_xp_type_returns_400(self, test_client, create_test_user):
        """Grant XP with invalid type returns 400."""
        user_id = await create_test_user()

        payload = {"amount": 100, "type": "invalid"}
        response = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/xp",
            json=payload,
        )

        assert response.status_code == 400

    async def test_missing_amount_returns_400(self, test_client, create_test_user):
        """Grant XP without amount returns 400."""
        user_id = await create_test_user()

        payload = {"type": "Completion"}
        response = await test_client.post(
            f"/api/v3/lootbox/users/{user_id}/xp",
            json=payload,
        )

        assert response.status_code == 400


class TestGetXpTierChange:
    """GET /api/v3/lootbox/xp/tier"""

    async def test_get_tier_change(self, test_client):
        """Get XP tier change information with valid structure."""
        response = await test_client.get(
            "/api/v3/lootbox/xp/tier",
            params={"old_xp": 100, "new_xp": 150},
        )

        assert response.status_code == 200
        data = response.json()
        assert "old_xp" in data
        assert "new_xp" in data
        assert "old_main_tier_name" in data
        assert "new_main_tier_name" in data
        assert "old_sub_tier_name" in data
        assert "new_sub_tier_name" in data
        assert "old_prestige_level" in data
        assert "new_prestige_level" in data
        assert "rank_change_type" in data
        assert "prestige_change" in data
        assert data["old_xp"] == 100
        assert data["new_xp"] == 150


class TestUpdateXpMultiplier:
    """POST /api/v3/lootbox/xp/multiplier"""

    async def test_set_xp_multiplier(self, test_client):
        """Set XP multiplier."""
        payload = {"value": 1.5}
        response = await test_client.post("/api/v3/lootbox/xp/multiplier", json=payload)

        assert response.status_code == 204


class TestGetXpMultiplier:
    """GET /api/v3/lootbox/xp/multiplier"""

    async def test_get_active_multiplier(self, test_client):
        """Get active XP multiplier returns float."""
        response = await test_client.get("/api/v3/lootbox/xp/multiplier")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, (int, float))
        assert data > 0
