"""Unit tests for LootboxService."""

from unittest.mock import ANY

import pytest

from services.exceptions.lootbox import InsufficientKeysError
from services.lootbox_service import DUPLICATE_COIN_VALUES, GACHA_WEIGHTS, LootboxService

pytestmark = [
    pytest.mark.domain_lootbox,
]


class TestLootboxServiceGacha:
    """Test gacha logic."""

    def test_perform_gacha_returns_valid_rarity(self):
        """_perform_gacha returns a valid rarity from GACHA_WEIGHTS."""
        rarity = LootboxService._perform_gacha()
        assert rarity in GACHA_WEIGHTS.keys()

    def test_perform_gacha_returns_string(self):
        """_perform_gacha returns a string."""
        rarity = LootboxService._perform_gacha()
        assert isinstance(rarity, str)

    def test_perform_gacha_distribution(self):
        """_perform_gacha respects weight distribution over many iterations."""
        # Run gacha 1000 times
        results = [LootboxService._perform_gacha() for _ in range(1000)]

        # Count occurrences
        counts = {rarity: results.count(rarity) for rarity in GACHA_WEIGHTS.keys()}

        # All rarities should appear at least once in 1000 rolls
        for rarity in GACHA_WEIGHTS.keys():
            assert counts[rarity] > 0, f"{rarity} never appeared in 1000 rolls"

        # Common should be most frequent (not a strict test, just sanity check)
        assert counts["common"] > counts["legendary"]


