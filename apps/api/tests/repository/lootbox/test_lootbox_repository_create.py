"""Tests for LootboxRepository create operations (inserts)."""

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


@pytest.fixture
async def setup_lootbox_reference_data(asyncpg_conn):
    """Set up minimal lootbox reference data for testing.

    Key types (Classic, Winter) are already inserted by migrations.
    This fixture adds test reward types for testing.
    """
    # Insert reward types (key types already exist from migrations)
    await asyncpg_conn.execute(
        """
        INSERT INTO lootbox.reward_types (name, type, key_type, rarity)
        VALUES
            ('Test Reward', 'title', 'Classic', 'common'),
            ('Reward 1', 'title', 'Classic', 'common'),
            ('Reward 2', 'title', 'Winter', 'rare'),
            ('Reward 3', 'banner', 'Classic', 'common')
        ON CONFLICT (name, type, key_type) DO NOTHING
        """
    )


# ==============================================================================
# TESTS FOR insert_user_reward
# ==============================================================================


class TestInsertUserRewardHappyPath:
    """Test happy path scenarios for insert_user_reward."""

    async def test_insert_user_reward_with_valid_data(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
        setup_lootbox_reference_data,
    ) -> None:
        """Test inserting a user reward with valid data succeeds."""
        # Arrange
        user_id = await create_test_user()

        # Use key types from migrations (Classic, Winter) and rewards from fixture
        reward_type = "title"
        key_type = "Classic"
        reward_name = "Test Reward"

        # Act
        await repository.insert_user_reward(
            user_id=user_id,
            reward_type=reward_type,
            key_type=key_type,
            reward_name=reward_name,
        )

        # Assert - verify the reward was inserted
        result = await asyncpg_conn.fetchrow(
            """
            SELECT user_id, reward_type, key_type, reward_name
            FROM lootbox.user_rewards
            WHERE user_id = $1 AND reward_name = $2
            """,
            user_id,
            reward_name,
        )
        assert result is not None
        assert result["user_id"] == user_id
        assert result["reward_type"] == reward_type
        assert result["key_type"] == key_type
        assert result["reward_name"] == reward_name

    async def test_insert_multiple_rewards_same_user(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
        setup_lootbox_reference_data,
    ) -> None:
        """Test inserting multiple rewards for the same user."""
        # Arrange
        user_id = await create_test_user()
        rewards = [
            ("title", "Classic", "Reward 1"),
            ("title", "Winter", "Reward 2"),
            ("banner", "Classic", "Reward 3"),
        ]

        # Act
        for reward_type, key_type, reward_name in rewards:
            await repository.insert_user_reward(
                user_id=user_id,
                reward_type=reward_type,
                key_type=key_type,
                reward_name=reward_name,
            )

        # Assert
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_rewards WHERE user_id = $1",
            user_id,
        )
        assert count == 3


class TestInsertUserRewardErrorCases:
    """Test error handling for insert_user_reward."""

    async def test_insert_reward_invalid_user_raises_error(
        self,
        repository: LootboxRepository,
    ) -> None:
        """Test inserting reward with non-existent user_id raises error."""
        # Arrange
        fake_user_id = 999999999999999999
        reward_type = "title"
        key_type = "Classic"
        reward_name = "Test Reward"

        # Act & Assert
        with pytest.raises(Exception):  # asyncpg.ForeignKeyViolationError or similar
            await repository.insert_user_reward(
                user_id=fake_user_id,
                reward_type=reward_type,
                key_type=key_type,
                reward_name=reward_name,
            )


# ==============================================================================
# TESTS FOR insert_user_key
# ==============================================================================


