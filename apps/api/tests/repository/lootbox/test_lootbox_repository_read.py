"""Tests for LootboxRepository read operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.lootbox_repository import LootboxRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_lootbox,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide lootbox repository instance."""
    return LootboxRepository(asyncpg_conn)


# ==============================================================================
# TESTS FOR fetch_user_key_count
# ==============================================================================


class TestFetchUserKeyCountHappyPath:
    """Test happy path scenarios for fetch_user_key_count."""

    async def test_fetch_user_key_count_returns_zero_for_no_keys(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test fetching key count for user with no keys returns 0."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_user_key_count(user_id=user_id, key_type="Classic")

        # Assert
        assert result == 0

    async def test_fetch_user_key_count_returns_correct_count(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test fetching key count returns correct number."""
        # Arrange
        user_id = await create_test_user()
        key_type = "Classic"

        # Insert 3 keys
        for _ in range(3):
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
                user_id,
                key_type,
            )

        # Act
        result = await repository.fetch_user_key_count(user_id=user_id, key_type=key_type)

        # Assert
        assert result == 3

    async def test_fetch_user_key_count_different_type_returns_zero(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test fetching count for different key type returns 0."""
        # Arrange
        user_id = await create_test_user()

        # Insert Classic keys
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
            user_id,
            "Classic",
        )

        # Act - query for Winter keys
        result = await repository.fetch_user_key_count(user_id=user_id, key_type="Winter")

        # Assert
        assert result == 0


# ==============================================================================
# TESTS FOR fetch_user_keys
# ==============================================================================


class TestFetchUserKeysHappyPath:
    """Test happy path scenarios for fetch_user_keys."""

    async def test_fetch_user_keys_empty_for_no_keys(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test fetching keys for user with no keys returns empty list."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_user_keys(user_id=user_id)

        # Assert
        assert result == []

    async def test_fetch_user_keys_returns_grouped_counts(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test fetching keys returns correct grouped counts."""
        # Arrange
        user_id = await create_test_user()

        # Insert mixed keys
        for _ in range(3):
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
                user_id,
                "Classic",
            )
        for _ in range(2):
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
                user_id,
                "Winter",
            )

        # Act
        result = await repository.fetch_user_keys(user_id=user_id)

        # Assert
        assert len(result) == 2
        amounts_by_type = {row["key_type"]: row["amount"] for row in result}
        assert amounts_by_type["Classic"] == 3
        assert amounts_by_type["Winter"] == 2

    async def test_fetch_user_keys_with_filter(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test fetching keys with key_type filter."""
        # Arrange
        user_id = await create_test_user()

        # Insert mixed keys
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
            user_id,
            "Classic",
        )
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
            user_id,
            "Winter",
        )

        # Act
        result = await repository.fetch_user_keys(user_id=user_id, key_type="Classic")

        # Assert
        assert len(result) == 1
        assert result[0]["key_type"] == "Classic"
        assert result[0]["amount"] == 1


# ==============================================================================
# TESTS FOR check_user_has_reward
# ==============================================================================


class TestCheckUserHasRewardHappyPath:
    """Test happy path scenarios for check_user_has_reward."""

    async def test_check_user_has_reward_returns_none_when_not_found(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test checking for non-existent reward returns None."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.check_user_has_reward(
            user_id=user_id,
            reward_type="title",
            key_type="Classic",
            reward_name="Nonexistent Reward",
        )

        # Assert
        assert result is None

    async def test_check_user_has_reward_returns_rarity_when_found(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test checking for existing reward returns rarity."""
        # Arrange
        user_id = await create_test_user()
        reward_name = "Test Reward"
        reward_type = "title"
        key_type = "Classic"
        rarity = "common"

        # Insert reward type
        await asyncpg_conn.execute(
            """
            INSERT INTO lootbox.reward_types (name, type, key_type, rarity)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT DO NOTHING
            """,
            reward_name,
            reward_type,
            key_type,
            rarity,
        )

        # Insert user reward
        await asyncpg_conn.execute(
            """
            INSERT INTO lootbox.user_rewards (user_id, reward_type, key_type, reward_name)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            reward_type,
            key_type,
            reward_name,
        )

        # Act
        result = await repository.check_user_has_reward(
            user_id=user_id,
            reward_type=reward_type,
            key_type=key_type,
            reward_name=reward_name,
        )

        # Assert
        assert result == rarity


# ==============================================================================
# TESTS FOR fetch_all_key_types
# ==============================================================================


class TestFetchAllKeyTypesHappyPath:
    """Test happy path scenarios for fetch_all_key_types."""

    async def test_fetch_all_key_types_returns_list(
        self,
        repository: LootboxRepository,
    ) -> None:
        """Test fetching all key types returns list."""
        # Act
        result = await repository.fetch_all_key_types()

        # Assert
        assert isinstance(result, list)
        assert len(result) >= 2  # Classic and Winter from migrations
        key_names = [row["name"] for row in result]
        assert "Classic" in key_names
        assert "Winter" in key_names

    async def test_fetch_all_key_types_with_filter(
        self,
        repository: LootboxRepository,
    ) -> None:
        """Test fetching key types with filter."""
        # Act
        result = await repository.fetch_all_key_types(key_type="Classic")

        # Assert
        assert len(result) == 1
        assert result[0]["name"] == "Classic"
