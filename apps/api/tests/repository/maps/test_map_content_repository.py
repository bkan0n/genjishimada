"""Real-DB tests for MapContentRepository (insert_map_name + fetch_all_map_names).

These run under tests/repository/ where migrations are applied (the services/
conftest no-ops setup_test_db, so real-DB tests cannot live there).

`maps.names` is a shared session-scoped seed table, so inserts use unique,
test-namespaced names and clean themselves up to avoid cross-test pollution.
"""

import uuid

import pytest

from repository.map_content_repository import MapContentRepository

pytestmark = [pytest.mark.domain_maps]


def _unique_name(prefix: str = "Test Map") -> str:
    """Return a name guaranteed absent from the seed set."""
    return f"{prefix} {uuid.uuid4().hex[:12]}"


@pytest.fixture
async def map_content_repo(asyncpg_pool):
    """Provide MapContentRepository backed by the real test pool."""
    return MapContentRepository(asyncpg_pool)


@pytest.fixture
async def cleanup_names(asyncpg_pool):
    """Track names inserted by a test and delete them afterward."""
    inserted: list[str] = []
    yield inserted
    if inserted:
        async with asyncpg_pool.acquire() as conn:
            await conn.execute("DELETE FROM maps.names WHERE name = ANY($1::text[])", inserted)


class TestInsertMapName:
    """MapContentRepository.insert_map_name (ON CONFLICT DO NOTHING)."""

    async def test_insert_new_name_returns_inserted_true(self, map_content_repo, cleanup_names):
        """Inserting a brand new name returns inserted=True."""
        name = _unique_name("Brand New Map")
        cleanup_names.append(name)

        result = await map_content_repo.insert_map_name(name)

        assert result == {"name": name, "inserted": True}

    async def test_insert_existing_name_returns_inserted_false(self, map_content_repo, cleanup_names):
        """Re-inserting an existing name returns inserted=False with no exception."""
        name = _unique_name("Existing Map")
        cleanup_names.append(name)

        first = await map_content_repo.insert_map_name(name)
        assert first["inserted"] is True

        second = await map_content_repo.insert_map_name(name)
        assert second == {"name": name, "inserted": False}


class TestFetchAllMapNames:
    """MapContentRepository.fetch_all_map_names."""

    async def test_fetch_all_returns_sorted_list(self, map_content_repo, cleanup_names):
        """fetch_all_map_names returns all rows sorted ascending."""
        name = _unique_name("Zzz Fetch Map")
        cleanup_names.append(name)
        await map_content_repo.insert_map_name(name)

        names = await map_content_repo.fetch_all_map_names()

        assert isinstance(names, list)
        assert name in names
        # Returned in ascending order.
        assert names == sorted(names)
        # Includes a known seed name.
        assert "Hanamura" in names
