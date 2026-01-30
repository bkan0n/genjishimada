"""Streamlined tests for MapsRepository entity operations.

Tests insert/delete operations for:
- Creators (insert_creators, delete_creators)
- Mechanics (insert_mechanics, delete_mechanics)
- Restrictions (insert_restrictions, delete_restrictions)
- Tags (insert_tags, delete_tags)
- Medals (insert_medals, delete_medals)

Test Coverage:
- Basic insert single/multiple entities
- Delete operations
- Transaction support for critical operations
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

        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE map_id = $1",
                map_id,
            )

        assert count == 3

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

        await maps_repo.insert_creators(
            map_id,
            [{"user_id": user1_id}, {"user_id": user2_id}],
        )

        await maps_repo.delete_creators(map_id)

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
    async def test_insert_medals_upsert_behavior(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that insert_medals uses UPSERT (updates on conflict)."""
        map_id = await create_test_map(db_pool, unique_map_code)

        await maps_repo.insert_medals(map_id, {"gold": 30.0, "silver": 45.0, "bronze": 60.0})
        await maps_repo.insert_medals(map_id, {"gold": 20.0, "silver": 35.0, "bronze": 50.0})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert result is not None
        assert float(result["gold"]) == pytest.approx(20.0, abs=0.01)
        assert float(result["silver"]) == pytest.approx(35.0, abs=0.01)
        assert float(result["bronze"]) == pytest.approx(50.0, abs=0.01)


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
