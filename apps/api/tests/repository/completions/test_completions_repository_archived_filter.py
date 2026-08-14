"""Tests for the archived tribool filter on the personal-records queries.

Covers CompletionsRepository.fetch_user_completions and
CompletionsRepository.fetch_world_records_per_user.

Test Coverage:
- fetch_user_completions: default returns both archived and non-archived (1 test)
- fetch_user_completions: explicit "all" matches the default (1 test)
- fetch_user_completions: "archived" returns only archived maps (1 test)
- fetch_user_completions: "not_archived" returns only non-archived maps (1 test)
- fetch_user_completions: filter does not alter rank of returned rows (1 test)
- fetch_world_records_per_user: default returns both (1 test)
- fetch_world_records_per_user: "archived" returns only archived maps (1 test)
- fetch_world_records_per_user: "not_archived" returns only non-archived maps (1 test)

Total: 8 tests
"""

import asyncpg
import pytest

from repository.completions_repository import CompletionsRepository

pytestmark = [
    pytest.mark.domain_completions,
]


@pytest.fixture
async def completions_repo(asyncpg_pool: asyncpg.Pool) -> CompletionsRepository:
    """Create repository instance."""
    return CompletionsRepository(asyncpg_pool)


@pytest.fixture
async def archived_pair(create_test_map, create_test_user, create_test_completion) -> dict:
    """Create one archived and one non-archived map, both completed by one user.

    Both completions are timed runs (completion=False) so they are rankable,
    which lets the same fixture drive the world-records assertions.
    """
    user_id = await create_test_user()
    archived_map_id = await create_test_map(archived=True)
    active_map_id = await create_test_map(archived=False)

    await create_test_completion(user_id, archived_map_id, completion=False, time=25.0)
    await create_test_completion(user_id, active_map_id, completion=False, time=35.0)

    return {
        "user_id": user_id,
        "archived_map_id": archived_map_id,
        "active_map_id": active_map_id,
    }


async def _codes_for_map_ids(pool: asyncpg.Pool, map_ids: list[int]) -> set[str]:
    """Look up the map codes for a list of map IDs."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code FROM core.maps WHERE id = ANY($1::bigint[])", map_ids)
    return {row["code"] for row in rows}


class TestFetchUserCompletionsArchivedFilter:
    """Archived filter behaviour on fetch_user_completions."""

    @pytest.mark.asyncio
    async def test_default_returns_archived_and_active(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """Omitting the filter keeps the pre-filter behaviour: both maps returned."""
        rows = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
        )

        expected = await _codes_for_map_ids(
            asyncpg_pool,
            [archived_pair["archived_map_id"], archived_pair["active_map_id"]],
        )
        assert {row["code"] for row in rows} == expected

    @pytest.mark.asyncio
    async def test_explicit_all_matches_default(
        self,
        completions_repo: CompletionsRepository,
        archived_pair: dict,
    ) -> None:
        """Passing "all" explicitly is identical to omitting the parameter."""
        default_rows = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
        )
        explicit_rows = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
            archived="all",
        )

        assert [row["code"] for row in default_rows] == [row["code"] for row in explicit_rows]

    @pytest.mark.asyncio
    async def test_archived_only(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """"archived" returns only completions on archived maps."""
        rows = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
            archived="archived",
        )

        expected = await _codes_for_map_ids(asyncpg_pool, [archived_pair["archived_map_id"]])
        assert {row["code"] for row in rows} == expected

    @pytest.mark.asyncio
    async def test_not_archived_only(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """"not_archived" returns only completions on non-archived maps."""
        rows = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
            archived="not_archived",
        )

        expected = await _codes_for_map_ids(asyncpg_pool, [archived_pair["active_map_id"]])
        assert {row["code"] for row in rows} == expected

    @pytest.mark.asyncio
    async def test_filter_does_not_change_rank(
        self,
        completions_repo: CompletionsRepository,
        create_test_user,
        create_test_completion,
        archived_pair: dict,
    ) -> None:
        """Excluding archived maps must not change ranks on the maps still returned.

        A second, faster user is added to the non-archived map so the target user
        ranks 2nd there. That rank must be identical with and without the filter.
        """
        faster_user = await create_test_user()
        await create_test_completion(faster_user, archived_pair["active_map_id"], completion=False, time=10.0)

        unfiltered = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
        )
        filtered = await completions_repo.fetch_user_completions(
            user_id=archived_pair["user_id"],
            difficulty=None,
            page_size=100,
            page_number=1,
            archived="not_archived",
        )

        ranks_unfiltered = {row["code"]: row["rank"] for row in unfiltered}
        ranks_filtered = {row["code"]: row["rank"] for row in filtered}

        assert len(ranks_filtered) == 1
        for code, rank in ranks_filtered.items():
            assert rank == ranks_unfiltered[code]
            assert rank == 2


class TestFetchWorldRecordsArchivedFilter:
    """Archived filter behaviour on fetch_world_records_per_user."""

    @pytest.mark.asyncio
    async def test_default_returns_archived_and_active(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """Omitting the filter keeps the pre-filter behaviour: both maps returned."""
        rows = await completions_repo.fetch_world_records_per_user(archived_pair["user_id"])

        expected = await _codes_for_map_ids(
            asyncpg_pool,
            [archived_pair["archived_map_id"], archived_pair["active_map_id"]],
        )
        assert {row["code"] for row in rows} == expected

    @pytest.mark.asyncio
    async def test_archived_only(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """"archived" returns only world records on archived maps."""
        rows = await completions_repo.fetch_world_records_per_user(
            archived_pair["user_id"],
            archived="archived",
        )

        expected = await _codes_for_map_ids(asyncpg_pool, [archived_pair["archived_map_id"]])
        assert {row["code"] for row in rows} == expected

    @pytest.mark.asyncio
    async def test_not_archived_only(
        self,
        completions_repo: CompletionsRepository,
        asyncpg_pool: asyncpg.Pool,
        archived_pair: dict,
    ) -> None:
        """"not_archived" returns only world records on non-archived maps."""
        rows = await completions_repo.fetch_world_records_per_user(
            archived_pair["user_id"],
            archived="not_archived",
        )

        expected = await _codes_for_map_ids(asyncpg_pool, [archived_pair["active_map_id"]])
        assert {row["code"] for row in rows} == expected
