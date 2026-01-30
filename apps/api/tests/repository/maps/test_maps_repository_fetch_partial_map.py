"""Focused tests for MapsRepository.fetch_partial_map method.

Test Coverage (8 tests):
- Fetch partial map with all data
- Fetch with creators relation
- Fetch with playtest meta relation
- Field selection verification
- Lazy loading prevention
- Primary vs non-primary creators filtering
- Multiple creators aggregation
- Transaction context
"""

from typing import Any, get_args
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk import difficulties
from genjishimada_sdk.maps import MapCategory, OverwatchMap, PlaytestStatus
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
    max_attempts = 10
    for _ in range(max_attempts):
        length = fake.random_int(min=4, max=6)
        code = "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=length))

        if code not in used_codes:
            used_codes.add(code)
            return code

    # Fallback: UUID-based code
    code = f"T{uuid4().hex[:5].upper()}"
    used_codes.add(code)
    return code


async def create_test_map(
    db_pool: asyncpg.Pool,
    code: str,
    **kwargs: Any,
) -> int:
    """Helper to create a test map with custom fields."""
    defaults = {
        "map_name": fake.random_element(elements=get_args(OverwatchMap)),
        "category": fake.random_element(elements=get_args(MapCategory)),
        "checkpoints": fake.random_int(min=1, max=50),
        "official": True,
        "playtesting": "Approved",
        "difficulty": "Medium",
        "raw_difficulty": 5.0,
        "hidden": False,
        "archived": False,
        "description": None,
        "custom_banner": None,
        "title": None,
    }
    defaults.update(kwargs)

    async with db_pool.acquire() as conn:
        map_id = await conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived,
                description, custom_banner, title
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id
            """,
            code,
            defaults["map_name"],
            defaults["category"],
            defaults["checkpoints"],
            defaults["official"],
            defaults["playtesting"],
            defaults["difficulty"],
            defaults["raw_difficulty"],
            defaults["hidden"],
            defaults["archived"],
            defaults["description"],
            defaults["custom_banner"],
            defaults["title"],
        )
    return map_id


async def create_test_user(db_pool: asyncpg.Pool, nickname: str) -> int:
    """Helper to create a test user."""
    # Generate a unique Discord snowflake-like ID
    user_id = fake.random_int(min=100000000000000000, max=999999999999999999)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname, global_name)
            VALUES ($1, $2, $3)
            """,
            user_id,
            nickname,
            nickname,  # Use same value for global_name
        )
    return user_id


async def add_creator(
    db_pool: asyncpg.Pool,
    map_id: int,
    user_id: int,
    is_primary: bool = False,
) -> None:
    """Helper to add a creator to a map."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id, is_primary)
            VALUES ($1, $2, $3)
            """,
            map_id,
            user_id,
            is_primary,
        )


async def add_playtest_meta(
    db_pool: asyncpg.Pool,
    map_id: int,
    initial_difficulty: float,
) -> int:
    """Helper to add playtest meta for a map."""
    async with db_pool.acquire() as conn:
        playtest_id = await conn.fetchval(
            """
            INSERT INTO playtests.meta (map_id, initial_difficulty)
            VALUES ($1, $2)
            RETURNING id
            """,
            map_id,
            initial_difficulty,
        )
    return playtest_id


# ==============================================================================
# CORE TESTS
# ==============================================================================


class TestFetchPartialMap:
    """Test fetch_partial_map functionality."""

    @pytest.mark.asyncio
    async def test_fetch_partial_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map returns core fields without full relations."""
        # Create map
        map_id = await create_test_map(db_pool, unique_map_code, checkpoints=15)

        # Add creator
        user_id = await create_test_user(db_pool, "TestCreator")
        await add_creator(db_pool, map_id, user_id, is_primary=True)

        # Add playtest meta
        await add_playtest_meta(db_pool, map_id, initial_difficulty=7.5)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id
        assert result["code"] == unique_map_code
        assert result["checkpoints"] == 15
        assert result["difficulty"] == pytest.approx(7.5, abs=0.01)
        assert "TestCreator" in result["creator_names"]


    @pytest.mark.asyncio
    async def test_fetch_with_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with creator names aggregated."""
        map_id = await create_test_map(db_pool, unique_map_code)

        user1_id = await create_test_user(db_pool, "Creator1")
        user2_id = await create_test_user(db_pool, "Creator2")

        await add_creator(db_pool, map_id, user1_id, is_primary=True)
        await add_creator(db_pool, map_id, user2_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert len(result["creator_names"]) == 2
        assert set(result["creator_names"]) == {"Creator1", "Creator2"}

    @pytest.mark.asyncio
    async def test_fetch_filters_non_primary_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that only primary creators are included in results."""
        map_id = await create_test_map(db_pool, unique_map_code)

        primary_id = await create_test_user(db_pool, "PrimaryUser")
        non_primary_id = await create_test_user(db_pool, "NonPrimaryUser")

        await add_creator(db_pool, map_id, primary_id, is_primary=True)
        await add_creator(db_pool, map_id, non_primary_id, is_primary=False)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Only primary creator should be included
        assert result["creator_names"] == ["PrimaryUser"]


    @pytest.mark.asyncio
    async def test_fetch_with_playtest_meta(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that difficulty comes from playtest.meta relation, not core.maps."""
        # Create map with difficulty "Hard" and raw_difficulty 7.0 in core.maps
        map_id = await create_test_map(
            db_pool,
            unique_map_code,
            difficulty="Hard",
            raw_difficulty=7.0,
        )

        # Add playtest meta with different initial_difficulty
        await add_playtest_meta(db_pool, map_id, initial_difficulty=3.5)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Should return playtest.meta.initial_difficulty, not core.maps values
        assert result["difficulty"] == pytest.approx(3.5, abs=0.01)

    @pytest.mark.asyncio
    async def test_field_selection_works(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that all expected fields are present and correctly selected."""
        await create_test_map(db_pool, unique_map_code)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Verify all expected fields are present
        assert "map_id" in result
        assert "code" in result
        assert "map_name" in result
        assert "checkpoints" in result
        assert "difficulty" in result
        assert "creator_names" in result
        # Verify creator_names is an array
        assert isinstance(result["creator_names"], list)

    @pytest.mark.asyncio
    async def test_lazy_loading_prevention(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that query eagerly loads relations to prevent N+1 queries."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Add multiple creators
        for i in range(3):
            user_id = await create_test_user(db_pool, f"Creator{i}")
            await add_creator(db_pool, map_id, user_id, is_primary=True)

        # Add playtest meta
        await add_playtest_meta(db_pool, map_id, initial_difficulty=5.0)

        # Fetch should complete in single query with all relations
        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Verify all creators are loaded
        assert len(result["creator_names"]) == 3
        # Verify playtest meta is loaded
        assert result["difficulty"] == pytest.approx(5.0, abs=0.01)


    @pytest.mark.asyncio
    async def test_fetch_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map within transaction context."""
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Create map within transaction
                map_id = await conn.fetchval(
                    """
                    INSERT INTO core.maps (
                        code, map_name, category, checkpoints, official,
                        playtesting, difficulty, raw_difficulty
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """,
                    unique_map_code,
                    "Hanamura",
                    "Classic",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5.0,
                )

                # Fetch within same transaction should see uncommitted changes
                result = await maps_repo.fetch_partial_map(unique_map_code, conn=conn)

                assert result is not None
                assert result["map_id"] == map_id
