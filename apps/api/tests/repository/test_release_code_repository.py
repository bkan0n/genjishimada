"""Repository tests for release-code methods on MapsRepository."""

import pytest

from repository.maps_repository import MapsRepository

pytestmark = [pytest.mark.domain_maps]


@pytest.fixture
async def repository(asyncpg_pool):
    """Provide MapsRepository backed by the test pool."""
    return MapsRepository(asyncpg_pool)


class TestIsMapArchived:
    """MapsRepository.is_map_archived"""

    async def test_archived_map_returns_true(self, repository, create_test_map):
        """Archived map returns True."""
        code = "TARCH1"
        await create_test_map(code=code, archived=True, map_name="King's Row", category="Classic")
        result = await repository.is_map_archived(code)
        assert result is True

    async def test_non_archived_map_returns_false(self, repository, create_test_map):
        """Non-archived map returns False."""
        code = "TACT01"
        await create_test_map(code=code, archived=False, map_name="King's Row", category="Classic")
        result = await repository.is_map_archived(code)
        assert result is False

    async def test_nonexistent_map_returns_none(self, repository):
        """Nonexistent code returns None."""
        result = await repository.is_map_archived("NOPE1")
        assert result is None


class TestHasUnresolvedChangeRequests:
    """MapsRepository.has_unresolved_change_requests"""

    async def test_no_change_requests_returns_false(self, repository, create_test_map):
        """Map with no CRs returns False."""
        code = "TNOCR"
        await create_test_map(code=code, map_name="King's Row", category="Classic")
        result = await repository.has_unresolved_change_requests(code)
        assert result is False

    async def test_unresolved_cr_returns_true(self, repository, create_test_map, create_test_user, asyncpg_pool):
        """Map with unresolved CR returns True."""
        code = "TUCR01"
        await create_test_map(code=code, map_name="King's Row", category="Classic")
        user_id = await create_test_user()
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.change_requests
                    (thread_id, code, user_id, resolved, change_request_type, content, creator_mentions)
                VALUES ($1, $2, $3, FALSE, 'Other', 'test', '0')
                """,
                900000000000000001,
                code,
                user_id,
            )
        result = await repository.has_unresolved_change_requests(code)
        assert result is True

    async def test_resolved_cr_returns_false(self, repository, create_test_map, create_test_user, asyncpg_pool):
        """Map with only resolved CRs returns False."""
        code = "TRCR01"
        await create_test_map(code=code, map_name="King's Row", category="Classic")
        user_id = await create_test_user()
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.change_requests
                    (thread_id, code, user_id, resolved, change_request_type, content, creator_mentions)
                VALUES ($1, $2, $3, TRUE, 'Other', 'test', '0')
                """,
                900000000000000002,
                code,
                user_id,
            )
        result = await repository.has_unresolved_change_requests(code)
        assert result is False


class TestReleaseCode:
    """MapsRepository.release_code"""

    async def test_sets_code_null_and_preserves_original(self, repository, create_test_map, asyncpg_pool):
        """Release sets code=NULL and original_code=old code."""
        code = "TREL01"
        map_id = await create_test_map(code=code, archived=True, map_name="King's Row", category="Classic")

        async with asyncpg_pool.acquire() as conn, conn.transaction():
            await repository.release_code(code, map_id, conn=conn)

        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT code, original_code FROM core.maps WHERE id = $1", map_id)

        assert row["code"] is None
        assert row["original_code"] == code

    async def test_clears_edit_request_code(self, repository, create_test_map, create_test_user, asyncpg_pool):
        """Release sets edit_requests.code to NULL."""
        code = "TREL02"
        map_id = await create_test_map(code=code, archived=True, map_name="King's Row", category="Classic")
        user_id = await create_test_user()

        # Seed an edit request
        async with asyncpg_pool.acquire() as conn:
            edit_id = await conn.fetchval(
                """
                INSERT INTO maps.edit_requests (map_id, code, proposed_changes, reason, created_by)
                VALUES ($1, $2, '{}', 'test', $3)
                RETURNING id
                """,
                map_id,
                code,
                user_id,
            )

        async with asyncpg_pool.acquire() as conn, conn.transaction():
            await repository.release_code(code, map_id, conn=conn)

        async with asyncpg_pool.acquire() as conn:
            edit_code = await conn.fetchval("SELECT code FROM maps.edit_requests WHERE id = $1", edit_id)

        assert edit_code is None
