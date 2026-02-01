"""Tests for UsersRepository update operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.users_repository import UsersRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_users,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide users repository instance."""
    return UsersRepository(asyncpg_conn)


# ==============================================================================
# UPDATE USER NAMES TESTS
# ==============================================================================


class TestUpdateUserNames:
    """Test update_user_names method."""

    async def test_update_nickname_only(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test updating only nickname leaves global_name unchanged."""
        # Arrange
        original_nickname = fake.user_name()
        original_global_name = fake.user_name()
        await repository.create_user(unique_user_id, original_nickname, original_global_name)

        new_nickname = fake.user_name()

        # Act
        await repository.update_user_names(
            unique_user_id,
            nickname=new_nickname,
            update_nickname=True,
            update_global_name=False,
        )

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == new_nickname
        assert user["global_name"] == original_global_name

    async def test_update_global_name_only(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test updating only global_name leaves nickname unchanged."""
        # Arrange
        original_nickname = fake.user_name()
        original_global_name = fake.user_name()
        await repository.create_user(unique_user_id, original_nickname, original_global_name)

        new_global_name = fake.user_name()

        # Act
        await repository.update_user_names(
            unique_user_id,
            global_name=new_global_name,
            update_nickname=False,
            update_global_name=True,
        )

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == original_nickname
        assert user["global_name"] == new_global_name

    async def test_update_both_fields(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test updating both nickname and global_name."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        new_nickname = fake.user_name()
        new_global_name = fake.user_name()

        # Act
        await repository.update_user_names(
            unique_user_id,
            nickname=new_nickname,
            global_name=new_global_name,
            update_nickname=True,
            update_global_name=True,
        )

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == new_nickname
        assert user["global_name"] == new_global_name

    async def test_update_with_no_flags_set_is_noop(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test update with both flags False doesn't change anything."""
        # Arrange
        original_nickname = fake.user_name()
        original_global_name = fake.user_name()
        await repository.create_user(unique_user_id, original_nickname, original_global_name)

        # Act - Neither flag is set, so no update should happen
        await repository.update_user_names(
            unique_user_id,
            nickname=fake.user_name(),
            global_name=fake.user_name(),
            update_nickname=False,
            update_global_name=False,
        )

        # Assert - Values should be unchanged
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == original_nickname
        assert user["global_name"] == original_global_name


# ==============================================================================
# UPSERT USER NOTIFICATIONS TESTS
# ==============================================================================


class TestUpsertUserNotifications:
    """Test upsert_user_notifications method."""

    async def test_insert_new_notification_settings(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting new notification settings."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        flags = 42

        # Act
        await repository.upsert_user_notifications(unique_user_id, flags)

        # Assert
        result = await repository.fetch_user_notifications(unique_user_id)
        assert result == flags

    async def test_update_existing_notification_settings(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test updating existing notification settings."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        old_flags = 42
        new_flags = 84
        await repository.upsert_user_notifications(unique_user_id, old_flags)

        # Act
        await repository.upsert_user_notifications(unique_user_id, new_flags)

        # Assert
        result = await repository.fetch_user_notifications(unique_user_id)
        assert result == new_flags

    async def test_upsert_with_invalid_user_id_raises_error(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test upserting notification settings with invalid user_id raises error."""
        # Arrange
        # Generate a user ID that doesn't exist
        while True:
            non_existent_user_id = fake.random_int(min=900000000000000000, max=998999999999999999)
            if non_existent_user_id not in global_user_id_tracker:
                break
        flags = 42

        # Act & Assert
        with pytest.raises(Exception):  # Foreign key violation
            await repository.upsert_user_notifications(non_existent_user_id, flags)


# ==============================================================================
# UPDATE MAPS CREATORS FOR FAKE MEMBER TESTS
# ==============================================================================


class TestUpdateMapsCreatorsForFakeMember:
    """Test update_maps_creators_for_fake_member method."""

    async def test_update_creators_references(
        self,
        repository: UsersRepository,
        unique_user_id: int,
        create_test_map,
        global_code_tracker: set[str],
        asyncpg_conn,
    ):
        """Test updating maps.creators references from fake to real user."""
        # Arrange
        # Create fake member
        fake_user_id = await repository.create_fake_member(fake.user_name())

        # Create real user
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Create map with fake member as creator
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)
        map_id = await create_test_map(code, creator_id=fake_user_id)

        # Act
        await repository.update_maps_creators_for_fake_member(fake_user_id, unique_user_id)

        # Assert - Verify creator is now the real user
        creator_user_id = await asyncpg_conn.fetchval(
            "SELECT user_id FROM maps.creators WHERE map_id = $1",
            map_id,
        )
        assert creator_user_id == unique_user_id

    async def test_update_creators_no_old_references_remain(
        self,
        repository: UsersRepository,
        unique_user_id: int,
        create_test_map,
        global_code_tracker: set[str],
        asyncpg_conn,
    ):
        """Test that old fake member references are completely replaced."""
        # Arrange
        fake_user_id = await repository.create_fake_member(fake.user_name())
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Create multiple maps with fake member as creator
        map_ids = []
        for _ in range(3):
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)
            map_id = await create_test_map(code)
            map_ids.append(map_id)
            await asyncpg_conn.execute(
                "INSERT INTO maps.creators (map_id, user_id) VALUES ($1, $2)",
                map_id,
                fake_user_id,
            )

        # Act
        await repository.update_maps_creators_for_fake_member(fake_user_id, unique_user_id)

        # Assert - Verify no creators with fake_user_id remain
        remaining_fake_creators = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM maps.creators WHERE user_id = $1",
            fake_user_id,
        )
        assert remaining_fake_creators == 0

        # Verify all creators now reference real user
        real_user_creators = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM maps.creators WHERE user_id = $1 AND map_id = ANY($2::int[])",
            unique_user_id,
            map_ids,
        )
        assert real_user_creators == 3
