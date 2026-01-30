"""Tests for RankCardRepository edge cases.

Test Coverage:
- Concurrent operations: multiple upserts to same user
- Transaction behavior: rollback, commit
- Null/empty value handling: empty strings, None values
- Boundary values: very long strings, special characters
- Integration scenarios: avatar partial updates, badge clearing
"""

import asyncio
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
# CONCURRENT OPERATIONS
# ==============================================================================


class TestConcurrentOperations:
    """Test concurrent access to rank_card tables."""

    async def test_concurrent_background_upserts_same_user(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test rapid sequential upserts to same user's background (last write wins)."""
        # Arrange
        user_id = await create_test_user()
        backgrounds = [f"bg_{i}" for i in range(10)]

        # Act - Upsert sequentially (asyncpg doesn't support concurrent ops on same connection)
        for bg in backgrounds:
            await repository.upsert_background(user_id, bg)

        # Assert - Last background should be set
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == backgrounds[-1]  # Last write wins

    async def test_concurrent_avatar_skin_and_pose_upserts(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test independent upserts of skin and pose don't interfere."""
        # Arrange
        user_id = await create_test_user()
        skin = fake.word()
        pose = fake.word()

        # Act - Upsert skin and pose sequentially (asyncpg doesn't support concurrent ops)
        await repository.upsert_avatar_skin(user_id, skin)
        await repository.upsert_avatar_pose(user_id, pose)

        # Assert - Both should be set
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == skin
        assert result["pose"] == pose

    async def test_concurrent_badge_upserts_same_user(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test rapid sequential badge upserts to same user (last write wins)."""
        # Arrange
        user_id = await create_test_user()

        badges1 = {
            "badge_name1": "first_set_1",
            "badge_type1": "type1",
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

        badges2 = {
            "badge_name1": "second_set_1",
            "badge_type1": "type1_alt",
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

        # Act - Upsert sequentially (asyncpg doesn't support concurrent ops on same connection)
        await repository.upsert_badges(user_id, **badges1)
        await repository.upsert_badges(user_id, **badges2)

        # Assert - Last write should win
        result = await repository.fetch_badges(user_id)
        assert result is not None
        assert result["badge_name1"] == "second_set_1"
        assert result["badge_type1"] == "type1_alt"


# ==============================================================================
# TRANSACTION BEHAVIOR
# ==============================================================================


class TestTransactionBehavior:
    """Test transaction commit and rollback behavior."""

    async def test_background_upsert_rollback(
        self,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test that rolled-back background upsert doesn't persist."""
        # Arrange
        repository = RankCardRepository(asyncpg_conn)
        user_id = await create_test_user()
        background = fake.word()

        # Act - Upsert in transaction, then rollback
        try:
            async with asyncpg_conn.transaction():
                await repository.upsert_background(user_id, background, conn=asyncpg_conn)
                raise Exception("Force rollback")
        except Exception:
            pass

        # Assert - Background should not be set
        result = await repository.fetch_background(user_id)
        assert result is None

    async def test_avatar_upsert_commit_persists(
        self,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test that committed avatar upsert persists."""
        # Arrange
        repository = RankCardRepository(asyncpg_conn)
        user_id = await create_test_user()
        skin = fake.word()

        # Act - Upsert in transaction, then commit
        async with asyncpg_conn.transaction():
            await repository.upsert_avatar_skin(user_id, skin, conn=asyncpg_conn)

        # Assert - Skin should be persisted
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == skin


# ==============================================================================
# NULL AND EMPTY VALUE HANDLING
# ==============================================================================


class TestNullAndEmptyValues:
    """Test handling of null and empty values."""

    async def test_background_empty_string(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting empty string as background."""
        # Arrange
        user_id = await create_test_user()

        # Act
        await repository.upsert_background(user_id, "")

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == ""

    async def test_badges_all_none_values(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting badges with all None values."""
        # Arrange
        user_id = await create_test_user()
        all_none = {
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

        # Act
        await repository.upsert_badges(user_id, **all_none)

        # Assert
        result = await repository.fetch_badges(user_id)
        assert result is not None
        for i in range(1, 7):
            assert result[f"badge_name{i}"] is None
            assert result[f"badge_type{i}"] is None


# ==============================================================================
# BOUNDARY VALUES
# ==============================================================================


class TestBoundaryValues:
    """Test boundary and extreme values."""

    async def test_background_very_long_string(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting very long background name."""
        # Arrange
        user_id = await create_test_user()
        long_name = "x" * 1000  # Very long string

        # Act
        await repository.upsert_background(user_id, long_name)

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == long_name

    async def test_background_unicode_characters(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting background with unicode characters."""
        # Arrange
        user_id = await create_test_user()
        unicode_name = "背景_🎨_नमस्ते_مرحبا"

        # Act
        await repository.upsert_background(user_id, unicode_name)

        # Assert
        result = await repository.fetch_background(user_id)
        assert result is not None
        assert result["name"] == unicode_name

    async def test_avatar_special_characters(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test upserting avatar with special characters."""
        # Arrange
        user_id = await create_test_user()
        special_skin = "skin-name_with.special!chars@#$%"
        special_pose = "pose/with\\backslashes\"quotes'"

        # Act
        await repository.upsert_avatar_skin(user_id, special_skin)
        await repository.upsert_avatar_pose(user_id, special_pose)

        # Assert
        result = await repository.fetch_avatar(user_id)
        assert result is not None
        assert result["skin"] == special_skin
        assert result["pose"] == special_pose


# ==============================================================================
# INTEGRATION SCENARIOS
# ==============================================================================


class TestIntegrationScenarios:
    """Test complex integration scenarios."""

    async def test_avatar_update_sequence_preserves_data(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test sequence of avatar updates preserves data correctly."""
        # Arrange
        user_id = await create_test_user()

        # Act - Complex sequence
        # 1. Set skin only
        await repository.upsert_avatar_skin(user_id, "skin1")
        result1 = await repository.fetch_avatar(user_id)

        # 2. Add pose
        await repository.upsert_avatar_pose(user_id, "pose1")
        result2 = await repository.fetch_avatar(user_id)

        # 3. Update skin (should preserve pose)
        await repository.upsert_avatar_skin(user_id, "skin2")
        result3 = await repository.fetch_avatar(user_id)

        # 4. Update pose (should preserve new skin)
        await repository.upsert_avatar_pose(user_id, "pose2")
        result4 = await repository.fetch_avatar(user_id)

        # Assert - Verify each step
        assert result1["skin"] == "skin1" and result1["pose"] == "Heroic"  # Default value
        assert result2["skin"] == "skin1" and result2["pose"] == "pose1"
        assert result3["skin"] == "skin2" and result3["pose"] == "pose1"
        assert result4["skin"] == "skin2" and result4["pose"] == "pose2"

    async def test_badge_progressive_fill_and_clear(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test progressively filling badges then clearing them."""
        # Arrange
        user_id = await create_test_user()

        # Act - Fill badges one by one
        await repository.upsert_badges(
            user_id,
            badge_name1="b1",
            badge_type1="t1",
            badge_name2=None,
            badge_type2=None,
            badge_name3=None,
            badge_type3=None,
            badge_name4=None,
            badge_type4=None,
            badge_name5=None,
            badge_type5=None,
            badge_name6=None,
            badge_type6=None,
        )
        result1 = await repository.fetch_badges(user_id)

        await repository.upsert_badges(
            user_id,
            badge_name1="b1",
            badge_type1="t1",
            badge_name2="b2",
            badge_type2="t2",
            badge_name3="b3",
            badge_type3="t3",
            badge_name4=None,
            badge_type4=None,
            badge_name5=None,
            badge_type5=None,
            badge_name6=None,
            badge_type6=None,
        )
        result2 = await repository.fetch_badges(user_id)

        # Clear all
        await repository.upsert_badges(
            user_id,
            badge_name1=None,
            badge_type1=None,
            badge_name2=None,
            badge_type2=None,
            badge_name3=None,
            badge_type3=None,
            badge_name4=None,
            badge_type4=None,
            badge_name5=None,
            badge_type5=None,
            badge_name6=None,
            badge_type6=None,
        )
        result3 = await repository.fetch_badges(user_id)

        # Assert
        assert result1["badge_name1"] == "b1" and result1["badge_name2"] is None
        assert result2["badge_name2"] == "b2" and result2["badge_name3"] == "b3"
        assert all(result3[f"badge_name{i}"] is None for i in range(1, 7))

    async def test_full_rank_card_customization(
        self,
        repository: RankCardRepository,
        create_test_user,
    ) -> None:
        """Test setting all rank card customization options for a user."""
        # Arrange
        user_id = await create_test_user()

        # Act - Set all customizations
        await repository.upsert_background(user_id, "custom_bg")
        await repository.upsert_avatar_skin(user_id, "custom_skin")
        await repository.upsert_avatar_pose(user_id, "custom_pose")
        await repository.upsert_badges(
            user_id,
            badge_name1="achievement1",
            badge_type1="gold",
            badge_name2="achievement2",
            badge_type2="silver",
            badge_name3="achievement3",
            badge_type3="bronze",
            badge_name4=None,
            badge_type4=None,
            badge_name5=None,
            badge_type5=None,
            badge_name6=None,
            badge_type6=None,
        )

        # Assert - Fetch all and verify
        bg = await repository.fetch_background(user_id)
        avatar = await repository.fetch_avatar(user_id)
        badges = await repository.fetch_badges(user_id)

        assert bg["name"] == "custom_bg"
        assert avatar["skin"] == "custom_skin"
        assert avatar["pose"] == "custom_pose"
        assert badges["badge_name1"] == "achievement1"
        assert badges["badge_name2"] == "achievement2"
        assert badges["badge_name3"] == "achievement3"
