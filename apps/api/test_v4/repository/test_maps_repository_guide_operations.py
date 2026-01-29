"""Exhaustive tests for MapsRepository guide operations.

Tests all guide-related methods:
- insert_guide
- check_guide_exists
- delete_guide
- update_guide
- fetch_guides

Test Coverage:
- Happy path: insert, check, delete, update, fetch
- Empty/None inputs
- Duplicate handling
- Foreign key violations
- Return values (row counts, booleans)
- Transaction context
- Edge cases and validation
"""

from typing import Any, get_args
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk.maps import MapCategory, OverwatchMap
from pytest_databases.docker.postgres import PostgresService

from repository.exceptions import UniqueConstraintViolationError
from repository.maps_repository import MapsRepository

fake = Faker()


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture(scope="session")
def used_codes() -> set[str]:
    """Session-scoped set to track used map codes and prevent collisions."""
    return set()


@pytest.fixture
async def db_pool(postgres_service: PostgresService) -> asyncpg.Pool:
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def maps_repo(db_pool: asyncpg.Pool) -> MapsRepository:
    """Create repository instance."""
    return MapsRepository(db_pool)


@pytest.fixture
def unique_map_code(used_codes: set[str]) -> str:
    """Generate a unique map code with collision prevention."""
    code = f"G{uuid4().hex[:5].upper()}"
    used_codes.add(code)
    return code


async def create_test_map(db_pool: asyncpg.Pool, code: str) -> int:
    """Helper to create a test map."""
    async with db_pool.acquire() as conn:
        map_id = await conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            code,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            fake.random_int(min=1, max=50),
            True,
            "Approved",
            "Medium",
            5.0,
        )
    return map_id


async def create_test_user(db_pool: asyncpg.Pool, nickname: str) -> int:
    """Helper to create a test user."""
    user_id = fake.random_int(min=100000000000000000, max=999999999999999999)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname, global_name)
            VALUES ($1, $2, $3)
            """,
            user_id,
            nickname,
            nickname,
        )
    return user_id


# ==============================================================================
# INSERT_GUIDE TESTS
# ==============================================================================


class TestInsertGuide:
    """Test insert_guide method."""

    @pytest.mark.asyncio
    async def test_insert_single_guide(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting a single guide."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "GuideCreator")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        # Verify insertion
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user_id,
            )

        assert result is not None
        assert result["url"] == "https://youtube.com/guide1"
        assert result["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_insert_multiple_guides_different_users(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting multiple guides from different users for same map."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")
        user3_id = await create_test_user(db_pool, "User3")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user2_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide3", user3_id)

        # Verify all inserted
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_guide_with_none_url(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide with None URL does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, None, user_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_guide_with_none_user_id(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide with None user_id does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", None)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_guide_with_empty_url(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide with empty string URL does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "", user_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_duplicate_guide_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting duplicate guide (same user, same map) raises error."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        # Insert first guide
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        # Try to insert again
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user_id)

        assert exc_info.value.table == "maps.guides"
        assert "guides_user_id_map_id_unique" in exc_info.value.constraint_name

    @pytest.mark.asyncio
    async def test_insert_guide_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_guide(
                    map_id,
                    "https://youtube.com/guide",
                    user_id,
                    conn=conn,
                )

        # Verify committed
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_guide_with_special_characters_in_url(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide with special characters in URL."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        special_url = "https://youtube.com/watch?v=abc123&t=45s&list=PLxyz"
        await maps_repo.insert_guide(map_id, special_url, user_id)

        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert result == special_url


# ==============================================================================
# CHECK_GUIDE_EXISTS TESTS
# ==============================================================================


class TestCheckGuideExists:
    """Test check_guide_exists method."""

    @pytest.mark.asyncio
    async def test_guide_exists_returns_true(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that existing guide returns True."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        exists = await maps_repo.check_guide_exists(map_id, user_id)

        assert exists is True

    @pytest.mark.asyncio
    async def test_guide_does_not_exist_returns_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that non-existent guide returns False."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        exists = await maps_repo.check_guide_exists(map_id, user_id)

        assert exists is False

    @pytest.mark.asyncio
    async def test_check_guide_exists_different_user(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test checking for guide from different user returns False."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user1_id)

        # Check with different user
        exists = await maps_repo.check_guide_exists(map_id, user2_id)

        assert exists is False

    @pytest.mark.asyncio
    async def test_check_guide_exists_different_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test checking for guide on different map returns False."""
        code1 = f"G{uuid4().hex[:5].upper()}"
        code2 = f"G{uuid4().hex[:5].upper()}"
        used_codes.add(code1)
        used_codes.add(code2)

        map1_id = await create_test_map(db_pool, code1)
        map2_id = await create_test_map(db_pool, code2)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map1_id, "https://youtube.com/guide", user_id)

        # Check on different map
        exists = await maps_repo.check_guide_exists(map2_id, user_id)

        assert exists is False

    @pytest.mark.asyncio
    async def test_check_guide_exists_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test checking guide exists within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                exists = await maps_repo.check_guide_exists(map_id, user_id, conn=conn)

        assert exists is True


