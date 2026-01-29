"""Exhaustive tests for MapsRepository.set_archive_status method.

Test Coverage:
- Happy path: archive single map
- Happy path: unarchive single map
- Bulk operations: archive multiple maps
- Bulk operations: unarchive multiple maps
- Empty list (no-op)
- Non-existent codes (silent failure)
- Mixed: some exist, some don't
- Idempotency: archive already archived
- Idempotency: unarchive already unarchived
- Toggle: archive then unarchive
- Transaction handling: commit and rollback
- Performance: bulk archive many maps
- Edge cases: verify other fields unchanged
"""

from typing import Any, get_args

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk import difficulties
from genjishimada_sdk.maps import MapCategory, OverwatchMap, PlaytestStatus
from pytest_databases.docker.postgres import PostgresService

from repository.maps_repository import MapsRepository

fake = Faker()


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
# HAPPY PATH TESTS - SINGLE MAP
# ==============================================================================


class TestSetArchiveStatusSingleMap:
    """Test archiving/unarchiving single maps."""

    @pytest.mark.asyncio
    async def test_archive_single_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test archiving a single map."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Verify map is archived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True

    @pytest.mark.asyncio
    async def test_unarchive_single_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test unarchiving a single map."""
        await create_test_map(db_pool, unique_map_code, archived=True)

        await maps_repo.set_archive_status([unique_map_code], archived=False)

        # Verify map is unarchived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is False


# ==============================================================================
# BULK OPERATION TESTS
# ==============================================================================


class TestSetArchiveStatusBulk:
    """Test bulk archive/unarchive operations."""

    @pytest.mark.asyncio
    async def test_archive_multiple_maps(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test archiving multiple maps at once."""
        # Create 5 unarchived maps
        codes = []
        for i in range(5):
            code = f"BULK{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=False)
            codes.append(code)

        # Archive all at once
        await maps_repo.set_archive_status(codes, archived=True)

        # Verify all are archived
        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                "SELECT code, archived FROM core.maps WHERE code = ANY($1::text[])",
                codes,
            )

        assert len(results) == 5
        assert all(r["archived"] is True for r in results)

    @pytest.mark.asyncio
    async def test_unarchive_multiple_maps(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test unarchiving multiple maps at once."""
        # Create 5 archived maps
        codes = []
        for i in range(5):
            code = f"UNAR{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=True)
            codes.append(code)

        # Unarchive all at once
        await maps_repo.set_archive_status(codes, archived=False)

        # Verify all are unarchived
        async with db_pool.acquire() as conn:
            results = await conn.fetch(
                "SELECT code, archived FROM core.maps WHERE code = ANY($1::text[])",
                codes,
            )

        assert len(results) == 5
        assert all(r["archived"] is False for r in results)

    @pytest.mark.asyncio
    async def test_bulk_archive_large_batch(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test archiving a large batch of maps."""
        # Create 20 maps
        codes = []
        for i in range(20):
            code = f"LRG{i:03d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=False)
            codes.append(code)

        # Archive all at once
        await maps_repo.set_archive_status(codes, archived=True)

        # Verify count
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.maps WHERE code = ANY($1::text[]) AND archived = TRUE",
                codes,
            )

        assert count == 20


# ==============================================================================
# EMPTY LIST TESTS
# ==============================================================================


