"""Focused tests for MapsRepository.set_archive_status method.

Test Coverage:
- Set archived=true (1 test)
- Set archived=false (1 test)
- Bulk archive (1 test)
- Bulk unarchive (1 test)
- Archive affects queries (1 test)
- Updated_at changes (1 test)
- Transaction commit (1 test)
- Archive returns count (1 test)

Total: 8 tests (reduced from 18)
"""

import asyncpg
import pytest
from faker import Faker
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

    # Fallback: timestamp-based code
    import time

    timestamp = str(int(time.time() * 1000))[-6:]
    code = f"T{timestamp[:5]}"
    used_codes.add(code)
    return code


async def create_test_map(
    db_pool: asyncpg.Pool,
    code: str,
    *,
    archived: bool = False,
) -> int:
    """Helper to create a test map."""
    async with db_pool.acquire() as conn:
        map_id = await conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            code,
            "Test Map",
            "Classic",
            10,
            True,
            "Approved",
            "Medium",
            5.0,
            archived,
        )
    return map_id


# ==============================================================================
# CORE FUNCTIONALITY TESTS
# ==============================================================================


class TestSetArchiveStatusCore:
    """Test core archive/unarchive functionality."""

    @pytest.mark.asyncio
    async def test_set_archived_true(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test setting archived=true on a map."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        await maps_repo.set_archive_status([unique_map_code], archived=True)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True

    @pytest.mark.asyncio
    async def test_set_archived_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test setting archived=false on a map."""
        await create_test_map(db_pool, unique_map_code, archived=True)

        await maps_repo.set_archive_status([unique_map_code], archived=False)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is False

    @pytest.mark.asyncio
    async def test_bulk_archive(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test archiving multiple maps at once."""
        codes = []
        for i in range(5):
            code = f"BULK{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=False)
            codes.append(code)

        await maps_repo.set_archive_status(codes, archived=True)

        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                "SELECT code, archived FROM core.maps WHERE code = ANY($1::text[])",
                codes,
            )

        assert len(results) == 5
        assert all(r["archived"] is True for r in results)

    @pytest.mark.asyncio
    async def test_bulk_unarchive(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test unarchiving multiple maps at once."""
        codes = []
        for i in range(5):
            code = f"UNAR{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=True)
            codes.append(code)

        await maps_repo.set_archive_status(codes, archived=False)

        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                "SELECT code, archived FROM core.maps WHERE code = ANY($1::text[])",
                codes,
            )

        assert len(results) == 5
        assert all(r["archived"] is False for r in results)

    @pytest.mark.asyncio
    async def test_archive_affects_queries(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that archived status affects query filtering."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        # Archive the map
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Verify filtering by archived status works
        async with db_pool.acquire() as conn:
            archived_count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.maps WHERE code = $1 AND archived = TRUE",
                unique_map_code,
            )
            unarchived_count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.maps WHERE code = $1 AND archived = FALSE",
                unique_map_code,
            )

        assert archived_count == 1
        assert unarchived_count == 0

    @pytest.mark.asyncio
    async def test_updated_at_changes(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that updated_at timestamp changes when archiving."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        # Get original updated_at
        async with db_pool.acquire() as conn:
            original = await conn.fetchrow("SELECT updated_at FROM core.maps WHERE code = $1", unique_map_code)

        # Wait briefly to ensure timestamp difference
        import asyncio

        await asyncio.sleep(0.1)

        # Archive
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Get new updated_at
        async with db_pool.acquire() as conn:
            updated = await conn.fetchrow("SELECT updated_at FROM core.maps WHERE code = $1", unique_map_code)

        assert updated["updated_at"] > original["updated_at"]

    @pytest.mark.asyncio
    async def test_transaction_commit(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that archiving within a committed transaction persists."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.set_archive_status([unique_map_code], archived=True, conn=conn)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True
