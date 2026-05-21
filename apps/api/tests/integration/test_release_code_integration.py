"""Integration tests for PATCH /api/v3/maps/{code}/release-code."""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_maps,
]

ENDPOINT = "/api/v3/maps/{code}/release-code"


class TestReleaseCodePreconditions:
    """Precondition validation for release-code endpoint."""

    async def test_nonexistent_map_returns_404(self, test_client):
        """Release code on non-existent map returns 404."""
        response = await test_client.patch(ENDPOINT.format(code="ZZZZZ"))
        assert response.status_code == 404

    async def test_non_archived_map_returns_409(self, test_client, create_test_map):
        """Release code on non-archived map returns 409."""
        code = "TNARC"
        await create_test_map(code=code, archived=False)
        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 409
        assert "archived" in response.json()["error"].lower()

    async def test_unresolved_crs_returns_409(
        self, test_client, create_test_map, create_test_user, asyncpg_pool
    ):
        """Release code with unresolved change requests returns 409."""
        code = "TUCR02"
        await create_test_map(code=code, archived=True)
        user_id = await create_test_user()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.change_requests
                    (thread_id, code, user_id, resolved, change_request_type, content, creator_mentions)
                VALUES ($1, $2, $3, FALSE, 'Other', 'test', '0')
                """,
                900000000000000010,
                code,
                user_id,
            )

        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 409
        assert "change request" in response.json()["error"].lower()

    async def test_resolved_crs_allow_release(
        self, test_client, create_test_map, create_test_user, asyncpg_pool
    ):
        """Release code succeeds when all CRs are resolved."""
        code = "TRCR02"
        await create_test_map(code=code, archived=True)
        user_id = await create_test_user()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.change_requests
                    (thread_id, code, user_id, resolved, change_request_type, content, creator_mentions)
                VALUES ($1, $2, $3, TRUE, 'Other', 'test', '0')
                """,
                900000000000000011,
                code,
                user_id,
            )

        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 204

    async def test_requires_auth(self, unauthenticated_client, create_test_map):
        """Release code without auth returns 401."""
        code = "TAUTH"
        await create_test_map(code=code, archived=True)
        response = await unauthenticated_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 401


class TestReleaseCodeBehavior:
    """Core behavior after successful release."""

    async def test_code_becomes_null(self, test_client, create_test_map, asyncpg_pool):
        """After release, map's code is NULL."""
        code = "TREL03"
        map_id = await create_test_map(code=code, archived=True)

        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 204

        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT code, original_code FROM core.maps WHERE id = $1", map_id)

        assert row["code"] is None
        assert row["original_code"] == code

    async def test_lookup_returns_none_after_release(self, test_client, create_test_map, asyncpg_pool):
        """After release, looking up the old code finds nothing."""
        code = "TREL04"
        await create_test_map(code=code, archived=True)

        await test_client.patch(ENDPOINT.format(code=code))

        async with asyncpg_pool.acquire() as conn:
            result = await conn.fetchval("SELECT id FROM core.maps WHERE code = $1", code)

        assert result is None

    async def test_released_code_can_be_reused(self, test_client, create_test_map, asyncpg_pool):
        """After release, a new map can be created with the same code."""
        code = "TREL05"
        old_map_id = await create_test_map(code=code, archived=True)

        await test_client.patch(ENDPOINT.format(code=code))

        # Create a new map with the same code
        new_map_id = await create_test_map(code=code)

        assert new_map_id != old_map_id

        async with asyncpg_pool.acquire() as conn:
            current_id = await conn.fetchval("SELECT id FROM core.maps WHERE code = $1", code)

        assert current_id == new_map_id

    async def test_edit_requests_code_cleared(
        self, test_client, create_test_map, create_test_user, asyncpg_pool
    ):
        """After release, edit_requests.code is set to NULL."""
        code = "TREL06"
        map_id = await create_test_map(code=code, archived=True)
        user_id = await create_test_user()

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

        await test_client.patch(ENDPOINT.format(code=code))

        async with asyncpg_pool.acquire() as conn:
            edit_code = await conn.fetchval("SELECT code FROM maps.edit_requests WHERE id = $1", edit_id)

        assert edit_code is None

    async def test_change_requests_code_cascaded(
        self, test_client, create_test_map, create_test_user, asyncpg_pool
    ):
        """After release, change_requests.code is NULL via ON UPDATE CASCADE."""
        code = "TREL07"
        await create_test_map(code=code, archived=True)
        user_id = await create_test_user()
        thread_id = 900000000000000020

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.change_requests
                    (thread_id, code, user_id, resolved, change_request_type, content, creator_mentions)
                VALUES ($1, $2, $3, TRUE, 'Other', 'test', '0')
                """,
                thread_id,
                code,
                user_id,
            )

        await test_client.patch(ENDPOINT.format(code=code))

        async with asyncpg_pool.acquire() as conn:
            cr_code = await conn.fetchval(
                "SELECT code FROM public.change_requests WHERE thread_id = $1", thread_id
            )

        assert cr_code is None

    async def test_original_code_audit_query(self, test_client, create_test_map, asyncpg_pool):
        """Released map is findable by original_code."""
        code = "TREL08"
        map_id = await create_test_map(code=code, archived=True)

        await test_client.patch(ENDPOINT.format(code=code))

        async with asyncpg_pool.acquire() as conn:
            found_id = await conn.fetchval(
                "SELECT id FROM core.maps WHERE original_code = $1", code
            )

        assert found_id == map_id


class TestReleaseCodeEdgeCases:
    """Edge cases for release-code endpoint."""

    async def test_already_released_returns_404(self, test_client, create_test_map):
        """Releasing an already-released map returns 404 (code is NULL)."""
        code = "TREL09"
        await create_test_map(code=code, archived=True)

        # First release succeeds
        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 204

        # Second release returns 404 (code lookup finds nothing)
        response = await test_client.patch(ENDPOINT.format(code=code))
        assert response.status_code == 404

    async def test_linked_map_auto_unlinks(self, test_client, create_test_map, asyncpg_pool):
        """Releasing a map that another map links to auto-unlinks via cascade."""
        target_code = "TREL10"
        target_id = await create_test_map(code=target_code, archived=True)

        linker_code = "TLNK01"
        linker_id = await create_test_map(code=linker_code)

        # Set up the link
        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE core.maps SET linked_code = $1 WHERE id = $2",
                target_code,
                linker_id,
            )

        # Release the target code
        response = await test_client.patch(ENDPOINT.format(code=target_code))
        assert response.status_code == 204

        # Linker's linked_code should be NULL (cascaded)
        async with asyncpg_pool.acquire() as conn:
            linked = await conn.fetchval("SELECT linked_code FROM core.maps WHERE id = $1", linker_id)

        assert linked is None

    async def test_completions_stay_linked_by_map_id(
        self, test_client, create_test_map, create_test_user, create_test_completion, asyncpg_pool
    ):
        """Completions remain accessible by map_id after code release."""
        code = "TREL11"
        map_id = await create_test_map(code=code, archived=True)
        user_id = await create_test_user()
        comp_id = await create_test_completion(user_id, map_id)

        await test_client.patch(ENDPOINT.format(code=code))

        async with asyncpg_pool.acquire() as conn:
            comp_map_id = await conn.fetchval(
                "SELECT map_id FROM core.completions WHERE id = $1", comp_id
            )

        assert comp_map_id == map_id
