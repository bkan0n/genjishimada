"""Tests for MapsRepository.check_code_exists method.

Test Coverage:
- Happy path: code exists
- Happy path: code doesn't exist
- Archived/hidden map filtering
- Transaction context
"""

from typing import Any, get_args
from uuid import uuid4

import asyncpg
from genjishimada_sdk.maps import MapCategory, OverwatchMap, PlaytestStatus
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

from repository.maps_repository import MapsRepository
from genjishimada_sdk import difficulties
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
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2),
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
        result = await maps_repo.check_code_exists(valid_map_code)

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
                True,
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
                True,
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

                    raise Exception("Force rollback")
            except Exception:
                pass

        result = await maps_repo.check_code_exists(code)

        assert result is False
