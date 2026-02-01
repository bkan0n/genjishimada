"""Tests for MapsRepository.lookup_map_id method.

Test Coverage:
- Lookup existing code returns ID
- Lookup non-existent code returns None
- Lookup archived map
- Lookup hidden map
- Transaction commit test
- Transaction rollback test
"""

from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

from repository.maps_repository import MapsRepository

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


# ==============================================================================
# TESTS
# ==============================================================================


class TestLookupMapId:
    """Test lookup_map_id method."""

    @pytest.mark.asyncio
    async def test_lookup_existing_code_returns_id(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        global_code_tracker: set[str],
    ) -> None:
        """Test that lookup_map_id returns the map ID when code exists."""
        code = f"T{uuid4().hex[:5].upper()}"
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
        assert isinstance(result, int)

    @pytest.mark.asyncio
    async def test_lookup_nonexistent_code_returns_none(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that lookup_map_id returns None when code doesn't exist."""
        result = await maps_repo.lookup_map_id("NOTEXIST")

        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_archived_map(
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
    async def test_lookup_hidden_map(
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
    async def test_transaction_commit(
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
    async def test_transaction_rollback(
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