class TestInsertUserKeyHappyPath:
    """Test happy path scenarios for insert_user_key."""

    async def test_insert_user_key_with_valid_data(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
        setup_lootbox_reference_data,
    ) -> None:
        """Test inserting a user key with valid data succeeds."""
        # Arrange
        user_id = await create_test_user()
        key_type = "Classic"

        # Act
        await repository.insert_user_key(user_id=user_id, key_type=key_type)

        # Assert - verify the key was inserted
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM lootbox.user_keys
            WHERE user_id = $1 AND key_type = $2
            """,
            user_id,
            key_type,
        )
        assert count == 1

    async def test_insert_multiple_keys_same_type(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
        setup_lootbox_reference_data,
    ) -> None:
        """Test inserting multiple keys of the same type for a user."""
        # Arrange
        user_id = await create_test_user()
        key_type = "Classic"
        num_keys = 5

        # Act
        for _ in range(num_keys):
            await repository.insert_user_key(user_id=user_id, key_type=key_type)

        # Assert
        count = await asyncpg_conn.fetchval(
            """
            SELECT COUNT(*)
            FROM lootbox.user_keys
            WHERE user_id = $1 AND key_type = $2
            """,
            user_id,
            key_type,
        )
        assert count == num_keys

    async def test_insert_keys_different_types(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
        setup_lootbox_reference_data,
    ) -> None:
        """Test inserting keys of different types for a user."""
        # Arrange
        user_id = await create_test_user()
        key_types = ["Classic", "Winter", "Classic"]  # Can have duplicates

        # Act
        for key_type in key_types:
            await repository.insert_user_key(user_id=user_id, key_type=key_type)

        # Assert
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1",
            user_id,
        )
        assert count == 3


class TestInsertUserKeyErrorCases:
    """Test error handling for insert_user_key."""

    async def test_insert_key_invalid_user_raises_error(
        self,
        repository: LootboxRepository,
    ) -> None:
        """Test inserting key with non-existent user_id raises error."""
        # Arrange
        fake_user_id = 999999999999999999
        key_type = "Classic"

        # Act & Assert
        with pytest.raises(Exception):  # asyncpg.ForeignKeyViolationError or similar
            await repository.insert_user_key(user_id=fake_user_id, key_type=key_type)


# ==============================================================================
# TESTS FOR insert_active_key
# ==============================================================================


class TestInsertActiveKeyHappyPath:
    """Test happy path scenarios for insert_active_key."""

    async def test_insert_active_key_with_valid_user(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test inserting active key for valid user succeeds."""
        # Arrange
        user_id = await create_test_user()

        # Set up active key in the table (assumes seeds have this table)
        # First check if active_key exists and set one if needed
        active_key_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM lootbox.active_key LIMIT 1)"
        )

        if not active_key_exists:
            # Insert a default active key for testing
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.active_key (key) VALUES ($1)",
                "Classic",
            )

        # Act
        await repository.insert_active_key(user_id=user_id)

        # Assert - verify the key was inserted
        result = await asyncpg_conn.fetchrow(
            """
            SELECT key_type
            FROM lootbox.user_keys
            WHERE user_id = $1
            ORDER BY earned_at DESC
            LIMIT 1
            """,
            user_id,
        )
        assert result is not None
        assert result["key_type"] is not None

    async def test_insert_active_key_multiple_times(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test inserting active key multiple times for same user."""
        # Arrange
        user_id = await create_test_user()

        # Ensure active key exists
        active_key_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM lootbox.active_key LIMIT 1)"
        )
        if not active_key_exists:
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.active_key (key) VALUES ($1)",
                "Classic",
            )

        # Act
        await repository.insert_active_key(user_id=user_id)
        await repository.insert_active_key(user_id=user_id)
        await repository.insert_active_key(user_id=user_id)

        # Assert
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1",
            user_id,
        )
        assert count == 3


class TestInsertActiveKeyErrorCases:
    """Test error handling for insert_active_key."""

    async def test_insert_active_key_invalid_user_raises_error(
        self,
        repository: LootboxRepository,
        asyncpg_conn,
    ) -> None:
        """Test inserting active key with non-existent user_id raises error."""
        # Arrange
        fake_user_id = 999999999999999999

        # Ensure active key exists
        active_key_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM lootbox.active_key LIMIT 1)"
        )
        if not active_key_exists:
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.active_key (key) VALUES ($1)",
                "Classic",
            )

        # Act & Assert
        with pytest.raises(Exception):  # asyncpg.ForeignKeyViolationError or similar
            await repository.insert_active_key(user_id=fake_user_id)

    async def test_insert_active_key_when_table_empty(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test inserting active key when active_key table is empty."""
        # Arrange
        user_id = await create_test_user()

        # Clear active_key table
        await asyncpg_conn.execute("DELETE FROM lootbox.active_key")

        # Act - Should insert nothing (LIMIT 1 returns no rows)
        await repository.insert_active_key(user_id=user_id)

        # Assert - no keys should be inserted
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1",
            user_id,
        )
        assert count == 0
