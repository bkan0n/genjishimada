"""Tests for PlaytestRepository delete operations.

Test Coverage:
- delete_completions_for_playtest: Delete completions submitted during playtest period
"""

import pytest
from faker import Faker

from repository.playtest_repository import PlaytestRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_playtests,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide playtest repository instance."""
    return PlaytestRepository(asyncpg_conn)


# ==============================================================================
# DELETE COMPLETIONS FOR PLAYTEST TESTS
# ==============================================================================


class TestDeleteCompletionsForPlaytest:
    """Test deleting completions submitted during playtest period."""

    @pytest.mark.asyncio
    async def test_delete_completions_removes_completions_after_playtest_start(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest removes completions submitted after playtest started."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()

        # Create playtest (this sets created_at timestamp)
        playtest_id = await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create a completion AFTER playtest started (will be deleted)
        completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion, verified, legacy
            )
            VALUES ($1, $2, 30.5, 'https://example.com/screenshot.png', TRUE, TRUE, FALSE)
            RETURNING id
            """,
            user_id,
            map_id,
        )

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - completion should be deleted
        exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            completion_id,
        )
        assert exists is False

    @pytest.mark.asyncio
    async def test_delete_completions_preserves_completions_before_playtest(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest preserves completions submitted before playtest."""
        # Arrange
        map_id = await create_test_map()
        user_id = await create_test_user()

        # Create completion BEFORE playtest starts
        old_completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion, verified, legacy,
                inserted_at
            )
            VALUES ($1, $2, 25.0, 'https://example.com/old.png', TRUE, TRUE, FALSE,
                    now() - interval '1 day')
            RETURNING id
            """,
            user_id,
            map_id,
        )

        # Create playtest (after the old completion)
        await asyncpg_conn.execute("SELECT pg_sleep(0.01)")  # Small delay to ensure timestamp difference
        playtest_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO playtests.meta (thread_id, map_id, initial_difficulty, completed)
            VALUES ($1, $2, 5.0, FALSE)
            RETURNING id
            """,
            unique_thread_id,
            map_id,
        )

        # Create completion AFTER playtest starts (will be deleted)
        new_completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion, verified, legacy
            )
            VALUES ($1, $2, 30.5, 'https://example.com/new.png', TRUE, TRUE, FALSE)
            RETURNING id
            """,
            user_id,
            map_id,
        )

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - old completion preserved, new completion deleted
        old_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            old_completion_id,
        )
        new_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            new_completion_id,
        )
        assert old_exists is True
        assert new_exists is False

    @pytest.mark.asyncio
    async def test_delete_completions_only_affects_playtest_map(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest only deletes for the playtest's map."""
        # Arrange
        map1_id = await create_test_map()
        map2_id = await create_test_map()
        user_id = await create_test_user()

        # Create playtest for map1
        await create_test_playtest(map1_id, thread_id=unique_thread_id)

        # Create completions for both maps
        map1_completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion, verified, legacy
            )
            VALUES ($1, $2, 30.5, 'https://example.com/screenshot.png', TRUE, TRUE, FALSE)
            RETURNING id
            """,
            user_id,
            map1_id,
        )

        map2_completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion, verified, legacy
            )
            VALUES ($1, $2, 35.0, 'https://example.com/screenshot2.png', TRUE, TRUE, FALSE)
            RETURNING id
            """,
            user_id,
            map2_id,
        )

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - map1 completion deleted, map2 completion preserved
        map1_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            map1_completion_id,
        )
        map2_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            map2_completion_id,
        )
        assert map1_exists is False
        assert map2_exists is True

    @pytest.mark.asyncio
    async def test_delete_completions_multiple_users(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest deletes from all users."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()

        # Create playtest
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create completions from multiple users
        for user_id in [user1_id, user2_id, user3_id]:
            await asyncpg_conn.execute(
                """
                INSERT INTO core.completions (
                    user_id, map_id, time, screenshot, completion, verified, legacy
                )
                VALUES ($1, $2, 30.5, 'https://example.com/screenshot.png', TRUE, TRUE, FALSE)
                """,
                user_id,
                map_id,
            )

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - all completions deleted
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM core.completions WHERE map_id = $1",
            map_id,
        )
        assert count == 0
