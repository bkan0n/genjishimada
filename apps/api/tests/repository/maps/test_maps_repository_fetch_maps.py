"""Tests for MapsRepository.fetch_maps method.

Test Coverage (12 tests):
- Happy path: fetch all maps (1 test)
- Filter: category (2 tests - single and multiple)
- Filter: boolean fields (1 test - archived/hidden combination)
- Filter: playtesting status (1 parameterized test)
- Filter: creator IDs (1 test)
- Pagination: different page sizes, page numbers (2 tests)
- Sorting: ascending and descending (2 tests)
- Count accuracy (1 test)
- Multiple filters combined (1 test)
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


async def create_test_user(db_pool: asyncpg.Pool, user_id: int, nickname: str) -> int:
    """Helper to create a test user."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET nickname = EXCLUDED.nickname
            """,
            user_id,
            nickname,
        )
    return user_id


async def add_map_creator(db_pool: asyncpg.Pool, map_id: int, user_id: int) -> None:
    """Helper to add a creator to a map."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id, is_primary)
            VALUES ($1, $2, TRUE)
            ON CONFLICT (map_id, user_id) DO NOTHING
            """,
            map_id,
            user_id,
        )


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
# FILTER TESTS - CREATORS
# ==============================================================================


class TestFetchMapsFilterCreators:
    """Test filtering by creators."""

    @pytest.mark.asyncio
    async def test_filter_by_creator_ids(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test filtering by creator IDs."""
        # Create a test user (using Discord ID as the ID)
        user_id = 123456789
        await create_test_user(db_pool, user_id=user_id, nickname="TestCreator")

        # Create a map and assign the creator
        code = "CRT01"
        used_codes.add(code)
        map_id = await create_test_map(db_pool, code)
        await add_map_creator(db_pool, map_id, user_id)

        # Filter by creator ID
        filters = MapSearchFilters(creator_ids=[user_id], return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        # Verify the map is in the results
        assert any(m["code"] == code for m in result)


# ==============================================================================
# FILTER TESTS - BOOLEAN FIELDS
# ==============================================================================


class TestFetchMapsFilterBoolean:
    """Test filtering by boolean fields."""

    @pytest.mark.asyncio
    async def test_filter_archived_and_hidden(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        unique_map_code: str,
    ) -> None:
        """Test filtering for archived and hidden maps."""
        await create_test_map(db_pool, unique_map_code, archived=True, hidden=True)

        filters = MapSearchFilters(archived=True, hidden=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert all(m["archived"] is True for m in result)
        assert all(m["hidden"] is True for m in result)


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


# ==============================================================================
# COUNT ACCURACY TEST
# ==============================================================================


class TestFetchMapsCount:
    """Test count accuracy."""

    @pytest.mark.asyncio
    async def test_fetch_count_matches_results(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        used_codes: set[str],
    ) -> None:
        """Test that fetch returns correct number of maps."""
        # Create 5 maps with unique category
        category = "CountTest"
        for i in range(5):
            code = f"CNT{i:02d}"
            used_codes.add(code)
            await create_test_map(db_pool, code, category=category)

        filters = MapSearchFilters(category=[category], return_all=True)
        result = await maps_repo.fetch_maps(filters=filters)

        assert len(result) == 5
