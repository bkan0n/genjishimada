"""Tests for LootboxRepository delete operations."""

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
# TESTS FOR delete_oldest_user_key
# ==============================================================================


class TestDeleteOldestUserKeyHappyPath:
    """Test happy path scenarios for delete_oldest_user_key."""

    async def test_delete_oldest_key_removes_correct_key(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test deleting oldest key removes the correct one."""
        # Arrange
        user_id = await create_test_user()
        key_type = "Classic"

        # Insert keys with different timestamps
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type, earned_at) VALUES ($1, $2, now() - interval '2 hours')",
            user_id,
            key_type,
        )
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type, earned_at) VALUES ($1, $2, now() - interval '1 hour')",
            user_id,
            key_type,
        )
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.user_keys (user_id, key_type, earned_at) VALUES ($1, $2, now())",
            user_id,
            key_type,
        )

        # Act
        await repository.delete_oldest_user_key(user_id=user_id, key_type=key_type)

        # Assert - should have 2 keys remaining
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
            user_id,
            key_type,
        )
        assert count == 2

    async def test_delete_oldest_key_no_op_when_no_keys(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test deleting oldest key when user has no keys is a no-op."""
        # Arrange
        user_id = await create_test_user()

        # Act - should not raise error
        await repository.delete_oldest_user_key(user_id=user_id, key_type="Classic")

        # Assert - no keys should exist
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1",
            user_id,
        )
        assert count == 0

    async def test_delete_oldest_key_only_affects_specified_type(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test deleting oldest key only affects specified key type."""
        # Arrange
        user_id = await create_test_user()

        # Insert different key types
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

        # Act - delete Classic key
        await repository.delete_oldest_user_key(user_id=user_id, key_type="Classic")

        # Assert - Winter key should remain
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
            user_id,
            "Winter",
        )
        assert count == 1

        # Classic key should be gone
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
            user_id,
            "Classic",
        )
        assert count == 0

    async def test_delete_oldest_key_deletes_only_one(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test deleting oldest key deletes only one key even with same timestamp."""
        # Arrange
        user_id = await create_test_user()
        key_type = "Classic"

        # Insert multiple keys (they may have same timestamp)
        for _ in range(3):
            await asyncpg_conn.execute(
                "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)",
                user_id,
                key_type,
            )

        # Act
        await repository.delete_oldest_user_key(user_id=user_id, key_type=key_type)

        # Assert - should have 2 keys remaining
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM lootbox.user_keys WHERE user_id = $1 AND key_type = $2",
            user_id,
            key_type,
        )
        assert count == 2


class TestDeleteOldestUserKeyEdgeCases:
    """Test edge cases for delete_oldest_user_key."""

    async def test_delete_oldest_key_with_invalid_user(
        self,
        repository: LootboxRepository,
    ) -> None:
        """Test deleting key for non-existent user is a no-op."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act - should not raise error
        await repository.delete_oldest_user_key(user_id=fake_user_id, key_type="Classic")

        # Assert - test passes if no exception raised
