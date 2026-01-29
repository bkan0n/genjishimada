"""Exhaustive tests for MapsRepository.fetch_partial_map method.

Test Coverage:
- Happy path: map with creators and playtest meta
- No creators: map with no creator entries
- No playtest meta: map with no playtest data
- Primary vs non-primary creators
- Multiple creators aggregation
- Non-existent map code returns None
- Case sensitivity
- NULL fields handling
- Archived/hidden maps
- Transaction context
- Data validation: verify fields and structure
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
# HAPPY PATH TESTS
# ==============================================================================


class TestFetchPartialMapHappyPath:
    """Test happy path scenarios."""

    @pytest.mark.asyncio
    async def test_fetch_map_with_all_data(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with creators and playtest meta."""
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
    async def test_fetch_map_with_no_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with no creators."""
        map_id = await create_test_map(db_pool, unique_map_code)
        await add_playtest_meta(db_pool, map_id, initial_difficulty=5.0)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id
        assert result["creator_names"] == [None]  # LEFT JOIN with no match gives [NULL]

    @pytest.mark.asyncio
    async def test_fetch_map_with_no_playtest_meta(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with no playtest meta."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "Creator1")
        await add_creator(db_pool, map_id, user_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id
        assert result["difficulty"] is None
        assert "Creator1" in result["creator_names"]

    @pytest.mark.asyncio
    async def test_fetch_map_minimal(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with minimal data (no creators, no playtest)."""
        map_id = await create_test_map(db_pool, unique_map_code)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id
        assert result["code"] == unique_map_code
        assert result["difficulty"] is None
        assert result["creator_names"] == [None]


# ==============================================================================
# CREATOR TESTS
# ==============================================================================


class TestFetchPartialMapCreators:
    """Test creator-related scenarios."""

    @pytest.mark.asyncio
    async def test_fetch_map_with_single_primary_creator(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test map with single primary creator."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "PrimaryCreator")
        await add_creator(db_pool, map_id, user_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["creator_names"] == ["PrimaryCreator"]

    @pytest.mark.asyncio
    async def test_fetch_map_with_multiple_primary_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test map with multiple primary creators."""
        map_id = await create_test_map(db_pool, unique_map_code)

        user1_id = await create_test_user(db_pool, "Creator1")
        user2_id = await create_test_user(db_pool, "Creator2")
        user3_id = await create_test_user(db_pool, "Creator3")

        await add_creator(db_pool, map_id, user1_id, is_primary=True)
        await add_creator(db_pool, map_id, user2_id, is_primary=True)
        await add_creator(db_pool, map_id, user3_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert len(result["creator_names"]) == 3
        assert set(result["creator_names"]) == {"Creator1", "Creator2", "Creator3"}

    @pytest.mark.asyncio
    async def test_fetch_map_with_non_primary_creators_only(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test map with only non-primary creators (should not be included)."""
        map_id = await create_test_map(db_pool, unique_map_code)

        user_id = await create_test_user(db_pool, "NonPrimaryCreator")
        await add_creator(db_pool, map_id, user_id, is_primary=False)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Non-primary creators are filtered out by `is_primary` condition
        assert result["creator_names"] == [None]

    @pytest.mark.asyncio
    async def test_fetch_map_with_mixed_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test map with both primary and non-primary creators."""
        map_id = await create_test_map(db_pool, unique_map_code)

        primary_id = await create_test_user(db_pool, "PrimaryUser")
        non_primary_id = await create_test_user(db_pool, "NonPrimaryUser")

        await add_creator(db_pool, map_id, primary_id, is_primary=True)
        await add_creator(db_pool, map_id, non_primary_id, is_primary=False)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        # Only primary creator should be included
        assert result["creator_names"] == ["PrimaryUser"]


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestFetchPartialMapEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_non_existent_map_code_returns_none(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test fetching non-existent map returns None."""
        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is None

    @pytest.mark.asyncio
    async def test_case_sensitivity_of_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test that code lookup is case-sensitive."""
        code = "ABC123"
        used_codes.add(code)
        await create_test_map(db_pool, code)

        # Fetch with different case
        result = await maps_repo.fetch_partial_map("abc123")

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_archived_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching archived map still works."""
        map_id = await create_test_map(db_pool, unique_map_code, archived=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id

    @pytest.mark.asyncio
    async def test_fetch_hidden_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching hidden map still works."""
        map_id = await create_test_map(db_pool, unique_map_code, hidden=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id

    @pytest.mark.asyncio
    async def test_map_with_special_characters_in_name(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test map with special characters in map_name."""
        map_id = await create_test_map(db_pool, unique_map_code, map_name="King's Row")

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_name"] == "King's Row"


# ==============================================================================
# DATA VALIDATION TESTS
# ==============================================================================


class TestFetchPartialMapDataValidation:
    """Test data validation and field correctness."""

    @pytest.mark.asyncio
    async def test_verify_map_id_correctness(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that returned map_id matches the actual map ID."""
        map_id = await create_test_map(db_pool, unique_map_code)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert result["map_id"] == map_id

    @pytest.mark.asyncio
    async def test_difficulty_comes_from_playtest_meta(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that difficulty comes from playtest.meta, not core.maps."""
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
    async def test_creator_names_array_structure(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that creator_names is returned as a list."""
        map_id = await create_test_map(db_pool, unique_map_code)
        user_id = await create_test_user(db_pool, "ArrayTestCreator")
        await add_creator(db_pool, map_id, user_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert isinstance(result["creator_names"], list)
        assert len(result["creator_names"]) == 1

    @pytest.mark.asyncio
    async def test_all_expected_fields_present(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that all expected fields are present in result."""
        await create_test_map(db_pool, unique_map_code)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert "map_id" in result
        assert "code" in result
        assert "map_name" in result
        assert "checkpoints" in result
        assert "difficulty" in result
        assert "creator_names" in result


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestFetchPartialMapTransactions:
    """Test transaction context."""

    @pytest.mark.asyncio
    async def test_fetch_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map within a transaction."""
        map_id = await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                result = await maps_repo.fetch_partial_map(unique_map_code, conn=conn)

        assert result is not None
        assert result["map_id"] == map_id

    @pytest.mark.asyncio
    async def test_fetch_sees_uncommitted_changes_in_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that fetch sees uncommitted changes within same transaction."""
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

                # Fetch within same transaction
                result = await maps_repo.fetch_partial_map(unique_map_code, conn=conn)

                assert result is not None
                assert result["map_id"] == map_id


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestFetchPartialMapPerformance:
    """Test performance with edge cases."""

    @pytest.mark.asyncio
    async def test_map_with_many_creators(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching map with many primary creators."""
        map_id = await create_test_map(db_pool, unique_map_code)

        # Add 10 primary creators
        creator_names = []
        for i in range(10):
            nickname = f"Creator{i:02d}"
            creator_names.append(nickname)
            user_id = await create_test_user(db_pool, nickname)
            await add_creator(db_pool, map_id, user_id, is_primary=True)

        result = await maps_repo.fetch_partial_map(unique_map_code)

        assert result is not None
        assert len(result["creator_names"]) == 10
        assert set(result["creator_names"]) == set(creator_names)
