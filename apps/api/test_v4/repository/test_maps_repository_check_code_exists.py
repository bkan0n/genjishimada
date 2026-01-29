"""Exhaustive tests for MapsRepository.check_code_exists method.

Test Coverage:
- Happy path: code exists
- Happy path: code doesn't exist
- Edge case: empty database
- Edge case: case sensitivity
- Edge case: various code lengths (4, 5, 6 chars)
- Edge case: special characters
- Edge case: whitespace in codes
- Edge case: null/empty string
- Edge case: using transaction context
- Edge case: archived/hidden maps
- Performance: checking multiple codes
- Concurrency: parallel existence checks
"""

import asyncio
from typing import Any, get_args

import asyncpg
from genjishimada_sdk.maps import MapCategory, OverwatchMap, PlaytestStatus
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

from repository.maps_repository import MapsRepository
from genjishimada_sdk import difficulties
fake = Faker()


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
    return "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=length))


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
    """Insert a test map and return its data."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, hidden, archived, difficulty, raw_difficulty,
                description, custom_banner, title
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
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
    return minimal_map_data


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestCheckCodeExistsHappyPath:
    """Test happy path scenarios for check_code_exists."""

    @pytest.mark.asyncio
    async def test_returns_true_when_code_exists(
        self,
        maps_repo: MapsRepository,
        insert_test_map: dict[str, Any],
    ) -> None:
        """Test that check_code_exists returns True when code exists."""
        code = insert_test_map["code"]

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_code_does_not_exist(
        self,
        maps_repo: MapsRepository,
        valid_map_code: str,
    ) -> None:
        """Test that check_code_exists returns False when code doesn't exist."""
        # Use a valid code that was NOT inserted
        result = await maps_repo.check_code_exists(valid_map_code)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_empty_database(
        self,
        maps_repo: MapsRepository,
        valid_map_code: str,
    ) -> None:
        """Test that check_code_exists returns False when database has no maps."""
        # Database is empty (no fixtures inserted)
        result = await maps_repo.check_code_exists(valid_map_code)

        assert result is False


# ==============================================================================
# CODE LENGTH TESTS
# ==============================================================================


class TestCheckCodeExistsCodeLength:
    """Test check_code_exists with various code lengths."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("code_length", [4, 5, 6])
    async def test_valid_code_lengths(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        code_length: int,
    ) -> None:
        """Test that codes of valid lengths (4-6) can be checked."""
        # Generate code of specific length
        code = "".join(fake.random_choices(elements="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", length=code_length))

        # Insert map with this code
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
                5,
            )

        # Check existence
        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_minimum_length_code_4_chars(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that minimum valid code length (4 chars) works."""
        code = "ABCD"

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
                5,
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_maximum_length_code_6_chars(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that maximum valid code length (6 chars) works."""
        code = "ABCD12"

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
                5,
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True


# ==============================================================================
# CASE SENSITIVITY TESTS
# ==============================================================================


class TestCheckCodeExistsCaseSensitivity:
    """Test case sensitivity behavior of check_code_exists."""

    @pytest.mark.asyncio
    async def test_uppercase_code_exists(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that uppercase code can be found."""
        code = "UPPR1"

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
                5,
            )

        result = await maps_repo.check_code_exists("UPPR1")

        assert result is True

    @pytest.mark.asyncio
    async def test_lowercase_code_not_found_when_uppercase_exists(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that lowercase query doesn't match uppercase stored code."""
        code = "UPPR2"

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
                5,
            )

        # Query with lowercase
        result = await maps_repo.check_code_exists("uppr2")

        # Should NOT find it (case-sensitive)
        assert result is False

    @pytest.mark.asyncio
    async def test_mixed_case_code_not_found(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that mixed case query doesn't match uppercase stored code."""
        code = "UPPR3"

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
                5,
            )

        # Query with mixed case
        result = await maps_repo.check_code_exists("UpPr3")

        assert result is False


# ==============================================================================
# SPECIAL CHARACTERS TESTS
# ==============================================================================


