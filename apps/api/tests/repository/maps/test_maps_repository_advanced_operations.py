"""Focused tests for MapsRepository advanced operations.

Tests complex repository operations:
- Quality: override_quality_votes
- Trending: fetch_trending_maps
- Medal operations: remove_map_medal_entries
- Map linking: link_map_codes, unlink_map_codes

Test Coverage:
- Core functionality
- Transaction commit scenarios
- Integration flows
"""

from typing import Any, get_args
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
    code = f"A{uuid4().hex[:5].upper()}"
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
# QUALITY OPERATIONS TESTS
# ==============================================================================


class TestOverrideQualityVotes:
    """Test override_quality_votes method."""

    @pytest.mark.asyncio
    async def test_override_quality_votes_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test overriding quality votes within transaction."""
        await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.override_quality_votes(unique_map_code, 6, conn=conn)


# ==============================================================================
# TRENDING MAPS TESTS
# ==============================================================================


class TestFetchTrendingMaps:
    """Test fetch_trending_maps method."""

    @pytest.mark.asyncio
    async def test_fetch_trending_maps_excludes_hidden_archived(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test that trending maps excludes hidden and archived maps."""
        code_visible = f"TV{uuid4().hex[:4].upper()}"
        code_hidden = f"TH{uuid4().hex[:4].upper()}"
        code_archived = f"TA{uuid4().hex[:4].upper()}"
        used_codes.update([code_visible, code_hidden, code_archived])

        await create_test_map(db_pool, code_visible)

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, hidden
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                """,
                code_hidden,
                "Nepal",
                "Classic",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                """,
                code_archived,
                "Hanamura",
                "Classic",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        results = await maps_repo.fetch_trending_maps(limit=100)

        # Hidden and archived should not appear
        codes = {r["code"] for r in results}
        assert code_hidden not in codes
        assert code_archived not in codes

    @pytest.mark.asyncio
    async def test_fetch_trending_maps_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test fetching trending maps within transaction."""
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                results = await maps_repo.fetch_trending_maps(conn=conn)

        assert isinstance(results, list)


# ==============================================================================
# MEDAL OPERATIONS TESTS
# ==============================================================================


class TestRemoveMapMedalEntries:
    """Test remove_map_medal_entries method."""

    @pytest.mark.asyncio
    async def test_remove_medal_entries_existing_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test removing medal entries for map with medals."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Insert medals
        await maps_repo.insert_medals(map_id, {"gold": 30.0, "silver": 45.0, "bronze": 60.0})

        # Remove
        await maps_repo.remove_map_medal_entries(unique_map_code)

        # Verify removed
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert count == 0

    @pytest.mark.asyncio
    async def test_remove_medal_entries_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test removing medal entries within transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)
        await maps_repo.insert_medals(map_id, {"gold": 30.0, "silver": 45.0, "bronze": 60.0})

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.remove_map_medal_entries(unique_map_code, conn=conn)

        # Verify removed
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM maps.medals WHERE map_id = $1",
                map_id,
            )

        assert count == 0


# ==============================================================================
# MAP LINKING TESTS
# ==============================================================================


class TestLinkMapCodes:
    """Test link_map_codes method."""

    @pytest.mark.asyncio
    async def test_link_two_maps(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test linking two map codes bidirectionally."""
        code1 = f"L1{uuid4().hex[:4].upper()}"
        code2 = f"L2{uuid4().hex[:4].upper()}"
        used_codes.update([code1, code2])

        await create_test_map(db_pool, code1)
        await create_test_map(db_pool, code2)

        await maps_repo.link_map_codes(code1, code2)

        # Verify bidirectional link
        async with db_pool.acquire() as conn:
            linked1 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )
            linked2 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code2,
            )

        assert linked1 == code2
        assert linked2 == code1

    @pytest.mark.asyncio
    async def test_link_maps_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test linking maps within transaction."""
        code1 = f"L3{uuid4().hex[:4].upper()}"
        code2 = f"L4{uuid4().hex[:4].upper()}"
        used_codes.update([code1, code2])

        await create_test_map(db_pool, code1)
        await create_test_map(db_pool, code2)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.link_map_codes(code1, code2, conn=conn)

        # Verify linked
        async with db_pool.acquire() as conn:
            linked1 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )

        assert linked1 == code2


class TestUnlinkMapCodes:
    """Test unlink_map_codes method."""

    @pytest.mark.asyncio
    async def test_unlink_linked_maps(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test unlinking previously linked maps."""
        code1 = f"U1{uuid4().hex[:4].upper()}"
        code2 = f"U2{uuid4().hex[:4].upper()}"
        used_codes.update([code1, code2])

        await create_test_map(db_pool, code1)
        await create_test_map(db_pool, code2)

        # Link first
        await maps_repo.link_map_codes(code1, code2)

        # Then unlink
        await maps_repo.unlink_map_codes(code1)

        # Verify both unlinked
        async with db_pool.acquire() as conn:
            linked1 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )
            linked2 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code2,
            )

        assert linked1 is None
        assert linked2 is None

    @pytest.mark.asyncio
    async def test_unlink_maps_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test unlinking maps within transaction."""
        code1 = f"U3{uuid4().hex[:4].upper()}"
        code2 = f"U4{uuid4().hex[:4].upper()}"
        used_codes.update([code1, code2])

        await create_test_map(db_pool, code1)
        await create_test_map(db_pool, code2)

        await maps_repo.link_map_codes(code1, code2)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.unlink_map_codes(code1, conn=conn)

        # Verify unlinked
        async with db_pool.acquire() as conn:
            linked1 = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )

        assert linked1 is None


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestAdvancedOperationsIntegration:
    """Test integration scenarios."""

    @pytest.mark.asyncio
    async def test_link_unlink_cycle(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test full link/unlink cycle."""
        code1 = f"I1{uuid4().hex[:4].upper()}"
        code2 = f"I2{uuid4().hex[:4].upper()}"
        used_codes.update([code1, code2])

        await create_test_map(db_pool, code1)
        await create_test_map(db_pool, code2)

        # Link
        await maps_repo.link_map_codes(code1, code2)

        async with db_pool.acquire() as conn:
            linked = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )
        assert linked == code2

        # Unlink
        await maps_repo.unlink_map_codes(code1)

        async with db_pool.acquire() as conn:
            linked = await conn.fetchval(
                "SELECT linked_code FROM core.maps WHERE code = $1",
                code1,
            )
        assert linked is None

    @pytest.mark.asyncio
    async def test_medal_operations_cycle(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test full medal insert/remove cycle."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Insert
        await maps_repo.insert_medals(map_id, {"gold": 25.0, "silver": 40.0, "bronze": 55.0})

        async with db_pool.acquire() as conn:
            medals = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )
        assert medals is not None

        # Remove
        await maps_repo.remove_map_medal_entries(unique_map_code)

        async with db_pool.acquire() as conn:
            medals = await conn.fetchrow(
                "SELECT * FROM maps.medals WHERE map_id = $1",
                map_id,
            )
        assert medals is None
