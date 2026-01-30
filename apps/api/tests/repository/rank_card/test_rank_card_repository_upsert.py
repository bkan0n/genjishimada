"""Tests for RankCardRepository upsert operations.

Test Coverage:
- upsert_background: insert, update, foreign key violations
- upsert_avatar_skin: insert, update, partial updates with pose
- upsert_avatar_pose: insert, update, partial updates with skin
- upsert_badges: insert, update, partial updates, null handling
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.exceptions import ForeignKeyViolationError
from repository.rank_card_repository import RankCardRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_rank_card,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide rank_card repository instance."""
    return RankCardRepository(asyncpg_conn)


# ==============================================================================
# UPSERT_BACKGROUND TESTS
# ==============================================================================


class TestUpsertBackground:
    """Test upsert_background operation."""

    async def test_insert_background_first_time(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test inserting background for user who has none set."""
        # Arrange
        user_id = await create_test_user()
        background_name = fake.word()

        # Act
        await repository.upsert_background(user_id, background_name)

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == background_name

    async def test_update_background_when_exists(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating background replaces existing value."""
        # Arrange
        user_id = await create_test_user()
        old_background = fake.word()
        new_background = fake.word()

        # Insert first background
        await repository.upsert_background(user_id, old_background)

        # Act - Update to new background
        await repository.upsert_background(user_id, new_background)

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == new_background
        assert result["name"] != old_background

    async def test_upsert_background_invalid_user_raises_error(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test upserting background with non-existent user raises foreign key error."""
        # Arrange
        invalid_user_id = 999999999999999999  # Non-existent user

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError):
            await repository.upsert_background(invalid_user_id, fake.word())

    async def test_upsert_background_empty_string(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting empty string background."""
        # Arrange
        user_id = await create_test_user()

        # Act
        await repository.upsert_background(user_id, "")

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == ""

    async def test_upsert_background_special_characters(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting background with special characters."""
        # Arrange
        user_id = await create_test_user()
        special_name = "background_with-special.chars!@#$%"

        # Act
        await repository.upsert_background(user_id, special_name)

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == special_name


# ==============================================================================
# UPSERT_AVATAR_SKIN TESTS
# ==============================================================================


class TestUpsertAvatarSkin:
    """Test upsert_avatar_skin operation."""

    async def test_insert_skin_first_time(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test inserting avatar skin for user who has none set."""
        # Arrange
        user_id = await create_test_user()
        skin_name = fake.word()

        # Act
        await repository.upsert_avatar_skin(user_id, skin_name)

        # Assert
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == skin_name
        assert result["pose"] == "Heroic"  # Default value from schema

    async def test_update_skin_when_exists(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating avatar skin replaces existing value."""
        # Arrange
        user_id = await create_test_user()
        old_skin = fake.word()
        new_skin = fake.word()

        await repository.upsert_avatar_skin(user_id, old_skin)

        # Act
        await repository.upsert_avatar_skin(user_id, new_skin)

        # Assert
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == new_skin
        assert result["skin"] != old_skin

    async def test_update_skin_preserves_existing_pose(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating skin preserves existing pose value."""
        # Arrange
        user_id = await create_test_user()
        skin_name = fake.word()
        pose_name = fake.word()

        # Set both skin and pose
        await repository.upsert_avatar_skin(user_id, "initial_skin")
        await repository.upsert_avatar_pose(user_id, pose_name)

        # Act - Update skin
        await repository.upsert_avatar_skin(user_id, skin_name)

        # Assert - Pose should be preserved
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == skin_name
        assert result["pose"] == pose_name

    async def test_upsert_avatar_skin_invalid_user_raises_error(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test upserting skin with non-existent user raises foreign key error."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError):
            await repository.upsert_avatar_skin(invalid_user_id, fake.word())


# ==============================================================================
# UPSERT_AVATAR_POSE TESTS
# ==============================================================================


class TestUpsertAvatarPose:
    """Test upsert_avatar_pose operation."""

    async def test_insert_pose_first_time(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test inserting avatar pose for user who has none set."""
        # Arrange
        user_id = await create_test_user()
        pose_name = fake.word()

        # Act
        await repository.upsert_avatar_pose(user_id, pose_name)

        # Assert
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["pose"] == pose_name
        assert result["skin"] == "Overwatch 1"  # Default value from schema

    async def test_update_pose_when_exists(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating avatar pose replaces existing value."""
        # Arrange
        user_id = await create_test_user()
        old_pose = fake.word()
        new_pose = fake.word()

        await repository.upsert_avatar_pose(user_id, old_pose)

        # Act
        await repository.upsert_avatar_pose(user_id, new_pose)

        # Assert
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["pose"] == new_pose
        assert result["pose"] != old_pose

    async def test_update_pose_preserves_existing_skin(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating pose preserves existing skin value."""
        # Arrange
        user_id = await create_test_user()
        skin_name = fake.word()
        pose_name = fake.word()

        # Set both skin and pose
        await repository.upsert_avatar_skin(user_id, skin_name)
        await repository.upsert_avatar_pose(user_id, "initial_pose")

        # Act - Update pose
        await repository.upsert_avatar_pose(user_id, pose_name)

        # Assert - Skin should be preserved
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == skin_name
        assert result["pose"] == pose_name

    async def test_upsert_avatar_pose_invalid_user_raises_error(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test upserting pose with non-existent user raises foreign key error."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError):
            await repository.upsert_avatar_pose(invalid_user_id, fake.word())


# ==============================================================================
# UPSERT_BADGES TESTS
# ==============================================================================


class TestUpsertBadges:
    """Test upsert_badges operation."""

    async def test_insert_all_badges_first_time(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test inserting all 6 badges for user who has none set."""
        # Arrange
        user_id = await create_test_user()
        badges = {
            "badge_name1": fake.word(),
            "badge_type1": fake.word(),
            "badge_name2": fake.word(),
            "badge_type2": fake.word(),
            "badge_name3": fake.word(),
            "badge_type3": fake.word(),
            "badge_name4": fake.word(),
            "badge_type4": fake.word(),
            "badge_name5": fake.word(),
            "badge_type5": fake.word(),
            "badge_name6": fake.word(),
            "badge_type6": fake.word(),
        }

        # Act
        await repository.upsert_badges(user_id, **badges)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        for key, value in badges.items():
            assert result[key] == value

    async def test_update_all_badges_when_exist(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating all badges replaces existing values."""
        # Arrange
        user_id = await create_test_user()

        old_badges = {
            "badge_name1": "old1",
            "badge_type1": "type1",
            "badge_name2": "old2",
            "badge_type2": "type2",
            "badge_name3": "old3",
            "badge_type3": "type3",
            "badge_name4": "old4",
            "badge_type4": "type4",
            "badge_name5": "old5",
            "badge_type5": "type5",
            "badge_name6": "old6",
            "badge_type6": "type6",
        }

        new_badges = {
            "badge_name1": "new1",
            "badge_type1": "newtype1",
            "badge_name2": "new2",
            "badge_type2": "newtype2",
            "badge_name3": "new3",
            "badge_type3": "newtype3",
            "badge_name4": "new4",
            "badge_type4": "newtype4",
            "badge_name5": "new5",
            "badge_type5": "newtype5",
            "badge_name6": "new6",
            "badge_type6": "newtype6",
        }

        await repository.upsert_badges(user_id, **old_badges)

        # Act
        await repository.upsert_badges(user_id, **new_badges)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        for key, value in new_badges.items():
            assert result[key] == value

    async def test_upsert_partial_badges_with_nulls(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting some badges as None (partial configuration)."""
        # Arrange
        user_id = await create_test_user()
        partial_badges = {
            "badge_name1": fake.word(),
            "badge_type1": fake.word(),
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": fake.word(),
            "badge_type3": fake.word(),
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }

        # Act
        await repository.upsert_badges(user_id, **partial_badges)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        assert result["badge_name1"] == partial_badges["badge_name1"]
        assert result["badge_type1"] == partial_badges["badge_type1"]
        assert result["badge_name2"] is None
        assert result["badge_type2"] is None
        assert result["badge_name3"] == partial_badges["badge_name3"]
        assert result["badge_type3"] == partial_badges["badge_type3"]
        assert result["badge_name4"] is None
        assert result["badge_name5"] is None
        assert result["badge_name6"] is None

    async def test_update_partial_badges_preserves_others(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test updating some badges preserves others (partial update)."""
        # Arrange
        user_id = await create_test_user()

        # Set initial badges (all 6)
        initial_badges = {
            "badge_name1": "keep1",
            "badge_type1": "type1",
            "badge_name2": "keep2",
            "badge_type2": "type2",
            "badge_name3": "keep3",
            "badge_type3": "type3",
            "badge_name4": "keep4",
            "badge_type4": "type4",
            "badge_name5": "keep5",
            "badge_type5": "type5",
            "badge_name6": "keep6",
            "badge_type6": "type6",
        }
        await repository.upsert_badges(user_id, **initial_badges)

        # Act - Update only badges 1 and 3
        updated_badges = {
            "badge_name1": "new1",
            "badge_type1": "newtype1",
            "badge_name2": "keep2",  # Keep same
            "badge_type2": "type2",
            "badge_name3": "new3",
            "badge_type3": "newtype3",
            "badge_name4": "keep4",  # Keep same
            "badge_type4": "type4",
            "badge_name5": "keep5",
            "badge_type5": "type5",
            "badge_name6": "keep6",
            "badge_type6": "type6",
        }
        await repository.upsert_badges(user_id, **updated_badges)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        assert result["badge_name1"] == "new1"
        assert result["badge_type1"] == "newtype1"
        assert result["badge_name2"] == "keep2"
        assert result["badge_type2"] == "type2"
        assert result["badge_name3"] == "new3"
        assert result["badge_type3"] == "newtype3"

    async def test_clear_all_badges_with_nulls(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test clearing all badges by setting them to None."""
        # Arrange
        user_id = await create_test_user()

        # Set initial badges
        initial_badges = {
            "badge_name1": fake.word(),
            "badge_type1": fake.word(),
            "badge_name2": fake.word(),
            "badge_type2": fake.word(),
            "badge_name3": fake.word(),
            "badge_type3": fake.word(),
            "badge_name4": fake.word(),
            "badge_type4": fake.word(),
            "badge_name5": fake.word(),
            "badge_type5": fake.word(),
            "badge_name6": fake.word(),
            "badge_type6": fake.word(),
        }
        await repository.upsert_badges(user_id, **initial_badges)

        # Act - Clear all badges
        null_badges = {
            "badge_name1": None,
            "badge_type1": None,
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }
        await repository.upsert_badges(user_id, **null_badges)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        for i in range(1, 7):
            assert result[f"badge_name{i}"] is None
            assert result[f"badge_type{i}"] is None

    async def test_upsert_badges_invalid_user_raises_error(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test upserting badges with non-existent user raises foreign key error."""
        # Arrange
        invalid_user_id = 999999999999999999
        badges = {
            "badge_name1": fake.word(),
            "badge_type1": fake.word(),
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": None,
            "badge_type3": None,
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError):
            await repository.upsert_badges(invalid_user_id, **badges)

