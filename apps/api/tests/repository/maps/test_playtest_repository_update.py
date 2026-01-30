"""Tests for PlaytestRepository update operations.

Test Coverage:
- update_playtest_meta: Dynamic field updates for playtest metadata
- associate_thread: Associate Discord thread with playtest
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
# UPDATE PLAYTEST META TESTS
# ==============================================================================


class TestUpdatePlaytestMeta:
    """Test updating playtest metadata fields."""

    @pytest.mark.asyncio
    async def test_update_single_field(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating a single field updates only that field."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            initial_difficulty=5.0,
            completed=False,
        )

        # Act
        await repository.update_playtest_meta(
            unique_thread_id,
            {"initial_difficulty": 7.5},
        )

        # Assert - verify field was updated
        result = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert float(result["initial_difficulty"]) == 7.5
        assert result["completed"] is False  # Other field unchanged

    @pytest.mark.asyncio
    async def test_update_multiple_fields(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating multiple fields at once."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            initial_difficulty=5.0,
            verification_id=None,
            completed=False,
        )

        verification_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Act
        await repository.update_playtest_meta(
            unique_thread_id,
            {
                "initial_difficulty": 8.5,
                "verification_id": verification_id,
                "completed": True,
            },
        )

        # Assert - verify all fields were updated
        result = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert float(result["initial_difficulty"]) == 8.5
        assert result["verification_id"] == verification_id
        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_update_completed_flag_to_true(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test marking playtest as completed."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            completed=False,
        )

        # Act
        await repository.update_playtest_meta(
            unique_thread_id,
            {"completed": True},
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT completed FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert result["completed"] is True

    @pytest.mark.asyncio
    async def test_update_verification_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating verification_id."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            verification_id=None,
        )

        verification_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Act
        await repository.update_playtest_meta(
            unique_thread_id,
            {"verification_id": verification_id},
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT verification_id FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert result["verification_id"] == verification_id

    @pytest.mark.asyncio
    async def test_update_difficulty_within_valid_range(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        asyncpg_conn,
    ) -> None:
        """Test updating initial_difficulty with valid value."""
        # Arrange
        map_id = await create_test_map()
        await create_test_playtest(
            map_id,
            thread_id=unique_thread_id,
            initial_difficulty=5.0,
        )

        # Act
        await repository.update_playtest_meta(
            unique_thread_id,
            {"initial_difficulty": 9.75},
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT initial_difficulty FROM playtests.meta WHERE thread_id = $1",
            unique_thread_id,
        )
        assert float(result["initial_difficulty"]) == 9.75


# ==============================================================================
# ASSOCIATE THREAD TESTS
# ==============================================================================


class TestAssociateThread:
    """Test associating Discord thread with playtest."""

    @pytest.mark.asyncio
    async def test_associate_thread_updates_thread_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        asyncpg_conn,
        unique_thread_id: int,
    ) -> None:
        """Test associate_thread updates the thread_id for a playtest."""
        # Arrange
        map_id = await create_test_map()

        # Create playtest without thread_id
        playtest_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO playtests.meta (map_id, initial_difficulty, completed)
            VALUES ($1, 5.0, FALSE)
            RETURNING id
            """,
            map_id,
        )

        # Act
        await repository.associate_thread(playtest_id, unique_thread_id)

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT thread_id FROM playtests.meta WHERE id = $1",
            playtest_id,
        )
        assert result["thread_id"] == unique_thread_id

    @pytest.mark.asyncio
    async def test_associate_thread_replaces_existing_thread_id(
        self,
        repository: PlaytestRepository,
        create_test_map,
        create_test_playtest,
        unique_thread_id: int,
        global_thread_id_tracker: set[int],
        asyncpg_conn,
    ) -> None:
        """Test associate_thread can replace an existing thread_id."""
        # Arrange
        map_id = await create_test_map()

        # Generate first thread ID
        while True:
            old_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            if old_thread_id not in global_thread_id_tracker:
                global_thread_id_tracker.add(old_thread_id)
                break

        playtest_id = await create_test_playtest(map_id, thread_id=old_thread_id)

        # Act - associate new thread
        await repository.associate_thread(playtest_id, unique_thread_id)

        # Assert - thread_id was updated
        result = await asyncpg_conn.fetchrow(
            "SELECT thread_id FROM playtests.meta WHERE id = $1",
            playtest_id,
        )
        assert result["thread_id"] == unique_thread_id
        assert result["thread_id"] != old_thread_id

    @pytest.mark.asyncio
    async def test_associate_thread_preserves_other_fields(
        self,
        repository: PlaytestRepository,
        create_test_map,
        asyncpg_conn,
        unique_thread_id: int,
    ) -> None:
        """Test associate_thread only updates thread_id, preserving other fields."""
        # Arrange
        map_id = await create_test_map()
        verification_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Create playtest with various fields set
        playtest_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO playtests.meta (
                map_id, initial_difficulty, verification_id, completed
            )
            VALUES ($1, 7.5, $2, FALSE)
            RETURNING id
            """,
            map_id,
            verification_id,
        )

        # Act
        await repository.associate_thread(playtest_id, unique_thread_id)

        # Assert - verify other fields unchanged
        result = await asyncpg_conn.fetchrow(
            "SELECT * FROM playtests.meta WHERE id = $1",
            playtest_id,
        )
        assert result["thread_id"] == unique_thread_id
        assert float(result["initial_difficulty"]) == 7.5
        assert result["verification_id"] == verification_id
        assert result["completed"] is False
        assert result["map_id"] == map_id
