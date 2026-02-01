"""Focused tests for MapsRepository.update_core_map method.

Test Coverage:
- Update single field (different field types)
- Update multiple fields
- Partial update
- Update with valid enum values
- Update timestamps
- No-op update (same values)
- Transaction commit
- Updated_at auto-update
"""

from typing import Any, get_args

import asyncpg
import pytest
from faker import Faker
from genjishimada_sdk import difficulties
from genjishimada_sdk.maps import MapCategory, OverwatchMap
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


@pytest.fixture
async def existing_map(
    db_pool: asyncpg.Pool,
    unique_map_code: str,
) -> dict[str, Any]:
    """Create an existing map to update in tests."""
    diff = "Medium"
    raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[diff]  # type: ignore

    map_data = {
        "code": unique_map_code,
        "map_name": fake.random_element(elements=get_args(OverwatchMap)),
        "category": fake.random_element(elements=get_args(MapCategory)),
        "checkpoints": fake.random_int(min=1, max=50),
        "official": True,
        "playtesting": "Approved",
        "difficulty": diff,
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2),
        "hidden": False,
        "archived": False,
        "description": fake.sentence(nb_words=10),
        "custom_banner": None,
        "title": fake.sentence(nb_words=3)[:50],
    }

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
            map_data["code"],
            map_data["map_name"],
            map_data["category"],
            map_data["checkpoints"],
            map_data["official"],
            map_data["playtesting"],
            map_data["hidden"],
            map_data["archived"],
            map_data["difficulty"],
            map_data["raw_difficulty"],
            map_data["description"],
            map_data["custom_banner"],
            map_data["title"],
        )

    map_data["id"] = map_id
    return map_data


# ==============================================================================
# CORE TESTS
# ==============================================================================


@pytest.mark.asyncio
async def test_update_single_field_string(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test updating a single string field."""
    new_map_name = "Nepal"
    await maps_repo.update_core_map(existing_map["code"], {"map_name": new_map_name})

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT map_name FROM core.maps WHERE code = $1", existing_map["code"])

    assert result["map_name"] == new_map_name


@pytest.mark.asyncio
async def test_update_single_field_integer(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test updating a single integer field."""
    new_checkpoints = 42
    await maps_repo.update_core_map(existing_map["code"], {"checkpoints": new_checkpoints})

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT checkpoints FROM core.maps WHERE code = $1", existing_map["code"])

    assert result["checkpoints"] == new_checkpoints


@pytest.mark.asyncio
async def test_update_single_field_boolean(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test updating a single boolean field."""
    new_hidden = True
    await maps_repo.update_core_map(existing_map["code"], {"hidden": new_hidden})

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT hidden FROM core.maps WHERE code = $1", existing_map["code"])

    assert result["hidden"] == new_hidden


@pytest.mark.asyncio
async def test_update_multiple_fields(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test updating multiple fields at once."""
    updates = {
        "map_name": "Ilios",
        "category": "Strive",
        "checkpoints": 15,
        "official": False,
    }

    await maps_repo.update_core_map(existing_map["code"], updates)

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT map_name, category, checkpoints, official FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    assert result["map_name"] == updates["map_name"]
    assert result["category"] == updates["category"]
    assert result["checkpoints"] == updates["checkpoints"]
    assert result["official"] == updates["official"]


@pytest.mark.asyncio
async def test_partial_update_preserves_other_fields(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test that partial update preserves unchanged fields."""
    original_checkpoints = existing_map["checkpoints"]

    # Only update map_name
    await maps_repo.update_core_map(existing_map["code"], {"map_name": "Busan"})

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT map_name, checkpoints FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    assert result["map_name"] == "Busan"
    assert result["checkpoints"] == original_checkpoints


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "difficulty",
    ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"],
)
async def test_update_with_valid_enum_values(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
    difficulty: str,
) -> None:
    """Test updating with all valid enum values."""
    await maps_repo.update_core_map(existing_map["code"], {"difficulty": difficulty})

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT difficulty FROM core.maps WHERE code = $1", existing_map["code"])

    assert result["difficulty"] == difficulty


@pytest.mark.asyncio
async def test_update_timestamps_are_automatic(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test that updated_at timestamp is automatically updated."""
    # Get original timestamps
    async with db_pool.acquire() as conn:
        original = await conn.fetchrow(
            "SELECT created_at, updated_at FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    # Wait a moment to ensure timestamp difference
    import asyncio

    await asyncio.sleep(0.1)

    # Update the map
    await maps_repo.update_core_map(existing_map["code"], {"map_name": "Updated"})

    # Get new timestamps
    async with db_pool.acquire() as conn:
        updated = await conn.fetchrow(
            "SELECT created_at, updated_at FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    # created_at should be unchanged, updated_at should be newer
    assert updated["created_at"] == original["created_at"]
    assert updated["updated_at"] > original["updated_at"]


@pytest.mark.asyncio
async def test_no_op_update_with_same_values(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test that updating with same values succeeds without error."""
    await maps_repo.update_core_map(
        existing_map["code"],
        {
            "map_name": existing_map["map_name"],
            "checkpoints": existing_map["checkpoints"],
        },
    )

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT map_name, checkpoints FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    assert result["map_name"] == existing_map["map_name"]
    assert result["checkpoints"] == existing_map["checkpoints"]


@pytest.mark.asyncio
async def test_transaction_commit_persists_changes(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test that update within a committed transaction persists."""
    new_map_name = "Transaction Map"

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await maps_repo.update_core_map(existing_map["code"], {"map_name": new_map_name}, conn=conn)

    # Verify update persisted
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow("SELECT map_name FROM core.maps WHERE code = $1", existing_map["code"])

    assert result["map_name"] == new_map_name


@pytest.mark.asyncio
async def test_updated_at_auto_updates_on_change(
    maps_repo: MapsRepository,
    db_pool: asyncpg.Pool,
    existing_map: dict[str, Any],
) -> None:
    """Test that updated_at is automatically updated when fields change."""
    # Get original updated_at
    async with db_pool.acquire() as conn:
        original = await conn.fetchval(
            "SELECT updated_at FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    # Wait briefly to ensure timestamp difference
    import asyncio

    await asyncio.sleep(0.1)

    # Perform update
    await maps_repo.update_core_map(existing_map["code"], {"checkpoints": 99})

    # Get new updated_at
    async with db_pool.acquire() as conn:
        new = await conn.fetchval(
            "SELECT updated_at FROM core.maps WHERE code = $1",
            existing_map["code"],
        )

    # Verify updated_at changed
    assert new > original
