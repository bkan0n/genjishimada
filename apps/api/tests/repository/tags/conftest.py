"""Tags domain fixtures."""

from typing import Any

import asyncpg
import pytest
from pytest_databases.docker.postgres import PostgresService

GUILD_ID = 100000000000000001


@pytest.fixture
async def create_test_tag(postgres_service: PostgresService):
    """Factory fixture for creating test tags.

    Creates a tag in public.tags and a matching entry in public.tag_lookup
    using a CTE for atomicity.

    Returns a function that creates a tag and returns its ID.

    Usage:
        tag_id = await create_test_tag("my-tag", "tag content", owner_id=123)
        tag_id = await create_test_tag("my-tag", "content", owner_id=123, guild_id=OTHER_GUILD)
    """

    async def _create(
        name: str,
        content: str,
        *,
        owner_id: int,
        guild_id: int = GUILD_ID,
        **overrides: Any,
    ) -> int:
        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                tag_id: int = await conn.fetchval(
                    """
                    WITH new_tag AS (
                        INSERT INTO public.tags (name, content, owner_id, location_id)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                    )
                    INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
                    SELECT $1, $3, $4, id FROM new_tag
                    RETURNING tag_id
                    """,
                    name,
                    content,
                    owner_id,
                    guild_id,
                )
            return tag_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_alias(postgres_service: PostgresService):
    """Factory fixture for creating test tag aliases.

    Creates an alias entry in public.tag_lookup pointing to an existing tag.

    Returns a function that creates an alias and returns the tag_id it points to.

    Usage:
        tag_id = await create_test_alias("alias-name", original_tag_id, owner_id=123)
    """

    async def _create(
        name: str,
        tag_id: int,
        *,
        owner_id: int,
        guild_id: int = GUILD_ID,
    ) -> int:
        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
                    VALUES ($1, $2, $3, $4)
                    """,
                    name,
                    owner_id,
                    guild_id,
                    tag_id,
                )
            return tag_id
        finally:
            await pool.close()

    return _create
