"""Exhaustive tests for MapsRepository.lookup_map_id method.

Test Coverage:
- Happy path: code exists, returns valid ID
- Happy path: code doesn't exist, returns None
- Edge case: empty database
- Edge case: case sensitivity
- Edge case: various code lengths (4, 5, 6 chars)
- Edge case: special characters
- Edge case: empty/null string
- Edge case: archived/hidden maps still return ID
- Edge case: verify ID correctness
- Edge case: ID stability (same code = same ID)
- Edge case: using transaction context
- Performance: lookup multiple IDs sequentially
- Concurrency: parallel lookups
"""

import asyncio
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
def valid_map_code() -> str:
    """Generate a valid Overwatch map code (4-6 uppercase alphanumeric chars)."""
    length = fake.random_int(min=4, max=6)
    return "".join(fake.unique.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=length))


@pytest.fixture
async def minimal_map_data(valid_map_code: str) -> dict[str, Any]:
    """Create minimal valid map data for database insertion."""
    diff = fake.random_element(elements=["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"])
    raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[diff]  # type: ignore
    return {
        "code": valid_map_code,
        "map_name": fake.random_element(elements=get_args(OverwatchMap)),
        "category": fake.random_element(elements=get_args(MapCategory)),
        "checkpoints": fake.random_int(min=1, max=50),
        "official": fake.boolean(),
        "playtesting": fake.random_element(elements=get_args(PlaytestStatus)),
        "hidden": False,
        "archived": False,
        "difficulty": diff,
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max, right_digits=2),
        "description": fake.sentence(nb_words=10),
        "custom_banner": None,
        "title": fake.sentence(nb_words=3),
    }


@pytest.fixture
async def insert_test_map(db_pool: asyncpg.Pool, minimal_map_data: dict[str, Any]) -> dict[str, Any]:
    """Insert a test map and return its data with ID."""
    async with db_pool.acquire() as conn:
        map_id = await conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, hidden, archived, difficulty, raw_difficulty,
                description, custom_banner, title
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id
            """,
            minimal_map_data["code"],
            minimal_map_data["map_name"],
            minimal_map_data["category"],
            minimal_map_data["checkpoints"],
            minimal_map_data["official"],
            minimal_map_data["playtesting"],
            minimal_map_data["hidden"],
            minimal_map_data["archived"],
            minimal_map_data["difficulty"],
            minimal_map_data["raw_difficulty"],
            minimal_map_data["description"],
            minimal_map_data["custom_banner"],
            minimal_map_data["title"],
        )
    minimal_map_data["id"] = map_id
    return minimal_map_data


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestLookupMapIdHappyPath:
    """Test happy path scenarios for lookup_map_id."""

    @pytest.mark.asyncio
    async def test_returns_id_when_code_exists(
        self,
        maps_repo: MapsRepository,
        insert_test_map: dict[str, Any],
    ) -> None:
        """Test that lookup_map_id returns the map ID when code exists."""
        code = insert_test_map["code"]
        expected_id = insert_test_map["id"]

        result = await maps_repo.lookup_map_id(code)

        assert result == expected_id
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_returns_none_when_code_does_not_exist(
        self,
        maps_repo: MapsRepository,
        valid_map_code: str,
    ) -> None:
        """Test that lookup_map_id returns None when code doesn't exist."""
        result = await maps_repo.lookup_map_id(valid_map_code)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_database(
        self,
        maps_repo: MapsRepository,
        valid_map_code: str,
    ) -> None:
        """Test that lookup_map_id returns None when database has no maps."""
        result = await maps_repo.lookup_map_id(valid_map_code)

        assert result is None


# ==============================================================================
# ID CORRECTNESS TESTS
# ==============================================================================


