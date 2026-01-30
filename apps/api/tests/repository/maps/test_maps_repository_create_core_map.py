"""Tests for MapsRepository.create_core_map method.

Test Coverage:
- Happy path: create with required fields
- Happy path: create with optional fields
- Transaction handling: commit and rollback
- Constraint smoke tests: duplicate code, enum validation
"""

from typing import Any, get_args
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk import difficulties
from genjishimada_sdk.maps import MapCategory, OverwatchMap, PlaytestStatus
from pytest_databases.docker.postgres import PostgresService

from repository.exceptions import UniqueConstraintViolationError
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
    """Generate a unique map code with collision prevention.

    Retries up to 10 times if a collision is detected.
    """
    max_attempts = 10
    for _ in range(max_attempts):
        length = fake.random_int(min=4, max=6)
        code = "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=length))

        if code not in used_codes:
            used_codes.add(code)
            return code

    # Fallback: use timestamp-based code to guarantee uniqueness
    import time

    timestamp = str(int(time.time() * 1000))[-6:]
    code = f"T{timestamp[:5]}"
    used_codes.add(code)
    return code


@pytest.fixture
def minimal_map_data(unique_map_code: str) -> dict[str, Any]:
    """Create minimal valid map data (only required fields)."""
    diff = fake.random_element(elements=["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"])
    raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[diff]  # type: ignore

    return {
        "code": unique_map_code,
        "map_name": fake.random_element(elements=get_args(OverwatchMap)),
        "category": fake.random_element(elements=get_args(MapCategory)),
        "checkpoints": fake.random_int(min=1, max=50),
        "official": fake.boolean(),
        "playtesting": fake.random_element(elements=get_args(PlaytestStatus)),
        "difficulty": diff,
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2),
        # Optional fields defaults
        "hidden": fake.boolean(),
        "archived": fake.boolean(),
        "description": None,
        "custom_banner": None,
        "title": None,
    }


@pytest.fixture
def complete_map_data(unique_map_code: str) -> dict[str, Any]:
    """Create complete map data with all optional fields populated."""
    diff = fake.random_element(elements=["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"])
    raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[diff]  # type: ignore

    return {
        "code": unique_map_code,
        "map_name": fake.random_element(elements=get_args(OverwatchMap)),
        "category": fake.random_element(elements=get_args(MapCategory)),
        "checkpoints": fake.random_int(min=1, max=50),
        "official": fake.boolean(),
        "playtesting": fake.random_element(elements=get_args(PlaytestStatus)),
        "difficulty": diff,
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2),
        "hidden": fake.boolean(),
        "archived": fake.boolean(),
        "description": fake.sentence(nb_words=15),
        "custom_banner": fake.url(),
        "title": fake.sentence(nb_words=3)[:50],  # Max 50 chars
    }


# ==============================================================================
# HAPPY PATH TESTS - MINIMAL DATA
# ==============================================================================


class TestCreateCoreMapHappyPathMinimal:
    """Test creating maps with minimal required fields."""

    @pytest.mark.asyncio
    async def test_create_with_minimal_required_fields(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating a map with only required fields returns valid ID."""
        map_id = await maps_repo.create_core_map(minimal_map_data)

        assert isinstance(map_id, int)
        assert map_id > 0

    @pytest.mark.asyncio
    async def test_created_map_has_correct_values(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that all fields are stored correctly."""
        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result["code"] == minimal_map_data["code"]
        assert result["map_name"] == minimal_map_data["map_name"]
        assert result["category"] == minimal_map_data["category"]
        assert result["checkpoints"] == minimal_map_data["checkpoints"]
        assert result["official"] == minimal_map_data["official"]
        assert result["playtesting"] == minimal_map_data["playtesting"]
        assert result["difficulty"] == minimal_map_data["difficulty"]
        assert float(result["raw_difficulty"]) == pytest.approx(minimal_map_data["raw_difficulty"], abs=0.01)
        assert result["hidden"] == minimal_map_data["hidden"]
        assert result["archived"] == minimal_map_data["archived"]


# ==============================================================================
# HAPPY PATH TESTS - COMPLETE DATA
# ==============================================================================


class TestCreateCoreMapHappyPathComplete:
    """Test creating maps with all optional fields populated."""

    @pytest.mark.asyncio
    async def test_create_with_all_fields(
        self,
        maps_repo: MapsRepository,
        complete_map_data: dict[str, Any],
    ) -> None:
        """Test creating a map with all fields populated."""
        map_id = await maps_repo.create_core_map(complete_map_data)

        assert isinstance(map_id, int)
        assert map_id > 0

    @pytest.mark.asyncio
    async def test_optional_fields_stored_correctly(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        complete_map_data: dict[str, Any],
    ) -> None:
        """Test that optional fields are stored when provided."""
        map_id = await maps_repo.create_core_map(complete_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result["description"] == complete_map_data["description"]
        assert result["custom_banner"] == complete_map_data["custom_banner"]
        assert result["title"] == complete_map_data["title"]


# ==============================================================================
# CONSTRAINT SMOKE TESTS
# ==============================================================================


class TestCreateCoreMapConstraints:
    """Smoke tests for database constraint enforcement."""

    @pytest.mark.asyncio
    async def test_duplicate_code_raises_unique_constraint_error(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that creating a map with duplicate code raises UniqueConstraintViolationError."""
        await maps_repo.create_core_map(minimal_map_data)

        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.create_core_map(minimal_map_data)

        assert "maps_code_key" in exc_info.value.constraint_name

    @pytest.mark.asyncio
    async def test_enum_validation_works(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that enum validation works for category and playtesting fields."""
        # Test valid enum values work
        minimal_map_data["category"] = "Classic"
        minimal_map_data["playtesting"] = "Approved"

        map_id = await maps_repo.create_core_map(minimal_map_data)

        assert isinstance(map_id, int)



# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestCreateCoreMapTransactions:
    """Test transaction handling."""

    @pytest.mark.asyncio
    async def test_create_within_transaction_committed(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map within a committed transaction."""
        async with db_pool.acquire() as conn:
            async with conn.transaction():
                map_id = await maps_repo.create_core_map(minimal_map_data, conn=conn)

        # Verify map exists after commit
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result is not None
        assert result["code"] == minimal_map_data["code"]

    @pytest.mark.asyncio
    async def test_create_within_transaction_rolled_back(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that rolled back transaction doesn't persist map."""
        map_id = None

        async with db_pool.acquire() as conn:
            try:
                async with conn.transaction():
                    map_id = await maps_repo.create_core_map(minimal_map_data, conn=conn)
                    # Force rollback
                    raise Exception("Force rollback")
            except Exception:
                pass

        # Verify map doesn't exist
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", minimal_map_data["code"])

        assert result is None