class TestSetArchiveStatusEmpty:
    """Test with empty code list."""

    @pytest.mark.asyncio
    async def test_empty_list_does_nothing(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that empty list doesn't cause errors."""
        # Should not raise an error
        await maps_repo.set_archive_status([], archived=True)
        await maps_repo.set_archive_status([], archived=False)


# ==============================================================================
# NON-EXISTENT CODE TESTS
# ==============================================================================


class TestSetArchiveStatusNonExistent:
    """Test with non-existent map codes."""

    @pytest.mark.asyncio
    async def test_non_existent_code_silent_failure(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test that non-existent code doesn't raise error (updates 0 rows)."""
        # Should not raise an error, just updates 0 rows
        await maps_repo.set_archive_status([unique_map_code], archived=True)

    @pytest.mark.asyncio
    async def test_mixed_existent_and_non_existent(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test mix of existent and non-existent codes."""
        # Create 2 real maps
        real_code1 = "REAL01"
        real_code2 = "REAL02"
        used_codes.add(real_code1)
        used_codes.add(real_code2)

        await create_test_map(db_pool, real_code1, archived=False)
        await create_test_map(db_pool, real_code2, archived=False)

        # Mix with fake codes
        fake_code1 = "FAKE01"
        fake_code2 = "FAKE02"
        used_codes.add(fake_code1)
        used_codes.add(fake_code2)

        codes = [real_code1, fake_code1, real_code2, fake_code2]

        # Archive all (including fake ones)
        await maps_repo.set_archive_status(codes, archived=True)

        # Verify only real maps are archived
        async with db_pool.acquire() as conn:
            real_results = await conn.fetch(
                "SELECT code, archived FROM core.maps WHERE code = ANY($1::text[])",
                [real_code1, real_code2],
            )

        assert len(real_results) == 2
        assert all(r["archived"] is True for r in real_results)


# ==============================================================================
# IDEMPOTENCY TESTS
# ==============================================================================


class TestSetArchiveStatusIdempotency:
    """Test idempotent behavior."""

    @pytest.mark.asyncio
    async def test_archive_already_archived_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test archiving an already archived map (idempotent)."""
        await create_test_map(db_pool, unique_map_code, archived=True)

        # Archive again
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Verify still archived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True

    @pytest.mark.asyncio
    async def test_unarchive_already_unarchived_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test unarchiving an already unarchived map (idempotent)."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        # Unarchive again
        await maps_repo.set_archive_status([unique_map_code], archived=False)

        # Verify still unarchived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is False

    @pytest.mark.asyncio
    async def test_multiple_archive_operations_same_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test archiving same map multiple times."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        # Archive 3 times
        for _ in range(3):
            await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Verify archived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True


# ==============================================================================
# TOGGLE TESTS
# ==============================================================================


class TestSetArchiveStatusToggle:
    """Test toggling archive status."""

    @pytest.mark.asyncio
    async def test_archive_then_unarchive(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test archiving then unarchiving a map."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        # Archive
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)
        assert result["archived"] is True

        # Unarchive
        await maps_repo.set_archive_status([unique_map_code], archived=False)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)
        assert result["archived"] is False

    @pytest.mark.asyncio
    async def test_unarchive_then_archive(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test unarchiving then archiving a map."""
        await create_test_map(db_pool, unique_map_code, archived=True)

        # Unarchive
        await maps_repo.set_archive_status([unique_map_code], archived=False)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)
        assert result["archived"] is False

        # Archive
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)
        assert result["archived"] is True


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestSetArchiveStatusTransactions:
    """Test transaction handling."""

    @pytest.mark.asyncio
    async def test_archive_within_transaction_committed(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test archiving within a committed transaction."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.set_archive_status([unique_map_code], archived=True, conn=conn)

        # Verify archived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is True

    @pytest.mark.asyncio
    async def test_archive_within_transaction_rolled_back(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that rolled back transaction doesn't persist archive."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        async with db_pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await maps_repo.set_archive_status([unique_map_code], archived=True, conn=conn)
                    # Force rollback
                    raise Exception("Force rollback")
            except Exception:
                pass

        # Verify not archived
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", unique_map_code)

        assert result["archived"] is False


# ==============================================================================
# FIELD PRESERVATION TESTS
# ==============================================================================


class TestSetArchiveStatusFieldPreservation:
    """Test that other fields are unchanged."""

    @pytest.mark.asyncio
    async def test_archiving_preserves_other_fields(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test that archiving doesn't modify other fields."""
        # Create map with specific values
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, archived, hidden, description
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                unique_map_code,
                "Original Name",
                "Strive",
                25,
                True,
                "Approved",
                "Hard",
                7.0,
                False,
                True,
                "Original description",
            )

        # Get original values
        async with db_pool.acquire() as conn:
            original = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", unique_map_code)

        # Archive
        await maps_repo.set_archive_status([unique_map_code], archived=True)

        # Get updated values
        async with db_pool.acquire() as conn:
            updated = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", unique_map_code)

        # Verify only archived changed
        assert updated["archived"] is True  # Changed
        assert updated["map_name"] == original["map_name"]
        assert updated["category"] == original["category"]
        assert updated["checkpoints"] == original["checkpoints"]
        assert updated["official"] == original["official"]
        assert updated["playtesting"] == original["playtesting"]
        assert updated["difficulty"] == original["difficulty"]
        assert updated["raw_difficulty"] == original["raw_difficulty"]
        assert updated["hidden"] == original["hidden"]
        assert updated["description"] == original["description"]


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestSetArchiveStatusPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_bulk_archive_performance(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test that bulk archiving is efficient."""
        # Create 50 maps
        codes = []
        for i in range(50):
            code = f"PRF{i:03d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=False)
            codes.append(code)

        # Archive all at once (should be single query)
        await maps_repo.set_archive_status(codes, archived=True)

        # Verify all archived
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.maps WHERE code = ANY($1::text[]) AND archived = TRUE",
                codes,
            )

        assert count == 50

    @pytest.mark.asyncio
    async def test_sequential_single_archives(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test archiving maps one at a time sequentially."""
        # Create 10 maps
        codes = []
        for i in range(10):
            code = f"SEQ{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, archived=False)
            codes.append(code)

        # Archive one at a time
        for code in codes:
            await maps_repo.set_archive_status([code], archived=True)

        # Verify all archived
        async with db_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.maps WHERE code = ANY($1::text[]) AND archived = TRUE",
                codes,
            )

        assert count == 10
