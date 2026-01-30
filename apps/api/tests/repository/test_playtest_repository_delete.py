"""Tests for PlaytestRepository delete operations.

Test Coverage:
- delete_completions_for_playtest: Delete all completions for a playtest
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


@pytest.fixture
async def create_completion_for_playtest(asyncpg_conn):
    """Factory to create completions associated with a playtest thread."""

    async def _create(user_id: int, map_id: int, thread_id: int) -> int:
        completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion,
                verified, legacy, verification_id
            )
            VALUES ($1, $2, 30.5, 'https://example.com/screenshot.png', TRUE, TRUE, FALSE, $3)
            RETURNING id
            """,
            user_id,
            map_id,
            thread_id,
        )
        return completion_id

    return _create


# ==============================================================================
# DELETE COMPLETIONS FOR PLAYTEST TESTS
# ==============================================================================


class TestDeleteCompletionsForPlaytest:
    """Test deleting all completions for a playtest."""

    @pytest.mark.asyncio
    async def test_delete_completions_removes_all_completions(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        create_completion_for_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest removes all completions."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        user3_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create multiple completions for this playtest
        await create_completion_for_playtest(user1_id, map_id, unique_thread_id)
        await create_completion_for_playtest(user2_id, map_id, unique_thread_id)
        await create_completion_for_playtest(user3_id, map_id, unique_thread_id)

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - all completions for this playtest should be deleted
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM core.completions WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_completions_only_affects_specific_playtest(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        create_completion_for_playtest,
        unique_thread_id: int,
        global_thread_id_tracker: set[int],
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest only deletes for specific thread."""
        # Arrange - create two playtests with completions
        map1_id = await create_test_map()
        map2_id = await create_test_map()
        user_id = await create_test_user()

        # Generate second thread ID
        while True:
            thread_id_2 = fake.random_int(min=100000000000000000, max=999999999999999999)
            if thread_id_2 not in global_thread_id_tracker:
                global_thread_id_tracker.add(thread_id_2)
                break

        await create_test_playtest(map1_id, thread_id=unique_thread_id)
        await create_test_playtest(map2_id, thread_id=thread_id_2)

        # Create completions for both playtests
        await create_completion_for_playtest(user_id, map1_id, unique_thread_id)
        await create_completion_for_playtest(user_id, map2_id, thread_id_2)

        # Act - delete completions for first playtest only
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - first playtest's completions deleted, second preserved
        count_thread1 = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM core.completions WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        count_thread2 = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM core.completions WHERE playtest_thread_id = $1",
            thread_id_2,
        )
        assert count_thread1 == 0
        assert count_thread2 == 1

    @pytest.mark.asyncio
    async def test_delete_completions_when_no_completions_is_no_op(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
    ) -> None:
        """Test delete_completions_for_playtest is no-op when no completions exist."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Act & Assert - should not raise
        await repository.delete_completions_for_playtest(unique_thread_id)

    @pytest.mark.asyncio
    async def test_delete_completions_for_non_existent_thread(
        self,
        repository: PlaytestRepository,
    ) -> None:
        """Test deleting completions for non-existent thread doesn't raise."""
        # Arrange
        non_existent_thread_id = 999999999999999999

        # Act & Assert - should not raise
        await repository.delete_completions_for_playtest(non_existent_thread_id)

    @pytest.mark.asyncio
    async def test_delete_completions_preserves_non_playtest_completions(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_user,
        create_test_playtest,
        create_completion_for_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test delete_completions_for_playtest doesn't delete completions without playtest_thread_id."""
        # Arrange
        map_id = await create_test_map()
        user1_id = await create_test_user()
        user2_id = await create_test_user()
        await create_test_playtest(map_id, thread_id=unique_thread_id)

        # Create completion for playtest
        await create_completion_for_playtest(user1_id, map_id, unique_thread_id)

        # Create completion NOT for playtest (playtest_thread_id = NULL)
        regular_completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                user_id, map_id, time, screenshot, completion,
                verified, legacy
            )
            VALUES ($1, $2, 25.0, 'https://example.com/screenshot2.png', TRUE, TRUE, FALSE)
            RETURNING id
            """,
            user2_id,
            map_id,
        )

        # Act
        await repository.delete_completions_for_playtest(unique_thread_id)

        # Assert - playtest completion deleted, regular completion preserved
        playtest_count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM core.completions WHERE playtest_thread_id = $1",
            unique_thread_id,
        )
        regular_exists = await asyncpg_conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.completions WHERE id = $1)",
            regular_completion_id,
        )
        assert playtest_count == 0
        assert regular_exists is True
