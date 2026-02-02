"""Maps domain fixtures."""

from typing import Any

import asyncpg
import msgspec
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_edit_request(postgres_service: PostgresService):
    """Factory fixture for creating test edit requests.

    Returns a function that creates an edit request with the given parameters.

    Usage:
        edit_id = await create_test_edit_request(map_id, code, created_by)
        edit_id = await create_test_edit_request(map_id, code, created_by, reason="Custom reason")
    """

    async def _create(
        map_id: int,
        code: str,
        created_by: int,
        **overrides: Any,
    ) -> int:
        # Default values
        data = {
            "proposed_changes": {"difficulty": "Hard", "checkpoints": 10},
            "reason": fake.sentence(nb_words=10),
        }

        # Apply overrides
        data.update(overrides)

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                edit_id = await conn.fetchval(
                    """
                    INSERT INTO maps.edit_requests (
                        map_id, code, proposed_changes, reason, created_by
                    )
                    VALUES ($1, $2, $3::jsonb, $4, $5)
                    RETURNING id
                    """,
                    map_id,
                    code,
                    msgspec.json.encode(data["proposed_changes"]).decode(),
                    data["reason"],
                    created_by,
                )
            return edit_id
        finally:
            await pool.close()

    return _create