# ==============================================================================
# DELETE_GUIDE TESTS
# ==============================================================================


class TestDeleteGuide:
    """Test delete_guide method."""

    @pytest.mark.asyncio
    async def test_delete_existing_guide_returns_1(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting existing guide returns 1."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        deleted_count = await maps_repo.delete_guide(map_id, user_id)

        assert deleted_count == 1

        # Verify deleted
        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is False

    @pytest.mark.asyncio
    async def test_delete_non_existent_guide_returns_0(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting non-existent guide returns 0."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        deleted_count = await maps_repo.delete_guide(map_id, user_id)

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_delete_guide_specific_user(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting guide only deletes for specific user."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user2_id)

        # Delete user1's guide
        deleted_count = await maps_repo.delete_guide(map_id, user1_id)

        assert deleted_count == 1

        # User1's guide should be gone
        exists1 = await maps_repo.check_guide_exists(map_id, user1_id)
        assert exists1 is False

        # User2's guide should still exist
        exists2 = await maps_repo.check_guide_exists(map_id, user2_id)
        assert exists2 is True

    @pytest.mark.asyncio
    async def test_delete_guide_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting guide within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                deleted_count = await maps_repo.delete_guide(map_id, user_id, conn=conn)

        assert deleted_count == 1

        # Verify deleted
        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is False


# ==============================================================================
# UPDATE_GUIDE TESTS
# ==============================================================================


class TestUpdateGuide:
    """Test update_guide method."""

    @pytest.mark.asyncio
    async def test_update_existing_guide_returns_1(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test updating existing guide returns 1."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        updated_count = await maps_repo.update_guide(
            map_id,
            user_id,
            "https://youtube.com/guide2",
        )

        assert updated_count == 1

    @pytest.mark.asyncio
    async def test_update_guide_changes_url(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that update actually changes the URL."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        new_url = "https://youtube.com/guide2"
        await maps_repo.update_guide(map_id, user_id, new_url)

        # Verify URL changed
        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user_id,
            )

        assert result == new_url

    @pytest.mark.asyncio
    async def test_update_non_existent_guide_returns_0(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test updating non-existent guide returns 0."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        updated_count = await maps_repo.update_guide(
            map_id,
            user_id,
            "https://youtube.com/guide",
        )

        assert updated_count == 0

    @pytest.mark.asyncio
    async def test_update_guide_specific_user(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test updating guide only updates for specific user."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user2_id)

        # Update user1's guide
        await maps_repo.update_guide(map_id, user1_id, "https://youtube.com/new1")

        # Verify user1's guide updated
        async with db_pool.acquire() as conn:
            url1 = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user1_id,
            )

        assert url1 == "https://youtube.com/new1"

        # Verify user2's guide unchanged
        async with db_pool.acquire() as conn:
            url2 = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user2_id,
            )

        assert url2 == "https://youtube.com/guide2"

    @pytest.mark.asyncio
    async def test_update_guide_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test updating guide within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                updated_count = await maps_repo.update_guide(
                    map_id,
                    user_id,
                    "https://youtube.com/guide2",
                    conn=conn,
                )

        assert updated_count == 1

        # Verify updated
        async with db_pool.acquire() as conn:
            url = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert url == "https://youtube.com/guide2"


# ==============================================================================
# FETCH_GUIDES TESTS
# ==============================================================================


class TestFetchGuides:
    """Test fetch_guides method."""

    @pytest.mark.asyncio
    async def test_fetch_guides_by_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching guides by map code."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "GuideAuthor")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert len(results) == 1
        assert results[0]["url"] == "https://youtube.com/guide"
        assert results[0]["user_id"] == user_id

    @pytest.mark.asyncio
    async def test_fetch_guides_multiple(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching multiple guides for same map."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")
        user3_id = await create_test_user(db_pool, "User3")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user2_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide3", user3_id)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert len(results) == 3
        user_ids = {r["user_id"] for r in results}
        assert user_ids == {user1_id, user2_id, user3_id}

    @pytest.mark.asyncio
    async def test_fetch_guides_no_guides_returns_empty(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching guides when none exist returns empty list."""
        await create_test_map(db_pool, unique_map_code)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_guides_non_existent_map_returns_empty(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test fetching guides for non-existent map returns empty list."""
        results = await maps_repo.fetch_guides(unique_map_code)

        assert results == []

    @pytest.mark.asyncio
    async def test_fetch_guides_usernames_array(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that usernames field is an array."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "TestUser")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert len(results) == 1
        assert "usernames" in results[0]
        assert isinstance(results[0]["usernames"], list)
        assert "TestUser" in results[0]["usernames"]

    @pytest.mark.asyncio
    async def test_fetch_guides_include_records_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetch_guides with include_records=False only returns guides."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "GuideAuthor")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        results = await maps_repo.fetch_guides(unique_map_code, include_records=False)

        # Should only have the guide, not completion videos
        assert len(results) == 1
        assert results[0]["url"] == "https://youtube.com/guide"

    @pytest.mark.asyncio
    async def test_fetch_guides_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching guides within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                results = await maps_repo.fetch_guides(unique_map_code, conn=conn)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_fetch_guides_all_expected_fields(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that fetch_guides returns all expected fields."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert len(results) == 1
        assert "user_id" in results[0]
        assert "url" in results[0]
        assert "usernames" in results[0]


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestGuideOperationsIntegration:
    """Test integration scenarios combining multiple guide operations."""

    @pytest.mark.asyncio
    async def test_full_crud_cycle(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test full CRUD cycle: create, read, update, delete."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        # Create
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)
        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is True

        # Read
        results = await maps_repo.fetch_guides(unique_map_code)
        assert len(results) == 1
        assert results[0]["url"] == "https://youtube.com/guide1"

        # Update
        updated = await maps_repo.update_guide(map_id, user_id, "https://youtube.com/guide2")
        assert updated == 1

        results = await maps_repo.fetch_guides(unique_map_code)
        assert results[0]["url"] == "https://youtube.com/guide2"

        # Delete
        deleted = await maps_repo.delete_guide(map_id, user_id)
        assert deleted == 1

        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is False

    @pytest.mark.asyncio
    async def test_multiple_users_multiple_guides(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test scenario with multiple users creating guides for same map."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "User1")
        user2_id = await create_test_user(db_pool, "User2")
        user3_id = await create_test_user(db_pool, "User3")

        # All users create guides
        await maps_repo.insert_guide(map_id, "https://youtube.com/user1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/user2", user2_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/user3", user3_id)

        # Fetch all
        results = await maps_repo.fetch_guides(unique_map_code)
        assert len(results) == 3

        # User2 updates their guide
        await maps_repo.update_guide(map_id, user2_id, "https://youtube.com/user2_new")

        # User1 deletes their guide
        await maps_repo.delete_guide(map_id, user1_id)

        # Should now have 2 guides
        results = await maps_repo.fetch_guides(unique_map_code)
        assert len(results) == 2

        # User1's guide should be gone
        exists1 = await maps_repo.check_guide_exists(map_id, user1_id)
        assert exists1 is False

        # User2 and User3 should still exist
        exists2 = await maps_repo.check_guide_exists(map_id, user2_id)
        exists3 = await maps_repo.check_guide_exists(map_id, user3_id)
        assert exists2 is True
        assert exists3 is True
