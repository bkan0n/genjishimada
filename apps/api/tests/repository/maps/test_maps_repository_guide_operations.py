"""Tests for MapsRepository guide operations.

Tests all guide-related methods:
- insert_guide
- check_guide_exists
- delete_guide
- update_guide
- fetch_guides

Test Coverage:
- CRUD operations for guides
- Guide visibility and fetching
- Transaction commit behavior
"""

from typing import get_args
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk.maps import MapCategory, OverwatchMap
from pytest_databases.docker.postgres import PostgresService

from repository.maps_repository import MapsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_maps,
]


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


# ==============================================================================
# CHECK_GUIDE_EXISTS TESTS
# ==============================================================================


class TestFetchGuide:
    """Test fetching guides."""

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

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user1_id)
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide2", user2_id)

        results = await maps_repo.fetch_guides(unique_map_code)

        assert len(results) == 2
        user_ids = {r["user_id"] for r in results}
        assert user_ids == {user1_id, user2_id}

    @pytest.mark.asyncio
    async def test_check_guide_exists(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test checking if guide exists for a user."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        # Should not exist initially
        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is False

        # Insert guide
        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        # Should exist now
        exists = await maps_repo.check_guide_exists(map_id, user_id)
        assert exists is True


# ==============================================================================
# DELETE GUIDE TESTS
# ==============================================================================


class TestDeleteGuide:
    """Test delete_guide method."""

    @pytest.mark.asyncio
    async def test_delete_existing_guide(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting existing guide."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide", user_id)

        deleted_count = await maps_repo.delete_guide(map_id, user_id)

        assert deleted_count == 1

        # Verify deleted
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user_id,
            )
        assert count == 0

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

        # Verify user1's guide deleted and user2's guide still exists
        async with db_pool.acquire() as conn:
            count1 = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user1_id,
            )
            count2 = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.guides WHERE map_id = $1 AND user_id = $2",
                map_id,
                user2_id,
            )

        assert count1 == 0
        assert count2 == 1


# ==============================================================================
# UPDATE_GUIDE TESTS
# ==============================================================================


class TestUpdateGuide:
    """Test update_guide method."""

    @pytest.mark.asyncio
    async def test_update_guide_changes_url(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that update changes the URL."""
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


# ==============================================================================
# GUIDE VISIBILITY TESTS
# ==============================================================================


class TestGuideVisibility:
    """Test guide visibility and fetching."""

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


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestGuideCRUDCycle:
    """Test full CRUD cycle for guides."""

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

        # Read
        results = await maps_repo.fetch_guides(unique_map_code)
        assert len(results) == 1
        assert results[0]["url"] == "https://youtube.com/guide1"

        # Update
        await maps_repo.update_guide(map_id, user_id, "https://youtube.com/guide2")

        results = await maps_repo.fetch_guides(unique_map_code)
        assert results[0]["url"] == "https://youtube.com/guide2"

        # Delete
        deleted = await maps_repo.delete_guide(map_id, user_id)
        assert deleted == 1

        # Verify deleted
        results = await maps_repo.fetch_guides(unique_map_code)
        assert len(results) == 0


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestGuideTransactions:
    """Test guide operations within transactions."""

    @pytest.mark.asyncio
    async def test_insert_guide_transaction_commit(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting guide within transaction commits."""
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
    async def test_update_guide_transaction_commit(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test updating guide within transaction commits."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "User1")

        await maps_repo.insert_guide(map_id, "https://youtube.com/guide1", user_id)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.update_guide(
                    map_id,
                    user_id,
                    "https://youtube.com/guide2",
                    conn=conn,
                )

        # Verify updated
        async with db_pool.acquire() as conn:
            url = await conn.fetchval(
                "SELECT url FROM maps.guides WHERE map_id = $1",
                map_id,
            )

        assert url == "https://youtube.com/guide2"
