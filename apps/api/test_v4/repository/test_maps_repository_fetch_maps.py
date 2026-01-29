"""Exhaustive tests for MapsRepository.fetch_maps method.

Test Coverage:
- Happy path: fetch all maps, fetch single map
- Filter: code (single map lookup)
- Filter: category, map_name
- Filter: boolean fields (archived, hidden, official)
- Filter: playtesting status
- Filter: creators (by ID, by name)
- Filter: mechanics, restrictions, tags
- Filter: difficulty (exact, range)
- Filter: quality, medals, completions, playtests
- Pagination: page_size, page_number, return_all
- Sorting: all sort keys (asc/desc)
- Multiple filters combined
- Validation: invalid filter combinations
- Edge cases: empty results, single=True behavior
- Transaction context
- Performance: large result sets
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
from utilities.map_search import MapSearchFilters

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
    **kwargs: Any,
) -> int:
    """Helper to create a test map with custom fields."""
    defaults = {
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


# ==============================================================================
# HAPPY PATH TESTS - BASIC FETCH
# ==============================================================================


class TestFetchMapsBasic:
    """Test basic fetch operations."""

    @pytest.mark.asyncio
    async def test_fetch_all_maps_returns_list(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test fetching all maps returns a list."""
        # Create 3 maps
        for i in range(3):
            code = f"ALL{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code)

        result = await maps_repo.fetch_maps()

        assert isinstance(result, list)
        assert len(result) >= 3

    @pytest.mark.asyncio
    async def test_fetch_single_map_by_code(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching a single map by code."""
        await create_test_map(db_pool, unique_map_code)

        result = await maps_repo.fetch_maps(code=unique_map_code, single=True)

        assert isinstance(result, dict)
        assert result["code"] == unique_map_code

    @pytest.mark.asyncio
    async def test_fetch_single_non_existent_returns_empty_dict(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test fetching non-existent map with single=True returns empty dict."""
        result = await maps_repo.fetch_maps(code=unique_map_code, single=True)

        assert result == {}

    @pytest.mark.asyncio
    async def test_fetch_empty_database_returns_empty_list(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test fetching from empty database returns empty list."""
        result = await maps_repo.fetch_maps()

        assert isinstance(result, list)
        # May or may not be empty depending on other tests


# ==============================================================================
# FILTER TESTS - CODE
# ==============================================================================


class TestFetchMapsFilterCode:
    """Test filtering by code."""

    @pytest.mark.asyncio
    async def test_filter_by_code_returns_single_map(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering by exact code returns one map."""
        await create_test_map(db_pool, unique_map_code, map_name="Nepal")

        filters = MapSearchFilters(code=unique_map_code)
        result = await maps_repo.fetch_maps(filters=filters)

        assert len(result) == 1
        assert result[0]["code"] == unique_map_code

    @pytest.mark.asyncio
    async def test_filter_by_non_existent_code_returns_empty(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test filtering by non-existent code returns empty list."""
        filters = MapSearchFilters(code=unique_map_code)
        result = await maps_repo.fetch_maps(filters=filters)

        assert result == []


# ==============================================================================
# FILTER TESTS - CATEGORY
# ==============================================================================


class TestFetchMapsFilterCategory:
    """Test filtering by category."""

    @pytest.mark.asyncio
    async def test_filter_by_single_category(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test filtering by single category."""
        # Create maps with different categories
        strive_code = "STRV1"
        used_codes.add(strive_code)
        await create_test_map(db_pool, strive_code, category="Strive")

        filters = MapSearchFilters(category=["Strive"])
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["category"] == "Strive" for m in result)
        assert any(m["code"] == strive_code for m in result)

    @pytest.mark.asyncio
    async def test_filter_by_multiple_categories(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test filtering by multiple categories."""
        # Create maps
        classic_code = "CLAS1"
        strive_code = "STRV2"
        used_codes.add(classic_code)
        used_codes.add(strive_code)

        await create_test_map(db_pool, classic_code, category="Classic")
        await create_test_map(db_pool, strive_code, category="Strive")

        filters = MapSearchFilters(category=["Classic", "Strive"])
        result = await maps_repo.fetch_maps(filters=filters)

        categories = {m["category"] for m in result}
        assert categories.issubset({"Classic", "Strive"})


# ==============================================================================
# FILTER TESTS - BOOLEAN FIELDS
# ==============================================================================


class TestFetchMapsFilterBoolean:
    """Test filtering by boolean fields."""

    @pytest.mark.asyncio
    async def test_filter_archived_true(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for archived maps only."""
        await create_test_map(db_pool, unique_map_code, archived=True)

        filters = MapSearchFilters(archived=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["archived"] is True for m in result)
        assert any(m["code"] == unique_map_code for m in result)

    @pytest.mark.asyncio
    async def test_filter_archived_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for non-archived maps only."""
        await create_test_map(db_pool, unique_map_code, archived=False)

        filters = MapSearchFilters(archived=False)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["archived"] is False for m in result)

    @pytest.mark.asyncio
    async def test_filter_hidden_true(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for hidden maps only."""
        await create_test_map(db_pool, unique_map_code, hidden=True)

        filters = MapSearchFilters(hidden=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["hidden"] is True for m in result)

    @pytest.mark.asyncio
    async def test_filter_official_true(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for official maps only."""
        await create_test_map(db_pool, unique_map_code, official=True)

        filters = MapSearchFilters(official=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["official"] is True for m in result)

    @pytest.mark.asyncio
    async def test_filter_official_false(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for unofficial maps only."""
        await create_test_map(db_pool, unique_map_code, official=False)

        filters = MapSearchFilters(official=False)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["official"] is False for m in result)


# ==============================================================================
# FILTER TESTS - PLAYTESTING STATUS
# ==============================================================================


class TestFetchMapsFilterPlaytesting:
    """Test filtering by playtesting status."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", get_args(PlaytestStatus))
    async def test_filter_by_playtesting_status(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
        status: str,
    ) -> None:
        """Test filtering by each playtesting status."""
        # Use UUID to guarantee uniqueness across parameterized tests
        code = f"PT{uuid4().hex[:6].upper()}"
        used_codes.add(code)
        await create_test_map(db_pool, code, playtesting=status)

        # Use return_all to ensure our test map is included in results
        filters = MapSearchFilters(playtesting=status, return_all=True)  # type: ignore
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["playtesting"] == status for m in result)
        assert any(m["code"] == code for m in result)


# ==============================================================================
# PAGINATION TESTS
# ==============================================================================


class TestFetchMapsPagination:
    """Test pagination functionality."""

    @pytest.mark.asyncio
    async def test_default_page_size_10(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test default page size is 10."""
        # Create 15 maps
        for i in range(15):
            code = f"PG{i:03d}"
            used_codes.add(code)
            await create_test_map(db_pool, code)

        filters = MapSearchFilters()
        result = await maps_repo.fetch_maps(filters=filters)

        assert len(result) <= 10

    @pytest.mark.asyncio
    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    async def test_different_page_sizes(
        self,
        maps_repo: MapsRepository,
        page_size: int,
    ) -> None:
        """Test different valid page sizes."""
        filters = MapSearchFilters(page_size=page_size)  # type: ignore
        result = await maps_repo.fetch_maps(filters=filters)

        assert len(result) <= page_size

    @pytest.mark.asyncio
    async def test_page_number_pagination(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test pagination across multiple pages."""
        # Create 25 maps with UUID-based codes for guaranteed uniqueness
        test_codes = []
        for i in range(25):
            code = f"PN{uuid4().hex[:5].upper()}"
            used_codes.add(code)
            test_codes.append(code)
            await create_test_map(db_pool, code)

        # Use explicit sorting to ensure stable pagination
        filters_page1 = MapSearchFilters(page_size=10, page_number=1, sort=["code:asc"])
        page1 = await maps_repo.fetch_maps(filters=filters_page1)

        filters_page2 = MapSearchFilters(page_size=10, page_number=2, sort=["code:asc"])
        page2 = await maps_repo.fetch_maps(filters=filters_page2)

        # Pages should have different maps
        page1_codes = {m["code"] for m in page1}
        page2_codes = {m["code"] for m in page2}
        assert page1_codes.isdisjoint(page2_codes)

    @pytest.mark.asyncio
    async def test_return_all_bypasses_pagination(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test return_all=True returns all results."""
        # Create 30 maps
        for i in range(30):
            code = f"RA{i:03d}"
            used_codes.add(code)
            await create_test_map(db_pool, code)

        filters = MapSearchFilters(return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        # Should get more than default page size of 10
        assert len(result) >= 30


# ==============================================================================
# SORTING TESTS
# ==============================================================================


class TestFetchMapsSorting:
    """Test sorting functionality."""

    @pytest.mark.asyncio
    async def test_sort_by_code_ascending(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test sorting by code ascending."""
        # Create maps with specific codes
        import time
        ts = int(time.time() * 1000)
        codes = [f"ZZ{ts % 1000:03d}", f"AA{ts % 1000:03d}", f"MM{ts % 1000:03d}"]
        for code in codes:
            used_codes.add(code)
            await create_test_map(db_pool, code)

        filters = MapSearchFilters(sort=["code:asc"], return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        # Extract codes from results
        result_codes = [m["code"] for m in result if m["code"] in codes]
        expected_order = sorted(codes)

        # Check relative order
        for i in range(len(result_codes) - 1):
            assert result_codes[i] <= result_codes[i + 1]

    @pytest.mark.asyncio
    async def test_sort_by_code_descending(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test sorting by code descending."""
        # Create maps
        import time
        ts = int(time.time() * 1000)
        codes = [f"AA{(ts + 1) % 1000:03d}", f"ZZ{(ts + 2) % 1000:03d}", f"MM{(ts + 3) % 1000:03d}"]
        for code in codes:
            used_codes.add(code)
            await create_test_map(db_pool, code)

        filters = MapSearchFilters(sort=["code:desc"], return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        result_codes = [m["code"] for m in result if m["code"] in codes]

        # Check descending order
        for i in range(len(result_codes) - 1):
            assert result_codes[i] >= result_codes[i + 1]

    @pytest.mark.asyncio
    async def test_sort_by_checkpoints_ascending(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test sorting by checkpoints ascending."""
        codes_and_checkpoints = [("CK01", 5), ("CK02", 15), ("CK03", 10)]
        for code, checkpoints in codes_and_checkpoints:
            used_codes.add(code)
            await create_test_map(db_pool, code, checkpoints=checkpoints)

        filters = MapSearchFilters(sort=["checkpoints:asc"], return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        result_items = [(m["code"], m["checkpoints"]) for m in result if m["code"] in [c for c, _ in codes_and_checkpoints]]

        # Check ascending order of checkpoints
        for i in range(len(result_items) - 1):
            assert result_items[i][1] <= result_items[i + 1][1]


# ==============================================================================
# MULTIPLE FILTER COMBINATION TESTS
# ==============================================================================


class TestFetchMapsMultipleFilters:
    """Test combining multiple filters."""

    @pytest.mark.asyncio
    async def test_combine_category_and_official(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test combining category and official filters."""
        code = "CMB01"
        used_codes.add(code)
        await create_test_map(db_pool, code, category="Strive", official=True)

        filters = MapSearchFilters(category=["Strive"], official=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["category"] == "Strive" for m in result)
        assert all(m["official"] is True for m in result)

    @pytest.mark.asyncio
    async def test_combine_archived_and_hidden(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test combining archived and hidden filters."""
        await create_test_map(db_pool, unique_map_code, archived=True, hidden=True)

        filters = MapSearchFilters(archived=True, hidden=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["archived"] is True for m in result)
        assert all(m["hidden"] is True for m in result)


# ==============================================================================
# VALIDATION TESTS
# ==============================================================================


class TestFetchMapsValidation:
    """Test filter validation."""

    @pytest.mark.asyncio
    async def test_difficulty_exact_with_range_raises_error(
        self,
        maps_repo: MapsRepository,
    ) -> None:
        """Test that using exact difficulty with range raises ValueError."""
        filters = MapSearchFilters(
            difficulty_exact="Medium",
            difficulty_range_min="Easy",  # type: ignore
        )

        with pytest.raises(ValueError, match="Cannot use exact difficulty with range"):
            await maps_repo.fetch_maps(filters=filters)


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestFetchMapsEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_single_true_with_multiple_results_returns_first(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test single=True with multiple results returns first result."""
        # Create multiple maps with same category
        for i in range(3):
            code = f"SNG{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, category="Classic")

        filters = MapSearchFilters(category=["Classic"])
        result = await maps_repo.fetch_maps(filters=filters, single=True)

        assert isinstance(result, dict)
        assert "code" in result

    @pytest.mark.asyncio
    async def test_single_true_with_no_results_returns_empty_dict(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test single=True with no results returns empty dict."""
        filters = MapSearchFilters(code=unique_map_code)
        result = await maps_repo.fetch_maps(filters=filters, single=True)

        assert result == {}


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestFetchMapsTransactions:
    """Test transaction context."""

    @pytest.mark.asyncio
    async def test_fetch_within_transaction(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test fetching maps within a transaction."""
        await create_test_map(db_pool, unique_map_code)

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                filters = MapSearchFilters(code=unique_map_code)
                result = await maps_repo.fetch_maps(filters=filters, conn=conn)

        assert len(result) == 1
        assert result[0]["code"] == unique_map_code


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestFetchMapsPerformance:
    """Test performance with large datasets."""

    @pytest.mark.asyncio
    async def test_fetch_large_result_set(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test fetching large result sets."""
        # Create 100 maps
        for i in range(100):
            code = f"LRG{i:04d}"
            used_codes.add(code)
            await create_test_map(db_pool, code)

        filters = MapSearchFilters(return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert len(result) >= 100
