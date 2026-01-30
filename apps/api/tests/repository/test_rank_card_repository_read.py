"""Tests for RankCardRepository read operations.

Test Coverage:
- fetch_background: returns dict when set, None when not set
- fetch_avatar: returns dict with skin/pose, handles partial data, None when not set
- fetch_badges: returns dict without user_id, handles partial data, None when not set
- fetch_nickname: returns primary username or nickname fallback, handles missing user
"""

from uuid import uuid4

import pytest
from faker import Faker

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
# FETCH_BACKGROUND TESTS
# ==============================================================================


class TestFetchBackground:
    """Test fetch_background operation."""

    async def test_fetch_background_when_set(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching background returns correct value when set."""
        # Arrange
        user_id = await create_test_user()
        background_name = fake.word()
        await repository.upsert_background(user_id, background_name)

        # Act
        result = await repository.fetch_background(user_id)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert "name" in result
        assert result["name"] == background_name

    async def test_fetch_background_when_not_set(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching background returns None when not set."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_background(user_id)

        # Assert
        assert result is None

    async def test_fetch_background_non_existent_user(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test fetching background for non-existent user returns None."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act
        result = await repository.fetch_background(invalid_user_id)

        # Assert
        assert result is None


# ==============================================================================
# FETCH_AVATAR TESTS
# ==============================================================================


class TestFetchAvatar:
    """Test fetch_avatar operation."""

    async def test_fetch_avatar_with_both_skin_and_pose(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching avatar returns both skin and pose when set."""
        # Arrange
        user_id = await create_test_user()
        skin_name = fake.word()
        pose_name = fake.word()
        await repository.upsert_avatar_skin(user_id, skin_name)
        await repository.upsert_avatar_pose(user_id, pose_name)

        # Act
        result = await repository.fetch_avatar(user_id)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert "skin" in result
        assert "pose" in result
        assert result["skin"] == skin_name
        assert result["pose"] == pose_name

    async def test_fetch_avatar_with_only_skin(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching avatar with only skin set returns skin and None pose."""
        # Arrange
        user_id = await create_test_user()
        skin_name = fake.word()
        await repository.upsert_avatar_skin(user_id, skin_name)

        # Act
        result = await repository.fetch_avatar(user_id)

        # Assert
        assert result is not None
        assert result["skin"] == skin_name
        assert result["pose"] is None

    async def test_fetch_avatar_with_only_pose(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching avatar with only pose set returns pose and None skin."""
        # Arrange
        user_id = await create_test_user()
        pose_name = fake.word()
        await repository.upsert_avatar_pose(user_id, pose_name)

        # Act
        result = await repository.fetch_avatar(user_id)

        # Assert
        assert result is not None
        assert result["skin"] is None
        assert result["pose"] == pose_name

    async def test_fetch_avatar_when_not_set(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching avatar returns None when not set."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_avatar(user_id)

        # Assert
        assert result is None

    async def test_fetch_avatar_non_existent_user(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test fetching avatar for non-existent user returns None."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act
        result = await repository.fetch_avatar(invalid_user_id)

        # Assert
        assert result is None


# ==============================================================================
# FETCH_BADGES TESTS
# ==============================================================================


class TestFetchBadges:
    """Test fetch_badges operation."""

    async def test_fetch_all_badges_when_set(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching badges returns all 6 badges when set."""
        # Arrange
        user_id = await create_test_user()
        badges = {
            "badge_name1": "badge1",
            "badge_type1": "type1",
            "badge_name2": "badge2",
            "badge_type2": "type2",
            "badge_name3": "badge3",
            "badge_type3": "type3",
            "badge_name4": "badge4",
            "badge_type4": "type4",
            "badge_name5": "badge5",
            "badge_type5": "type5",
            "badge_name6": "badge6",
            "badge_type6": "type6",
        }
        await repository.upsert_badges(user_id, **badges)

        # Act
        result = await repository.fetch_badges(user_id)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        for key, value in badges.items():
            assert result[key] == value

    async def test_fetch_badges_excludes_user_id(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test that fetch_badges excludes user_id from returned dict."""
        # Arrange
        user_id = await create_test_user()
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
        await repository.upsert_badges(user_id, **badges)

        # Act
        result = await repository.fetch_badges(user_id)

        # Assert
        assert result is not None
        assert "user_id" not in result

    async def test_fetch_partial_badges_with_nulls(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching badges with some set to None."""
        # Arrange
        user_id = await create_test_user()
        badges = {
            "badge_name1": "badge1",
            "badge_type1": "type1",
            "badge_name2": None,
            "badge_type2": None,
            "badge_name3": "badge3",
            "badge_type3": "type3",
            "badge_name4": None,
            "badge_type4": None,
            "badge_name5": None,
            "badge_type5": None,
            "badge_name6": None,
            "badge_type6": None,
        }
        await repository.upsert_badges(user_id, **badges)

        # Act
        result = await repository.fetch_badges(user_id)

        # Assert
        assert result is not None
        assert result["badge_name1"] == "badge1"
        assert result["badge_type1"] == "type1"
        assert result["badge_name2"] is None
        assert result["badge_type2"] is None
        assert result["badge_name3"] == "badge3"
        assert result["badge_type3"] == "type3"
        assert result["badge_name4"] is None

    async def test_fetch_badges_when_not_set(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test fetching badges returns None when not set."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_badges(user_id)

        # Assert
        assert result is None

    async def test_fetch_badges_non_existent_user(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test fetching badges for non-existent user returns None."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act
        result = await repository.fetch_badges(invalid_user_id)

        # Assert
        assert result is None


# ==============================================================================
# FETCH_NICKNAME TESTS
# ==============================================================================


class TestFetchNickname:
    """Test fetch_nickname operation."""

    async def test_fetch_nickname_returns_discord_nickname(
        self,
        repository: RankCardRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test fetching nickname returns Discord nickname when no Overwatch username."""
        # Arrange
        nickname = fake.user_name()
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
            unique_user_id,
            nickname,
            nickname,
        )

        # Act
        result = await repository.fetch_nickname(unique_user_id)

        # Assert
        assert result == nickname

    async def test_fetch_nickname_prefers_primary_overwatch_username(
        self,
        repository: RankCardRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test fetching nickname prefers primary Overwatch username over Discord nickname."""
        # Arrange
        nickname = "discord_nick"
        ow_username = "overwatch_main"

        # Create user with Discord nickname
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
            unique_user_id,
            nickname,
            nickname,
        )

        # Add primary Overwatch username
        await asyncpg_conn.execute(
            """
            INSERT INTO users.overwatch_usernames (user_id, username, is_primary)
            VALUES ($1, $2, TRUE)
            """,
            unique_user_id,
            ow_username,
        )

        # Act
        result = await repository.fetch_nickname(unique_user_id)

        # Assert
        assert result == ow_username
        assert result != nickname

    async def test_fetch_nickname_with_non_primary_overwatch_username(
        self,
        repository: RankCardRepository,
        asyncpg_conn,
        unique_user_id: int,
    ) -> None:
        """Test fetching nickname ignores non-primary Overwatch usernames."""
        # Arrange
        nickname = "discord_nick"
        ow_username_non_primary = "overwatch_alt"

        # Create user
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3)",
            unique_user_id,
            nickname,
            nickname,
        )

        # Add non-primary Overwatch username
        await asyncpg_conn.execute(
            """
            INSERT INTO users.overwatch_usernames (user_id, username, is_primary)
            VALUES ($1, $2, FALSE)
            """,
            unique_user_id,
            ow_username_non_primary,
        )

        # Act
        result = await repository.fetch_nickname(unique_user_id)

        # Assert - Should return Discord nickname, not non-primary OW username
        assert result == nickname

    async def test_fetch_nickname_non_existent_user_returns_unknown(
        self,
        repository: RankCardRepository,
    ) -> None:
        """Test fetching nickname for non-existent user returns 'Unknown User'."""
        # Arrange
        invalid_user_id = 999999999999999999

        # Act
        result = await repository.fetch_nickname(invalid_user_id)

        # Assert
        assert result == "Unknown User"
