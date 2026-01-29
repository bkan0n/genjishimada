"""Exhaustive tests for MapsRepository entity operations.

Tests insert/delete operations for:
- Creators (insert_creators, delete_creators)
- Mechanics (insert_mechanics, delete_mechanics)
- Restrictions (insert_restrictions, delete_restrictions)
- Tags (insert_tags, delete_tags)
- Medals (insert_medals, delete_medals)

Test Coverage:
- Happy path: insert single/multiple entities
- Delete operations
- Empty/None inputs
- Duplicate handling
- Foreign key violations
- Transaction context
- Validation and error cases
"""

from typing import Any, get_args
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk.maps import MapCategory, OverwatchMap
from pytest_databases.docker.postgres import PostgresService

from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError
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
    code = f"E{uuid4().hex[:5].upper()}"
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
# CREATORS TESTS - INSERT
# ==============================================================================


class TestInsertCreators:
    """Test insert_creators method."""

    @pytest.mark.asyncio
    async def test_insert_single_creator(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting single creator."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")

        await maps_repo.insert_creators(map_id, [{"user_id": user_id, "is_primary": True}])

        # Verify insertion
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert result is not None
        assert result["user_id"] == user_id
        assert result["is_primary"] is True

    @pytest.mark.asyncio
    async def test_insert_multiple_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting multiple creators."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "Creator1")
        user2_id = await create_test_user(db_pool, "Creator2")
        user3_id = await create_test_user(db_pool, "Creator3")

        creators = [
            {"user_id": user1_id, "is_primary": True},
            {"user_id": user2_id, "is_primary": False},
            {"user_id": user3_id, "is_primary": False},
        ]

        await maps_repo.insert_creators(map_id, creators)

        # Verify all inserted
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_creator_defaults_is_primary_to_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that is_primary defaults to False if not specified."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")

        # Don't specify is_primary
        await maps_repo.insert_creators(map_id, [{"user_id": user_id}])

        async with db_pool.acquire() as conn:
            is_primary = await conn.fetchval(
                "SELECT is_primary FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert is_primary is False

    @pytest.mark.asyncio
    async def test_insert_creators_empty_list(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting empty list does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_creators(map_id, [])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_creators_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting None does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_creators(map_id, None)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_duplicate_creator_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting duplicate creator raises UniqueConstraintViolationError."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")

        # Insert once
        await maps_repo.insert_creators(map_id, [{"user_id": user_id}])

        # Try to insert again
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.insert_creators(map_id, [{"user_id": user_id}])

        assert exc_info.value.table == "maps.creators"

    @pytest.mark.asyncio
    async def test_insert_creator_with_non_existent_user_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting creator with non-existent user_id raises ForeignKeyViolationError."""
        map_id = await create_test_map(db_pool, unique_map_code)
        fake_user_id = 999999999999999999

        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await maps_repo.insert_creators(map_id, [{"user_id": fake_user_id}])

        assert exc_info.value.table == "maps.creators"

    @pytest.mark.asyncio
    async def test_insert_creator_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting creator within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_creators(
                    map_id,
                    [{"user_id": user_id, "is_primary": True}],
                    conn=conn,
                )

        # Verify committed
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 1


# ==============================================================================
# CREATORS TESTS - DELETE
# ==============================================================================


class TestDeleteCreators:
    """Test delete_creators method."""

    @pytest.mark.asyncio
    async def test_delete_all_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting all creators for a map."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user1_id = await create_test_user(db_pool, "Creator1")
        user2_id = await create_test_user(db_pool, "Creator2")

        # Insert creators
        await maps_repo.insert_creators(
            map_id,
            [{"user_id": user1_id}, {"user_id": user2_id}],
        )

        # Delete all
        await maps_repo.delete_creators(map_id)

        # Verify deleted
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_creators_with_no_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting creators when none exist (no error)."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Should not raise error
        await maps_repo.delete_creators(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_creators_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting creators within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")

        await maps_repo.insert_creators(map_id, [{"user_id": user_id}])

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.delete_creators(map_id, conn=conn)

        # Verify deleted
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 0


# ==============================================================================
# MECHANICS TESTS - INSERT
# ==============================================================================


class TestInsertMechanics:
    """Test insert_mechanics method."""

    @pytest.mark.asyncio
    async def test_insert_single_mechanic(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting single mechanic."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Bhop"])

        # Verify insertion
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_multiple_mechanics(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting multiple mechanics."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Bhop", "Slide", "Dash"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_mechanics_empty_list(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting empty list does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, [])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_mechanics_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting None does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, None)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_non_existent_mechanic(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting non-existent mechanic name does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Non-existent mechanic
        await maps_repo.insert_mechanics(map_id, ["NonExistentMechanic"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_duplicate_mechanic_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting duplicate mechanic raises UniqueConstraintViolationError."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Bhop"])

        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.insert_mechanics(map_id, ["Bhop"])

        assert exc_info.value.table == "maps.mechanic_links"

    @pytest.mark.asyncio
    async def test_insert_mechanics_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting mechanics within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_mechanics(map_id, ["Slide"], conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_mechanics_case_sensitive(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that mechanic lookup is case-sensitive."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # "bhop" vs "Bhop"
        await maps_repo.insert_mechanics(map_id, ["bhop"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        # Should be 0 if case-sensitive, 1 if case-insensitive
        # Based on seed data, "Bhop" exists, "bhop" doesn't
        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_mixed_valid_invalid_mechanics(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting mix of valid and invalid mechanics only inserts valid ones."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Bhop", "InvalidMechanic", "Slide"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        # Only 2 valid mechanics should be inserted
        assert count == 2


# ==============================================================================
# MECHANICS TESTS - DELETE
# ==============================================================================


class TestDeleteMechanics:
    """Test delete_mechanics method."""

    @pytest.mark.asyncio
    async def test_delete_all_mechanics(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting all mechanics for a map."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Bhop", "Slide"])
        await maps_repo.delete_mechanics(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_mechanics_with_no_mechanics(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting mechanics when none exist."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.delete_mechanics(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_mechanics_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting mechanics within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_mechanics(map_id, ["Dash"])

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.delete_mechanics(map_id, conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.mechanic_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0


# ==============================================================================
# RESTRICTIONS TESTS - INSERT
# ==============================================================================


class TestInsertRestrictions:
    """Test insert_restrictions method."""

    @pytest.mark.asyncio
    async def test_insert_single_restriction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting single restriction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["Bhop"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_multiple_restrictions(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting multiple restrictions."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["Bhop", "Triple Jump", "Multi Climb"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_restrictions_empty_list(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting empty list does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, [])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_restrictions_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting None does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, None)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_non_existent_restriction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting non-existent restriction does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["NonExistentRestriction"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_duplicate_restriction_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting duplicate restriction raises error."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["Bhop"])

        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.insert_restrictions(map_id, ["Bhop"])

        assert exc_info.value.table == "maps.restriction_links"

    @pytest.mark.asyncio
    async def test_insert_restrictions_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting restrictions within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_restrictions(map_id, ["Wall Climb"], conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1


# ==============================================================================
# RESTRICTIONS TESTS - DELETE
# ==============================================================================


class TestDeleteRestrictions:
    """Test delete_restrictions method."""

    @pytest.mark.asyncio
    async def test_delete_all_restrictions(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting all restrictions for a map."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["Bhop", "Triple Jump"])
        await maps_repo.delete_restrictions(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_restrictions_with_no_restrictions(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting restrictions when none exist."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.delete_restrictions(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_restrictions_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting restrictions within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_restrictions(map_id, ["Dash Start"])

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.delete_restrictions(map_id, conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.restriction_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0


# ==============================================================================
# TAGS TESTS - INSERT
# ==============================================================================


class TestInsertTags:
    """Test insert_tags method."""

    @pytest.mark.asyncio
    async def test_insert_single_tag(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting single tag."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["XP Based"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1

    @pytest.mark.asyncio
    async def test_insert_multiple_tags(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting multiple tags."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["XP Based", "Other Heroes", "Custom Grav/Speed"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 3

    @pytest.mark.asyncio
    async def test_insert_tags_empty_list(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting empty list does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, [])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_tags_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting None does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, None)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_non_existent_tag(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting non-existent tag does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["NonExistentTag"])

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_insert_duplicate_tag_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting duplicate tag raises error."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["XP Based"])

        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.insert_tags(map_id, ["XP Based"])

        assert exc_info.value.table == "maps.tag_links"

    @pytest.mark.asyncio
    async def test_insert_tags_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting tags within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_tags(map_id, ["Other Heroes"], conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 1


# ==============================================================================
# TAGS TESTS - DELETE
# ==============================================================================


class TestDeleteTags:
    """Test delete_tags method."""

    @pytest.mark.asyncio
    async def test_delete_all_tags(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting all tags for a map."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["XP Based", "Other Heroes"])
        await maps_repo.delete_tags(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_tags_with_no_tags(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting tags when none exist."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.delete_tags(map_id)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_delete_tags_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting tags within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_tags(map_id, ["Custom Grav/Speed"])

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.delete_tags(map_id, conn=conn)

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.tag_links WHERE map_id = $1",
                map_id,
            )

        assert count == 0


# ==============================================================================
# MEDALS TESTS - INSERT
# ==============================================================================


class TestInsertMedals:
    """Test insert_medals method."""

    @pytest.mark.asyncio
    async def test_insert_medals_all_times(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting medals with all times."""
        map_id = await create_test_map(db_pool, unique_map_code)

        medals = {"gold": 30.0, "silver": 45.0, "bronze": 60.0}
        await maps_repo.insert_medals(map_id, medals)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is not None
        assert float(result["gold"]) == pytest.approx(30.0, abs=0.01)
        assert float(result["silver"]) == pytest.approx(45.0, abs=0.01)
        assert float(result["bronze"]) == pytest.approx(60.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_insert_medals_partial_times(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting medals with only some times."""
        map_id = await create_test_map(db_pool, unique_map_code)

        medals = {"gold": 25.0, "silver": None, "bronze": 55.0}
        await maps_repo.insert_medals(map_id, medals)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is not None
        assert float(result["gold"]) == pytest.approx(25.0, abs=0.01)
        assert result["silver"] is None
        assert float(result["bronze"]) == pytest.approx(55.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_insert_medals_upsert_behavior(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that insert_medals uses UPSERT (updates on conflict)."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Insert initial medals
        await maps_repo.insert_medals(map_id, {"gold": 30.0, "silver": 45.0, "bronze": 60.0})

        # Insert again with different values (should update)
        await maps_repo.insert_medals(map_id, {"gold": 20.0, "silver": 35.0, "bronze": 50.0})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        # Should have updated values, not duplicates
        assert result is not None
        assert float(result["gold"]) == pytest.approx(20.0, abs=0.01)
        assert float(result["silver"]) == pytest.approx(35.0, abs=0.01)
        assert float(result["bronze"]) == pytest.approx(50.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_insert_medals_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting None does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_medals(map_id, None)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_insert_medals_empty_dict(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting empty dict does nothing."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_medals(map_id, {})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_insert_medals_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test inserting medals within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        medals = {"gold": 40.0, "silver": 55.0, "bronze": 70.0}

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.insert_medals(map_id, medals, conn=conn)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is not None
        assert float(result["gold"]) == pytest.approx(40.0, abs=0.01)


# ==============================================================================
# MEDALS TESTS - DELETE
# ==============================================================================


class TestDeleteMedals:
    """Test delete_medals method."""

    @pytest.mark.asyncio
    async def test_delete_medals(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting medals for a map."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_medals(map_id, {"gold": 30.0, "silver": 45.0, "bronze": 60.0})
        await maps_repo.delete_medals(map_id)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_medals_with_no_medals(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting medals when none exist."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.delete_medals(map_id)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_medals_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test deleting medals within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_medals(map_id, {"gold": 35.0, "silver": 50.0, "bronze": 65.0})

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.delete_medals(map_id, conn=conn)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is None
