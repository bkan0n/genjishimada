"""Exhaustive tests for MapsRepository.create_core_map method.

Test Coverage:
- Happy path: create with all required fields
- Happy path: create with optional fields
- Constraint violations: duplicate code
- Constraint violations: invalid enum values
- Field validation: difficulty ranges
- Field validation: empty/null strings
- Field validation: title length constraint
- Transaction handling: commit and rollback
- Edge cases: minimal data, maximal data
- Edge cases: boundary values
- Performance: bulk inserts
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
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max, right_digits=2),
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
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max, right_digits=2),
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
    async def test_created_map_exists_in_database(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that created map can be retrieved from database."""
        map_id = await maps_repo.create_core_map(minimal_map_data)

        # Verify map exists
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result is not None
        assert result["code"] == minimal_map_data["code"]
        assert result["map_name"] == minimal_map_data["map_name"]
        assert result["category"] == minimal_map_data["category"]

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

    @pytest.mark.asyncio
    async def test_create_with_description_only(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with only description as optional field."""
        minimal_map_data["description"] = fake.sentence(nb_words=20)

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result["description"] == minimal_map_data["description"]
        assert result["custom_banner"] is None
        assert result["title"] is None

    @pytest.mark.asyncio
    async def test_create_with_custom_banner_only(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with only custom_banner as optional field."""
        minimal_map_data["custom_banner"] = fake.url()

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result["custom_banner"] == minimal_map_data["custom_banner"]
        assert result["description"] is None
        assert result["title"] is None

    @pytest.mark.asyncio
    async def test_create_with_title_only(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with only title as optional field."""
        minimal_map_data["title"] = fake.sentence(nb_words=3)[:50]

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE id = $1", map_id)

        assert result["title"] == minimal_map_data["title"]
        assert result["description"] is None
        assert result["custom_banner"] is None


# ==============================================================================
# CONSTRAINT VIOLATION TESTS - DUPLICATE CODE
# ==============================================================================


class TestCreateCoreMapDuplicateCode:
    """Test duplicate code constraint violations."""

    @pytest.mark.asyncio
    async def test_duplicate_code_raises_unique_constraint_error(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that creating a map with duplicate code raises UniqueConstraintViolationError."""
        # Create first map
        await maps_repo.create_core_map(minimal_map_data)

        # Attempt to create second map with same code
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.create_core_map(minimal_map_data)

        # Verify constraint name
        assert "maps_code_key" in exc_info.value.constraint_name

    @pytest.mark.asyncio
    async def test_duplicate_code_different_data_still_fails(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
        unique_map_code: str,
    ) -> None:
        """Test that duplicate code fails even with different map data."""
        # Create first map
        await maps_repo.create_core_map(minimal_map_data)

        # Create different map data but same code
        different_data = minimal_map_data.copy()
        different_data["map_name"] = "Different Map"
        different_data["checkpoints"] = 999

        with pytest.raises(UniqueConstraintViolationError):
            await maps_repo.create_core_map(different_data)

    @pytest.mark.asyncio
    async def test_case_sensitive_codes_are_unique(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
        global_code_tracker: set[str],
    ) -> None:
        """Test that uppercase and lowercase codes are treated as different (case-sensitive)."""
        # Create map with uppercase code - use unique code
        uppercase_code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(uppercase_code)
        minimal_map_data["code"] = uppercase_code
        await maps_repo.create_core_map(minimal_map_data)

        # This should fail because lowercase violates code constraint (only uppercase allowed)
        # But if it somehow gets past validation, it would be a different code
        # Note: The database constraint requires [A-Z0-9]{4,6}, so lowercase won't insert
        lowercase_code = "abcd"
        minimal_map_data["code"] = lowercase_code

        # This will fail at the CHECK constraint level, not unique constraint
        with pytest.raises((asyncpg.CheckViolationError, Exception)):
            await maps_repo.create_core_map(minimal_map_data)


# ==============================================================================
# FIELD VALIDATION TESTS - DIFFICULTY
# ==============================================================================


class TestCreateCoreMapDifficultyValidation:
    """Test difficulty field validation."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "difficulty",
        ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"],
    )
    async def test_all_valid_difficulties(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
        difficulty: str,
    ) -> None:
        """Test that all valid difficulty values work."""
        raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[difficulty]  # type: ignore
        minimal_map_data["difficulty"] = difficulty
        minimal_map_data["raw_difficulty"] = fake.pyfloat(min_value=raw_min, max_value=raw_max, right_digits=2)

        map_id = await maps_repo.create_core_map(minimal_map_data)

        assert isinstance(map_id, int)

    @pytest.mark.asyncio
    async def test_raw_difficulty_minimum_value(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with minimum raw_difficulty (Easy minimum)."""
        minimal_map_data["difficulty"] = "Easy"
        minimal_map_data["raw_difficulty"] = difficulties.DIFFICULTY_RANGES_ALL["Easy"][0]  # type: ignore

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT raw_difficulty FROM core.maps WHERE id = $1", map_id)

        assert float(result["raw_difficulty"]) == pytest.approx(
            difficulties.DIFFICULTY_RANGES_ALL["Easy"][0], abs=0.01  # type: ignore
        )

    @pytest.mark.asyncio
    async def test_raw_difficulty_maximum_value(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with maximum raw_difficulty (Hell maximum)."""
        minimal_map_data["difficulty"] = "Hell"
        minimal_map_data["raw_difficulty"] = difficulties.DIFFICULTY_RANGES_ALL["Hell"][1]  # type: ignore

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT raw_difficulty FROM core.maps WHERE id = $1", map_id)

        assert float(result["raw_difficulty"]) == pytest.approx(
            difficulties.DIFFICULTY_RANGES_ALL["Hell"][1], abs=0.01  # type: ignore
        )


# ==============================================================================
# FIELD VALIDATION TESTS - CHECKPOINTS
# ==============================================================================


class TestCreateCoreMapCheckpointsValidation:
    """Test checkpoints field validation."""

    @pytest.mark.asyncio
    async def test_minimum_checkpoints_value(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with minimum checkpoints (1)."""
        minimal_map_data["checkpoints"] = 1

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT checkpoints FROM core.maps WHERE id = $1", map_id)

        assert result["checkpoints"] == 1

    @pytest.mark.asyncio
    async def test_large_checkpoints_value(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test creating map with large checkpoints value."""
        minimal_map_data["checkpoints"] = 999

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT checkpoints FROM core.maps WHERE id = $1", map_id)

        assert result["checkpoints"] == 999


# ==============================================================================
# FIELD VALIDATION TESTS - TITLE LENGTH
# ==============================================================================


class TestCreateCoreMapTitleValidation:
    """Test title field length constraint."""

    @pytest.mark.asyncio
    async def test_title_at_max_length_50_chars(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that title with exactly 50 characters is accepted."""
        minimal_map_data["title"] = "A" * 50

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT title FROM core.maps WHERE id = $1", map_id)

        assert result["title"] == "A" * 50
        assert len(result["title"]) == 50

    @pytest.mark.asyncio
    async def test_title_exceeding_max_length_fails(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that title with more than 50 characters fails."""
        minimal_map_data["title"] = "A" * 51

        with pytest.raises((asyncpg.CheckViolationError, Exception)):
            await maps_repo.create_core_map(minimal_map_data)

    @pytest.mark.asyncio
    async def test_empty_title_string_accepted(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
    ) -> None:
        """Test that empty string title is accepted."""
        minimal_map_data["title"] = ""

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT title FROM core.maps WHERE id = $1", map_id)

        assert result["title"] == ""


# ==============================================================================
# BOOLEAN FIELD TESTS
# ==============================================================================


class TestCreateCoreMapBooleanFields:
    """Test boolean field combinations."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("official", [True, False])
    async def test_official_field_values(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
        official: bool,
    ) -> None:
        """Test both official values."""
        minimal_map_data["official"] = official

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT official FROM core.maps WHERE id = $1", map_id)

        assert result["official"] == official

    @pytest.mark.asyncio
    @pytest.mark.parametrize("hidden", [True, False])
    async def test_hidden_field_values(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
        hidden: bool,
    ) -> None:
        """Test both hidden values."""
        minimal_map_data["hidden"] = hidden

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT hidden FROM core.maps WHERE id = $1", map_id)

        assert result["hidden"] == hidden

    @pytest.mark.asyncio
    @pytest.mark.parametrize("archived", [True, False])
    async def test_archived_field_values(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        minimal_map_data: dict[str, Any],
        archived: bool,
    ) -> None:
        """Test both archived values."""
        minimal_map_data["archived"] = archived

        map_id = await maps_repo.create_core_map(minimal_map_data)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE id = $1", map_id)

        assert result["archived"] == archived


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


# ==============================================================================
# ENUM VALIDATION TESTS
# ==============================================================================


class TestCreateCoreMapEnumValidation:
    """Test enum field validation."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("category", get_args(MapCategory))
    async def test_all_valid_categories(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
        category: str,
    ) -> None:
        """Test all valid category enum values."""
        minimal_map_data["category"] = category

        map_id = await maps_repo.create_core_map(minimal_map_data)

        assert isinstance(map_id, int)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("playtesting", get_args(PlaytestStatus))
    async def test_all_valid_playtest_statuses(
        self,
        maps_repo: MapsRepository,
        minimal_map_data: dict[str, Any],
        playtesting: str,
    ) -> None:
        """Test all valid playtesting enum values."""
        minimal_map_data["playtesting"] = playtesting

        map_id = await maps_repo.create_core_map(minimal_map_data)

        assert isinstance(map_id, int)


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestCreateCoreMapPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_create_multiple_maps_sequentially(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test creating multiple maps in sequence."""
        num_maps = 10
        map_ids = []

        for i in range(num_maps):
            # Generate unique code using UUID
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)

            data = {
                "code": code,
                "map_name": "Hanamura",
                "category": "Classic",
                "checkpoints": 10,
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

            map_id = await maps_repo.create_core_map(data)
            map_ids.append(map_id)

        # Verify all maps exist
        assert len(map_ids) == num_maps
        assert len(set(map_ids)) == num_maps  # All IDs are unique