class TestCheckCodeExistsSpecialCharacters:
    """Test behavior with special characters and invalid codes."""

    @pytest.mark.asyncio
    async def test_code_with_spaces_not_found(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with spaces are not found (invalid format)."""
        result = await maps_repo.check_code_exists("AB CD")

        assert result is False

    @pytest.mark.asyncio
    async def test_code_with_special_characters_not_found(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with special characters are not found."""
        result = await maps_repo.check_code_exists("ABC!@")

        assert result is False

    @pytest.mark.asyncio
    async def test_code_with_hyphen_not_found(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with hyphens are not found."""
        result = await maps_repo.check_code_exists("AB-CD")

        assert result is False

    @pytest.mark.asyncio
    async def test_code_with_underscore_not_found(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that codes with underscores are not found."""
        result = await maps_repo.check_code_exists("AB_CD")

        assert result is False


# ==============================================================================
# EMPTY/NULL STRING TESTS
# ==============================================================================


class TestCheckCodeExistsEmptyNull:
    """Test behavior with empty and null-like inputs."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_false(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that empty string returns False."""
        result = await maps_repo.check_code_exists("")

        assert result is False

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_false(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that whitespace-only string returns False."""
        result = await maps_repo.check_code_exists("   ")

        assert result is False

    @pytest.mark.asyncio
    async def test_tab_characters_returns_false(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that string with tabs returns False."""
        result = await maps_repo.check_code_exists("\t\t")

        assert result is False

    @pytest.mark.asyncio
    async def test_newline_characters_returns_false(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that string with newlines returns False."""
        result = await maps_repo.check_code_exists("\n\n")

        assert result is False


# ==============================================================================
# ARCHIVED/HIDDEN MAP TESTS
# ==============================================================================


class TestCheckCodeExistsArchivedHidden:
    """Test that check_code_exists finds archived and hidden maps."""

    @pytest.mark.asyncio
    async def test_finds_archived_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that archived maps are still found by check_code_exists."""
        code = "ARCH01"

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                code,
                "Archived Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
                True,  # archived=True
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_finds_hidden_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that hidden maps are still found by check_code_exists."""
        code = "HIDE01"

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, hidden
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                code,
                "Hidden Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
                True,  # hidden=True
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_finds_archived_and_hidden_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that archived AND hidden maps are still found."""
        code = "BOTH01"

        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived, hidden
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                code,
                "Archived and Hidden Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
                True,  # archived=True
                True,  # hidden=True
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True


# ==============================================================================
# TRANSACTION CONTEXT TESTS
# ==============================================================================


class TestCheckCodeExistsTransaction:
    """Test check_code_exists within transaction context."""

    @pytest.mark.asyncio
    async def test_check_within_transaction_before_commit(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that code exists within transaction before commit."""
        code = "TRANS1"

        async with db_pool.acquire() as conn:
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
                    "Transaction Map",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5,
                )

                # Check existence within same transaction
                result = await maps_repo.check_code_exists(code, conn=conn)

                assert result is True

    @pytest.mark.asyncio
    async def test_check_after_rollback_returns_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that code doesn't exist after transaction rollback."""
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
                        5,
                    )

                    # Force rollback
                    raise Exception("Force rollback")
            except Exception:
                pass

        # Check existence after rollback
        result = await maps_repo.check_code_exists(code)

        assert result is False


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestCheckCodeExistsPerformance:
    """Test performance characteristics of check_code_exists."""

    @pytest.mark.asyncio
    async def test_check_multiple_codes_sequentially(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test checking multiple codes sequentially."""
        codes = ["SEQ001", "SEQ002", "SEQ003", "SEQ004", "SEQ005"]

        # Insert first 3 codes
        async with db_pool.acquire() as conn:
            for code in codes[:3]:
                await conn.execute(
                    """
                    INSERT INTO core.maps (
                        code, map_name, category, checkpoints, official,
                        playtesting, difficulty, raw_difficulty
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    code,
                    f"Map {code}",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5,
                )

        # Check all codes
        results = {}
        for code in codes:
            results[code] = await maps_repo.check_code_exists(code)

        # Verify results
        assert results["SEQ001"] is True
        assert results["SEQ002"] is True
        assert results["SEQ003"] is True
        assert results["SEQ004"] is False
        assert results["SEQ005"] is False

    @pytest.mark.asyncio
    async def test_check_multiple_codes_concurrently(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test checking multiple codes concurrently."""
        codes = ["PAR001", "PAR002", "PAR003", "PAR004", "PAR005"]

        # Insert first 3 codes
        async with db_pool.acquire() as conn:
            for code in codes[:3]:
                await conn.execute(
                    """
                    INSERT INTO core.maps (
                        code, map_name, category, checkpoints, official,
                        playtesting, difficulty, raw_difficulty
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    code,
                    f"Map {code}",
                    "Hanamura",
                    10,
                    True,
                    "Approved",
                    "Medium",
                    5,
                )

        # Check all codes concurrently
        tasks = [maps_repo.check_code_exists(code) for code in codes]
        results = await asyncio.gather(*tasks)

        # Verify results
        assert results[0] is True  # PAR001
        assert results[1] is True  # PAR002
        assert results[2] is True  # PAR003
        assert results[3] is False  # PAR004
        assert results[4] is False  # PAR005


# ==============================================================================
# NUMERIC CODE TESTS
# ==============================================================================


class TestCheckCodeExistsNumeric:
    """Test behavior with numeric and alphanumeric codes."""

    @pytest.mark.asyncio
    async def test_all_numeric_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that all-numeric codes work."""
        code = "12345"

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
                "Numeric Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_all_alpha_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that all-alphabetic codes work."""
        code = "ABCDE"

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
                "Alpha Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True

    @pytest.mark.asyncio
    async def test_mixed_alphanumeric_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
    ) -> None:
        """Test that mixed alphanumeric codes work."""
        code = "A1B2C"

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
                "Mixed Map",
                "Hanamura",
                10,
                True,
                "Approved",
                "Medium",
                5,
            )

        result = await maps_repo.check_code_exists(code)

        assert result is True
