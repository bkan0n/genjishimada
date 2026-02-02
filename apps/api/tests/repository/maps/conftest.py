"""Maps domain fixtures."""

from typing import Any

import msgspec
import pytest
from faker import Faker

import asyncpg

fake = Faker()


@pytest.fixture
def create_test_edit_request(asyncpg_pool: asyncpg.Pool):
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

        async with asyncpg_pool.acquire() as conn:
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

    return _create