class TestLookupMapIdCorrectness:
    """Test that returned IDs are correct and stable."""

    @pytest.mark.asyncio
    async def test_returned_id_matches_inserted_id(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that the returned ID matches the ID from INSERT RETURNING."""
        code = "TEST01"

        # Insert and capture ID
        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Test Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        # Lookup ID
        looked_up_id = await maps_repo.lookup_map_id(code)

        assert looked_up_id == inserted_id

    @pytest.mark.asyncio
    async def test_id_is_stable_across_multiple_lookups(
        self,
        maps_repo: MapsRepository,
        insert_test_map: dict[str, Any],
    ) -> None:
        """Test that looking up the same code multiple times returns the same ID."""
        code = insert_test_map["code"]

        # Lookup multiple times
        id1 = await maps_repo.lookup_map_id(code)
        id2 = await maps_repo.lookup_map_id(code)
        id3 = await maps_repo.lookup_map_id(code)

        # All should be the same
        assert id1 == id2 == id3

    @pytest.mark.asyncio
    async def test_different_codes_return_different_ids(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that different map codes return different IDs."""
        code1 = "MAP001"
        code2 = "MAP002"

        # Insert two maps
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                code1,
                "Map 1",
                "Hanamura",
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
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                code2,
                "Map 2",
                "Hanamura",
                15,
                True,
                "Approved",
                "Hard",
                7.0,
            )

        # Lookup both
        id1 = await maps_repo.lookup_map_id(code1)
        id2 = await maps_repo.lookup_map_id(code2)

        assert id1 != id2
        assert isinstance(id1, int)
        assert isinstance(id2, int)


# ==============================================================================
# CASE SENSITIVITY TESTS
# ==============================================================================