class TestLootboxServiceGetRandomItems:
    """Test get_random_items preview behavior."""

    async def test_get_random_items_no_keys_raises_error(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Raises InsufficientKeysError when user has no keys."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        # No key to delete
        mock_lootbox_repo.delete_oldest_user_key.return_value = False

        with pytest.raises(InsufficientKeysError):
            await service.get_random_items(
                user_id=123456789,
                key_type="Classic",
                test_mode=False,
            )

        # Should have tried to delete one key
        mock_lootbox_repo.delete_oldest_user_key.assert_called_once()

    async def test_get_random_items_consumes_one_key(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Consumes exactly one key regardless of amount parameter."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.delete_oldest_user_key.return_value = True
        mock_lootbox_repo.fetch_random_reward.return_value = {
            "name": "Test Reward",
            "type": "avatar",
            "rarity": "common",
            "duplicate": False,
            "coin_amount": 0,
        }

        result = await service.get_random_items(
            user_id=123456789,
            key_type="Classic",
            amount=3,
            test_mode=False,
        )

        # Should return 3 rewards
        assert len(result) == 3

        # Should only consume ONE key at the start
        mock_lootbox_repo.delete_oldest_user_key.assert_called_once_with(
            123456789, "Classic", conn=ANY
        )

    async def test_get_random_items_does_not_grant_rewards(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Does not grant rewards or coins (preview only)."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.delete_oldest_user_key.return_value = True
        mock_lootbox_repo.fetch_random_reward.return_value = {
            "name": "Test Reward",
            "type": "avatar",
            "rarity": "common",
            "duplicate": False,
            "coin_amount": 0,
        }

        await service.get_random_items(
            user_id=123456789,
            key_type="Classic",
            test_mode=False,
        )

        # Should NOT grant any rewards
        mock_lootbox_repo.insert_user_reward.assert_not_called()
        mock_lootbox_repo.add_user_coins.assert_not_called()

    async def test_get_random_items_does_not_grant_coins_for_duplicates(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Does not grant coins even for duplicate rewards (preview only)."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.delete_oldest_user_key.return_value = True
        mock_lootbox_repo.fetch_random_reward.return_value = {
            "name": "Test Reward",
            "type": "avatar",
            "rarity": "rare",
            "duplicate": True,  # This is a duplicate
            "coin_amount": 250,
        }

        result = await service.get_random_items(
            user_id=123456789,
            key_type="Classic",
            test_mode=False,
        )

        # Should return rewards with duplicate info
        assert len(result) == 3
        assert all(r.duplicate is True for r in result)
        assert all(r.coin_amount == 250 for r in result)

        # But should NOT grant coins
        mock_lootbox_repo.add_user_coins.assert_not_called()

    async def test_get_random_items_test_mode_skips_key_consumption(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Test mode skips key consumption."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.fetch_random_reward.return_value = {
            "name": "Test Reward",
            "type": "avatar",
            "rarity": "common",
            "duplicate": False,
            "coin_amount": 0,
        }

        result = await service.get_random_items(
            user_id=123456789,
            key_type="Classic",
            test_mode=True,
        )

        assert len(result) == 3
        # Should NOT try to delete any keys
        mock_lootbox_repo.delete_oldest_user_key.assert_not_called()

    async def test_get_random_items_always_returns_three_rewards(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Always returns 3 rewards regardless of amount parameter."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.delete_oldest_user_key.return_value = True
        mock_lootbox_repo.fetch_random_reward.return_value = {
            "name": "Test Reward",
            "type": "avatar",
            "rarity": "common",
            "duplicate": False,
            "coin_amount": 0,
        }

        # Even with amount=1, should return 3 rewards
        result = await service.get_random_items(
            user_id=123456789,
            key_type="Classic",
            amount=1,  # This is ignored
            test_mode=False,
        )

        assert len(result) == 3


class TestLootboxServiceGrantReward:
    """Test grant_reward_to_user business logic."""

    async def test_grant_reward_duplicate_grants_coins(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Duplicate reward grants coins instead of reward."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        # User already has this reward (returns rarity)
        mock_lootbox_repo.check_user_has_reward.return_value = "rare"

        result = await service.grant_reward_to_user(
            user_id=123456789,
            reward_type="avatar",
            key_type="Classic",
            reward_name="Test Avatar",
        )

        # Should grant coins for duplicate
        expected_coins = DUPLICATE_COIN_VALUES["rare"]
        mock_lootbox_repo.add_user_coins.assert_called_once_with(123456789, expected_coins, conn=ANY)

        # Should not insert reward
        mock_lootbox_repo.insert_user_reward.assert_not_called()

        # Response should indicate duplicate
        assert result.duplicate is True
        assert result.coin_amount == expected_coins
        assert result.name == "Test Avatar"
        assert result.rarity == "rare"

    async def test_grant_reward_new_reward_grants_item(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """New reward grants the item to user."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        # User does NOT have this reward (returns None)
        mock_lootbox_repo.check_user_has_reward.return_value = None
        mock_lootbox_repo.fetch_all_rewards.return_value = [
            {"name": "Test Avatar", "rarity": "epic", "type": "avatar", "key_type": "Classic"}
        ]

        result = await service.grant_reward_to_user(
            user_id=123456789,
            reward_type="avatar",
            key_type="Classic",
            reward_name="Test Avatar",
        )

        # Should insert reward
        mock_lootbox_repo.insert_user_reward.assert_called_once_with(
            user_id=123456789,
            reward_type="avatar",
            key_type="Classic",
            reward_name="Test Avatar",
            conn=ANY,
        )

        # Should not grant coins
        mock_lootbox_repo.add_user_coins.assert_not_called()

        # Response should indicate new reward
        assert result.duplicate is False
        assert result.coin_amount == 0
        assert result.name == "Test Avatar"
        assert result.rarity == "epic"

    async def test_grant_reward_deletes_key(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """grant_reward_to_user deletes oldest key."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        mock_lootbox_repo.check_user_has_reward.return_value = None
        mock_lootbox_repo.fetch_all_rewards.return_value = [
            {"name": "Test", "rarity": "common", "type": "avatar", "key_type": "Classic"}
        ]

        await service.grant_reward_to_user(
            user_id=123456789,
            reward_type="avatar",
            key_type="Winter",
            reward_name="Test",
        )

        # Should delete key before granting reward
        mock_lootbox_repo.delete_oldest_user_key.assert_called_once_with(
            123456789, "Winter", conn=ANY
        )

    async def test_grant_reward_duplicate_coin_values(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """Duplicate rewards grant correct coin amounts per rarity."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        # Test each rarity
        test_cases = [
            ("common", DUPLICATE_COIN_VALUES["common"]),
            ("rare", DUPLICATE_COIN_VALUES["rare"]),
            ("epic", DUPLICATE_COIN_VALUES["epic"]),
            ("legendary", DUPLICATE_COIN_VALUES["legendary"]),
        ]

        for rarity, expected_coins in test_cases:
            mock_lootbox_repo.check_user_has_reward.return_value = rarity
            mock_lootbox_repo.add_user_coins.reset_mock()

            result = await service.grant_reward_to_user(
                user_id=123456789,
                reward_type="avatar",
                key_type="Classic",
                reward_name="Test",
            )

            assert result.coin_amount == expected_coins
            mock_lootbox_repo.add_user_coins.assert_called_once_with(123456789, expected_coins, conn=ANY)


class TestLootboxServiceDebugGrant:
    """Test debug_grant_reward_no_key conditional logic."""

    async def test_debug_grant_reward_type_coins(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """debug_grant_reward_no_key grants coins when reward_type is 'coins'."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        await service.debug_grant_reward_no_key(
            user_id=123456789,
            key_type="Classic",
            reward_type="coins",
            reward_name="500",  # Coin amount as string
        )

        # Should grant coins
        mock_lootbox_repo.add_user_coins.assert_called_once_with(123456789, 500, conn=ANY)

        # Should not insert reward
        mock_lootbox_repo.insert_user_reward.assert_not_called()

    async def test_debug_grant_reward_type_avatar(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """debug_grant_reward_no_key grants reward when reward_type is not 'coins'."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        await service.debug_grant_reward_no_key(
            user_id=123456789,
            key_type="Winter",
            reward_type="avatar",
            reward_name="Test Avatar",
        )

        # Should insert reward
        mock_lootbox_repo.insert_user_reward.assert_called_once_with(
            user_id=123456789,
            reward_type="avatar",
            key_type="Winter",
            reward_name="Test Avatar",
            conn=ANY,
        )

        # Should not grant coins
        mock_lootbox_repo.add_user_coins.assert_not_called()

    async def test_debug_grant_reward_type_banner(
        self, mock_pool, mock_state, mock_lootbox_repo
    ):
        """debug_grant_reward_no_key works with different reward types."""
        service = LootboxService(mock_pool, mock_state, mock_lootbox_repo)

        await service.debug_grant_reward_no_key(
            user_id=123456789,
            key_type="Classic",
            reward_type="banner",
            reward_name="Test Banner",
        )

        # Should insert reward
        mock_lootbox_repo.insert_user_reward.assert_called_once_with(
            user_id=123456789,
            reward_type="banner",
            key_type="Classic",
            reward_name="Test Banner",
            conn=ANY,
        )
