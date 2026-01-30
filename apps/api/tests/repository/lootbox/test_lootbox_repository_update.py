"""Tests for LootboxRepository update operations."""

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
# TESTS FOR add_user_coins
# ==============================================================================


class TestAddUserCoinsHappyPath:
    """Test happy path scenarios for add_user_coins."""

    async def test_add_coins_creates_user_if_not_exists(
        self,
        repository: LootboxRepository,
        unique_user_id,
        asyncpg_conn,
    ) -> None:
        """Test adding coins creates user record if it doesn't exist."""
        # Act
        await repository.add_user_coins(user_id=unique_user_id, amount=100)

        # Assert - user should be created with coins
        result = await asyncpg_conn.fetchrow(
            "SELECT id, coins FROM core.users WHERE id = $1",
            unique_user_id,
        )
        assert result is not None
        assert result["coins"] == 100

    async def test_add_coins_adds_to_existing_balance(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test adding coins to existing user adds to balance."""
        # Arrange
        user_id = await create_test_user()

        # Set initial coins
        await asyncpg_conn.execute(
            "UPDATE core.users SET coins = 50 WHERE id = $1",
            user_id,
        )

        # Act
        await repository.add_user_coins(user_id=user_id, amount=25)

        # Assert
        result = await asyncpg_conn.fetchval(
            "SELECT coins FROM core.users WHERE id = $1",
            user_id,
        )
        assert result == 75

    async def test_add_zero_coins(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test adding zero coins doesn't change balance."""
        # Arrange
        user_id = await create_test_user()
        await asyncpg_conn.execute(
            "UPDATE core.users SET coins = 100 WHERE id = $1",
            user_id,
        )

        # Act
        await repository.add_user_coins(user_id=user_id, amount=0)

        # Assert
        result = await asyncpg_conn.fetchval(
            "SELECT coins FROM core.users WHERE id = $1",
            user_id,
        )
        assert result == 100


# ==============================================================================
# TESTS FOR upsert_user_xp
# ==============================================================================


class TestUpsertUserXpHappyPath:
    """Test happy path scenarios for upsert_user_xp."""

    async def test_upsert_xp_creates_record_if_not_exists(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test upserting XP creates record if it doesn't exist."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.upsert_user_xp(
            user_id=user_id,
            xp_amount=100,
            multiplier=1.0,
        )

        # Assert
        assert result["previous_amount"] == 0
        assert result["new_amount"] == 100

    async def test_upsert_xp_adds_to_existing_xp(
        self,
        repository: LootboxRepository,
        create_test_user,
        asyncpg_conn,
    ) -> None:
        """Test upserting XP adds to existing amount."""
        # Arrange
        user_id = await create_test_user()

        # Insert initial XP
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.xp (user_id, amount) VALUES ($1, $2)",
            user_id,
            50,
        )

        # Act
        result = await repository.upsert_user_xp(
            user_id=user_id,
            xp_amount=25,
            multiplier=1.0,
        )

        # Assert
        assert result["previous_amount"] == 50
        assert result["new_amount"] == 75

    async def test_upsert_xp_applies_multiplier(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test upserting XP applies multiplier correctly."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.upsert_user_xp(
            user_id=user_id,
            xp_amount=100,
            multiplier=2.0,
        )

        # Assert
        assert result["previous_amount"] == 0
        assert result["new_amount"] == 200  # 100 * 2.0

    async def test_upsert_xp_floors_result(
        self,
        repository: LootboxRepository,
        create_test_user,
    ) -> None:
        """Test upserting XP floors the result."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.upsert_user_xp(
            user_id=user_id,
            xp_amount=100,
            multiplier=1.5,
        )

        # Assert
        assert result["new_amount"] == 150  # floor(100 * 1.5)


# ==============================================================================
# TESTS FOR update_xp_multiplier
# ==============================================================================


class TestUpdateXpMultiplierHappyPath:
    """Test happy path scenarios for update_xp_multiplier."""

    async def test_update_xp_multiplier_changes_value(
        self,
        repository: LootboxRepository,
        asyncpg_conn,
    ) -> None:
        """Test updating XP multiplier changes the value."""
        # Arrange - ensure a multiplier exists
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.xp_multiplier (value) VALUES (1.0) ON CONFLICT DO NOTHING"
        )

        # Act
        await repository.update_xp_multiplier(multiplier=2.5)

        # Assert
        result = await asyncpg_conn.fetchval(
            "SELECT value FROM lootbox.xp_multiplier LIMIT 1"
        )
        assert float(result) == 2.5


# ==============================================================================
# TESTS FOR update_active_key
# ==============================================================================


class TestUpdateActiveKeyHappyPath:
    """Test happy path scenarios for update_active_key."""

    async def test_update_active_key_changes_value(
        self,
        repository: LootboxRepository,
        asyncpg_conn,
    ) -> None:
        """Test updating active key changes the value."""
        # Arrange - ensure active key exists
        await asyncpg_conn.execute(
            "INSERT INTO lootbox.active_key (key) VALUES ('Classic') ON CONFLICT DO NOTHING"
        )

        # Act
        await repository.update_active_key(key_type="Winter")

        # Assert
        result = await asyncpg_conn.fetchval(
            "SELECT key FROM lootbox.active_key LIMIT 1"
        )
        assert result == "Winter"
