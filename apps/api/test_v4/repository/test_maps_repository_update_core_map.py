"""Exhaustive tests for MapsRepository.update_core_map method.

Test Coverage:
- Happy path: update single field
- Happy path: update multiple fields
- Update each field individually (all fields)
- Update all fields at once
- Empty update (no fields)
- Non-existent map updates (silent failure)
- Constraint violations: duplicate code
- Field validation: difficulty, title length, checkpoints
- NULL values for optional fields
- Transaction handling: commit and rollback
- Performance: sequential updates
- Edge cases: update to same values
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
        "raw_difficulty": fake.pyfloat(min_value=raw_min, max_value=raw_max, right_digits=2),
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
# HAPPY PATH TESTS - SINGLE FIELD
# ==============================================================================


class TestUpdateCoreMapSingleField:
    """Test updating a single field at a time."""

    @pytest.mark.asyncio
    async def test_update_map_name(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the map_name field."""
        new_map_name = "Nepal"
        await maps_repo.update_core_map(existing_map["code"], {"map_name": new_map_name})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT map_name FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["map_name"] == new_map_name

    @pytest.mark.asyncio
    async def test_update_category(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the category field."""
        new_category = "Strive"
        await maps_repo.update_core_map(existing_map["code"], {"category": new_category})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT category FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["category"] == new_category

    @pytest.mark.asyncio
    async def test_update_checkpoints(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the checkpoints field."""
        new_checkpoints = 999
        await maps_repo.update_core_map(existing_map["code"], {"checkpoints": new_checkpoints})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT checkpoints FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["checkpoints"] == new_checkpoints

    @pytest.mark.asyncio
    async def test_update_official(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the official field."""
        new_official = not existing_map["official"]
        await maps_repo.update_core_map(existing_map["code"], {"official": new_official})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT official FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["official"] == new_official

    @pytest.mark.asyncio
    async def test_update_playtesting(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the playtesting field."""
        new_playtesting = "In Progress"
        await maps_repo.update_core_map(existing_map["code"], {"playtesting": new_playtesting})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT playtesting FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["playtesting"] == new_playtesting

    @pytest.mark.asyncio
    async def test_update_difficulty(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the difficulty field."""
        new_difficulty = "Hell"
        await maps_repo.update_core_map(existing_map["code"], {"difficulty": new_difficulty})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT difficulty FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["difficulty"] == new_difficulty

    @pytest.mark.asyncio
    async def test_update_raw_difficulty(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the raw_difficulty field."""
        new_raw_difficulty = 9.5
        await maps_repo.update_core_map(existing_map["code"], {"raw_difficulty": new_raw_difficulty})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT raw_difficulty FROM core.maps WHERE code = $1", existing_map["code"])

        assert float(result["raw_difficulty"]) == pytest.approx(new_raw_difficulty, abs=0.01)

    @pytest.mark.asyncio
    async def test_update_hidden(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the hidden field."""
        new_hidden = True
        await maps_repo.update_core_map(existing_map["code"], {"hidden": new_hidden})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT hidden FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["hidden"] == new_hidden

    @pytest.mark.asyncio
    async def test_update_archived(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the archived field."""
        new_archived = True
        await maps_repo.update_core_map(existing_map["code"], {"archived": new_archived})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT archived FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["archived"] == new_archived

    @pytest.mark.asyncio
    async def test_update_description(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the description field."""
        new_description = fake.sentence(nb_words=20)
        await maps_repo.update_core_map(existing_map["code"], {"description": new_description})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT description FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["description"] == new_description

    @pytest.mark.asyncio
    async def test_update_custom_banner(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the custom_banner field."""
        new_custom_banner = fake.url()
        await maps_repo.update_core_map(existing_map["code"], {"custom_banner": new_custom_banner})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT custom_banner FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["custom_banner"] == new_custom_banner

    @pytest.mark.asyncio
    async def test_update_title(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating only the title field."""
        new_title = fake.sentence(nb_words=3)[:50]
        await maps_repo.update_core_map(existing_map["code"], {"title": new_title})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT title FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["title"] == new_title


# ==============================================================================
# HAPPY PATH TESTS - MULTIPLE FIELDS
# ==============================================================================


class TestUpdateCoreMapMultipleFields:
    """Test updating multiple fields at once."""

    @pytest.mark.asyncio
    async def test_update_two_fields(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating two fields at once."""
        updates = {
            "map_name": "Kanezaka",
            "checkpoints": 25,
        }

        await maps_repo.update_core_map(existing_map["code"], updates)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT map_name, checkpoints FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["map_name"] == updates["map_name"]
        assert result["checkpoints"] == updates["checkpoints"]

    @pytest.mark.asyncio
    async def test_update_multiple_fields(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating multiple fields at once."""
        # Note: Don't update both difficulty and raw_difficulty in same update
        # Database trigger will calculate difficulty from raw_difficulty
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
    async def test_update_all_fields(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating all updatable fields at once."""
        updates = {
            "map_name": "Busan",
            "category": "Beginner",
            "checkpoints": 30,
            "official": False,
            "playtesting": "Rejected",
            "difficulty": "Extreme",
            "raw_difficulty": 8.8,
            "hidden": True,
            "archived": True,
            "description": "Updated description",
            "custom_banner": "https://example.com/banner.png",
            "title": "Updated Title",
        }

        await maps_repo.update_core_map(existing_map["code"], updates)

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["map_name"] == updates["map_name"]
        assert result["category"] == updates["category"]
        assert result["checkpoints"] == updates["checkpoints"]
        assert result["official"] == updates["official"]
        assert result["playtesting"] == updates["playtesting"]
        assert result["difficulty"] == updates["difficulty"]
        assert float(result["raw_difficulty"]) == pytest.approx(updates["raw_difficulty"], abs=0.01)
        assert result["hidden"] == updates["hidden"]
        assert result["archived"] == updates["archived"]
        assert result["description"] == updates["description"]
        assert result["custom_banner"] == updates["custom_banner"]
        assert result["title"] == updates["title"]


# ==============================================================================
# EMPTY UPDATE TESTS
# ==============================================================================


class TestUpdateCoreMapEmpty:
    """Test updating with empty data."""

    @pytest.mark.asyncio
    async def test_update_with_empty_dict_does_nothing(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test that updating with empty dict returns without error."""
        # Get original values
        async with db_pool.acquire() as conn:
            original = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", existing_map["code"])

        # Update with empty dict
        await maps_repo.update_core_map(existing_map["code"], {})

        # Verify nothing changed
        async with db_pool.acquire() as conn:
            updated = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", existing_map["code"])

        assert dict(original) == dict(updated)


# ==============================================================================
# NON-EXISTENT MAP TESTS
# ==============================================================================


class TestUpdateCoreMapNonExistent:
    """Test updating non-existent maps."""

    @pytest.mark.asyncio
    async def test_update_non_existent_map_silent_failure(
        self,
        maps_repo: MapsRepository,
        unique_map_code: str,
    ) -> None:
        """Test that updating non-existent map doesn't raise error (silent failure)."""
        # Should not raise an error, just updates 0 rows
        await maps_repo.update_core_map(unique_map_code, {"map_name": "Ghost Map"})

        # No exception means test passes


# ==============================================================================
# CONSTRAINT VIOLATION TESTS
# ==============================================================================


class TestUpdateCoreMapConstraints:
    """Test constraint violations during update."""

    @pytest.mark.asyncio
    async def test_update_code_to_duplicate_raises_error(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
        used_codes: set[str],
    ) -> None:
        """Test that updating code to existing code raises UniqueConstraintViolationError."""
        # Generate a different unique code for the second map
        import time
        second_code = f"DUP{str(int(time.time() * 1000))[-4:]}"
        used_codes.add(second_code)

        # Create another map
        async with db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                second_code,
                "Other Map",
                "Classic",
                10,
                True,
                "Approved",
                "Medium",
                5.0,
            )

        # Try to update existing_map's code to the other map's code
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await maps_repo.update_core_map(existing_map["code"], {"code": second_code})

        assert "maps_code_key" in exc_info.value.constraint_name


# ==============================================================================
# FIELD VALIDATION TESTS
# ==============================================================================


class TestUpdateCoreMapValidation:
    """Test field validation during updates."""

    @pytest.mark.asyncio
    async def test_update_title_exceeding_max_length_fails(
        self,
        maps_repo: MapsRepository,
        existing_map: dict[str, Any],
    ) -> None:
        """Test that updating title to >50 chars fails."""
        long_title = "A" * 51

        with pytest.raises((asyncpg.CheckViolationError, Exception)):
            await maps_repo.update_core_map(existing_map["code"], {"title": long_title})

    @pytest.mark.asyncio
    async def test_update_title_to_max_length_succeeds(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test that updating title to exactly 50 chars succeeds."""
        max_title = "A" * 50

        await maps_repo.update_core_map(existing_map["code"], {"title": max_title})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT title FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["title"] == max_title

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "difficulty",
        ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"],
    )
    async def test_update_all_valid_difficulties(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
        difficulty: str,
    ) -> None:
        """Test updating to all valid difficulty values."""
        await maps_repo.update_core_map(existing_map["code"], {"difficulty": difficulty})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT difficulty FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["difficulty"] == difficulty


# ==============================================================================
# NULL VALUE TESTS
# ==============================================================================


class TestUpdateCoreMapNullValues:
    """Test updating optional fields to NULL."""

    @pytest.mark.asyncio
    async def test_update_description_to_null(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating description to NULL."""
        await maps_repo.update_core_map(existing_map["code"], {"description": None})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT description FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["description"] is None

    @pytest.mark.asyncio
    async def test_update_custom_banner_to_null(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating custom_banner to NULL."""
        await maps_repo.update_core_map(existing_map["code"], {"custom_banner": None})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT custom_banner FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["custom_banner"] is None

    @pytest.mark.asyncio
    async def test_update_title_to_null(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating title to NULL."""
        await maps_repo.update_core_map(existing_map["code"], {"title": None})

        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT title FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["title"] is None


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestUpdateCoreMapTransactions:
    """Test transaction handling."""

    @pytest.mark.asyncio
    async def test_update_within_transaction_committed(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating within a committed transaction."""
        new_map_name = "Transaction Map"

        async with db_pool.acquire() as conn:
            async with conn.transaction():
                await maps_repo.update_core_map(existing_map["code"], {"map_name": new_map_name}, conn=conn)

        # Verify update persisted
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT map_name FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["map_name"] == new_map_name

    @pytest.mark.asyncio
    async def test_update_within_transaction_rolled_back(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test that rolled back transaction doesn't persist update."""
        original_map_name = existing_map["map_name"]
        new_map_name = "Rollback Map"

        async with db_pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await maps_repo.update_core_map(existing_map["code"], {"map_name": new_map_name}, conn=conn)
                    # Force rollback
                    raise Exception("Force rollback")
            except Exception:
                pass

        # Verify update was rolled back
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT map_name FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["map_name"] == original_map_name


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestUpdateCoreMapEdgeCases:
    """Test edge cases."""

    @pytest.mark.asyncio
    async def test_update_to_same_values_succeeds(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test updating fields to their current values."""
        # Update to same values
        await maps_repo.update_core_map(
            existing_map["code"],
            {
                "map_name": existing_map["map_name"],
                "checkpoints": existing_map["checkpoints"],
            },
        )

        # Verify values unchanged
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow(
                "SELECT map_name, checkpoints FROM core.maps WHERE code = $1",
                existing_map["code"],
            )

        assert result["map_name"] == existing_map["map_name"]
        assert result["checkpoints"] == existing_map["checkpoints"]

    @pytest.mark.asyncio
    async def test_update_code_field(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
        used_codes: set[str],
    ) -> None:
        """Test updating the code field itself."""
        old_code = existing_map["code"]

        # Generate a truly unique new code
        import time
        new_code = f"NEW{str(int(time.time() * 1000))[-4:]}"
        used_codes.add(new_code)

        await maps_repo.update_core_map(old_code, {"code": new_code})

        # Verify old code doesn't exist
        async with db_pool.acquire() as conn:
            old_result = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", old_code)

        assert old_result is None

        # Verify new code exists
        async with db_pool.acquire() as conn:
            new_result = await conn.fetchrow("SELECT * FROM core.maps WHERE code = $1", new_code)

        assert new_result is not None
        assert new_result["code"] == new_code


# ==============================================================================
# PERFORMANCE TESTS
# ==============================================================================


class TestUpdateCoreMapPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_sequential_updates(
        self,
        maps_repo: MapsRepository,
        db_pool: asyncpg.Pool,
        existing_map: dict[str, Any],
    ) -> None:
        """Test multiple sequential updates to same map."""
        for i in range(5):
            await maps_repo.update_core_map(existing_map["code"], {"checkpoints": 10 + i})

        # Verify final value
        async with db_pool.acquire() as conn:
            result = await conn.fetchrow("SELECT checkpoints FROM core.maps WHERE code = $1", existing_map["code"])

        assert result["checkpoints"] == 14  # 10 + 4
