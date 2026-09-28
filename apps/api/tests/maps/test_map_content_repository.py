"""Real-DB tests for MapContentRepository (insert_map_name + fetch_all_map_names).

The database fixture restores migration-seeded map names before every test.
"""

import uuid

import pytest

from repository.map_content_repository import MapContentRepository

pytestmark = [pytest.mark.domain_maps, pytest.mark.database]


def _unique_name(prefix: str = "Test Map") -> str:
    """Return a name guaranteed absent from the seed set."""
    return f"{prefix} {uuid.uuid4().hex[:12]}"


@pytest.fixture
async def map_content_repo(asyncpg_pool):
    """Provide MapContentRepository backed by the real test pool."""
    return MapContentRepository(asyncpg_pool)




class TestInsertMapName:
    """MapContentRepository.insert_map_name (ON CONFLICT DO NOTHING)."""

    async def test_insert_new_name_returns_inserted_true(self, map_content_repo):
        """Inserting a brand new name returns inserted=True."""
        name = _unique_name("Brand New Map")

        result = await map_content_repo.insert_map_name(name)

        assert result == {"name": name, "inserted": True}

    async def test_insert_existing_name_returns_inserted_false(self, map_content_repo):
        """Re-inserting an existing name returns inserted=False with no exception."""
        name = _unique_name("Existing Map")

        first = await map_content_repo.insert_map_name(name)
        assert first["inserted"] is True

        second = await map_content_repo.insert_map_name(name)
        assert second == {"name": name, "inserted": False}


class TestFetchAllMapNames:
    """MapContentRepository.fetch_all_map_names."""

    async def test_fetch_all_returns_sorted_list(self, map_content_repo):
        """fetch_all_map_names returns all rows sorted ascending."""
        name = _unique_name("Zzz Fetch Map")
        await map_content_repo.insert_map_name(name)

        names = await map_content_repo.fetch_all_map_names()

        assert isinstance(names, list)
        assert name in names
        # Returned in ascending order.
        assert names == sorted(names)
        # Includes a known seed name.
        assert "Hanamura" in names