class TestLookupMapIdCaseSensitivity:
    """Test case sensitivity behavior of lookup_map_id."""

    @pytest.mark.asyncio
    async def test_uppercase_code_returns_id(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that uppercase code returns the correct ID."""
        code = "UPPER1"

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Test Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        result = await maps_repo.lookup_map_id("UPPER1")

        assert result == inserted_id

    @pytest.mark.asyncio
    async def test_lowercase_query_returns_none_when_uppercase_stored(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that lowercase query doesn't match uppercase stored code."""
        code = "UPPER2"

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                code,
                "Test Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        # Query with lowercase
        result = await maps_repo.lookup_map_id("upper2")

        # Should NOT find it (case-sensitive)
        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_case_query_returns_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that mixed case query doesn't match uppercase stored code."""
        code = "UPPER3"

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                code,
                "Test Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        # Query with mixed case
        result = await maps_repo.lookup_map_id("UpPeR3")

        assert result is None


# ==============================================================================
# CODE LENGTH TESTS
# ==============================================================================


class TestLookupMapIdCodeLength:
    """Test lookup_map_id with various code lengths."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code_length", [4, 5, 6])
    async def test_valid_code_lengths(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        code_length: int,
    ) -> None:
        """Test that codes of valid lengths (4-6) can be looked up."""
        # Generate code of specific length
        code = "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=code_length))

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Test Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id


# ==============================================================================
# SPECIAL CHARACTERS TESTS
# ==============================================================================


class TestLookupMapIdSpecialCharacters:
    """Test behavior with special characters and invalid codes."""

    @pytest.mark.asyncio
    async def test_code_with_spaces_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with spaces return None (invalid format)."""
        result = await maps_repo.lookup_map_id("AB CD")

        assert result is None

    @pytest.mark.asyncio
    async def test_code_with_special_characters_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with special characters return None."""
        result = await maps_repo.lookup_map_id("ABC!@")

        assert result is None

    @pytest.mark.asyncio
    async def test_code_with_hyphen_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with hyphens return None."""
        result = await maps_repo.lookup_map_id("AB-CD")

        assert result is None


# ==============================================================================
# EMPTY/NULL STRING TESTS
# ==============================================================================


class TestLookupMapIdEmptyNull:
    """Test behavior with empty and null-like inputs."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that empty string returns None."""
        result = await maps_repo.lookup_map_id("")

        assert result is None

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that whitespace-only string returns None."""
        result = await maps_repo.lookup_map_id("   ")

        assert result is None


# ==============================================================================
# ARCHIVED/HIDDEN MAP TESTS
# ==============================================================================


class TestLookupMapIdArchivedHidden:
    """Test that lookup_map_id finds archived and hidden maps."""

    @pytest.mark.asyncio
    async def test_returns_id_for_archived_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that archived maps still return their ID."""
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                code,
                "Archived Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
                True,  # archived=True
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id

    @pytest.mark.asyncio
    async def test_returns_id_for_hidden_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that hidden maps still return their ID."""
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, hidden
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
                """,
                code,
                "Hidden Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
                True,  # hidden=True
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id

    @pytest.mark.asyncio
    async def test_returns_id_for_archived_and_hidden_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that archived AND hidden maps still return their ID."""
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived, hidden
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                code,
                "Archived and Hidden Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
                True,  # archived=True
                True,  # hidden=True
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id


# ==============================================================================
# TRANSACTION CONTEXT TESTS
# ==============================================================================


class TestLookupMapIdTransaction:
    """Test lookup_map_id within transaction context."""

    @pytest.mark.asyncio
    async def test_lookup_within_transaction_before_commit(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that ID can be looked up within transaction before commit."""
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                # Insert within transaction
                inserted_id = await conn.fetchval(
                    """
                    INSERT INTO core.maps (
                        code, map_name, category, checkpoints, official,
                        playtesting, difficulty, raw_difficulty
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """,
                    code,
                    "Transaction Map",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5.0,
                )

                # Lookup within same transaction
                result = await maps_repo.lookup_map_id(code, conn=conn)

                assert result == inserted_id

    @pytest.mark.asyncio
    async def test_lookup_after_rollback_returns_none(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that ID cannot be looked up after transaction rollback."""
        code = "ROLLBK"

        async with db_pool.acquire() as conn:
            try:
                async with conn.transaction():
                    # Insert within transaction
                    await conn.execute(
                        """
                        INSERT INTO core.maps (
                            code, map_name, category, checkpoints, official,
                            playtesting, difficulty, raw_difficulty
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        code,
                        "Rollback Map",
                        "Hanamura",
                        10,
                        True,
                        "Approved",
                        "Medium",
                        5.0,
                    )

                    # Force rollback
                    raise Exception("Force rollback")
            except Exception:
                pass

        # Lookup after rollback
        result = await maps_repo.lookup_map_id(code)

        assert result is None


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestLookupMapIdPerformance:
    """Test performance characteristics of lookup_map_id."""

    @pytest.mark.asyncio
    async def test_lookup_multiple_ids_sequentially(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test looking up multiple IDs sequentially."""
        codes = [f"T{uuid4().hex[:5].upper()}" for _ in range(5)]
        for code in codes:
            global_code_tracker.add(code)
        expected_ids = {}

        # Insert maps and store their IDs
        async with db_pool.acquire() as conn:
            for code in codes[:3]:
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
                    f"Map {code}",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5.0,
                )
                expected_ids[code] = map_id

        # Lookup all codes
        results = {}
        for code in codes:
            results[code] = await maps_repo.lookup_map_id(code)

        # Verify results (first 3 exist, last 2 don't)
        assert results[codes[0]] == expected_ids[codes[0]]
        assert results[codes[1]] == expected_ids[codes[1]]
        assert results[codes[2]] == expected_ids[codes[2]]
        assert results[codes[3]] is None
        assert results[codes[4]] is None

    @pytest.mark.asyncio
    async def test_lookup_multiple_ids_concurrently(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test looking up multiple IDs concurrently."""
        codes = [f"T{uuid4().hex[:5].upper()}" for _ in range(5)]
        for code in codes:
            global_code_tracker.add(code)
        expected_ids = {}

        # Insert maps
        async with db_pool.acquire() as conn:
            for code in codes[:3]:
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
                    f"Map {code}",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5.0,
                )
                expected_ids[code] = map_id

        # Lookup all codes concurrently
        tasks = [maps_repo.lookup_map_id(code) for code in codes]
        results = await asyncio.gather(*tasks)

        # Verify results (first 3 exist, last 2 don't)
        assert results[0] == expected_ids[codes[0]]
        assert results[1] == expected_ids[codes[1]]
        assert results[2] == expected_ids[codes[2]]
        assert results[3] is None
        assert results[4] is None


# ==============================================================================
# NUMERIC CODE TESTS
# ==============================================================================


class TestLookupMapIdNumeric:
    """Test behavior with numeric and alphanumeric codes."""

    @pytest.mark.asyncio
    async def test_all_numeric_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that all-numeric codes work."""
        # Generate numeric-only code (5 digits)
        code = "".join(str(fake.random_int(min=0, max=9)) for _ in range(5))
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Numeric Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id

    @pytest.mark.asyncio
    async def test_all_alpha_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that all-alphabetic codes work."""
        # Generate alpha-only code (5 letters)
        code = "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ", length=5))
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Alpha Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id

    @pytest.mark.asyncio
    async def test_mixed_alphanumeric_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that mixed alphanumeric codes work."""
        # Use UUID-based code (already mixed alphanumeric)
        code = f"T{uuid4().hex[:4].upper()}"
        global_code_tracker.add(code)

        async with db_pool.acquire() as conn:
            inserted_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                code,
                "Mixed Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        result = await maps_repo.lookup_map_id(code)

        assert result == inserted_id
