"""Maps domain fixtures."""

from typing import Any

import asyncpg
import msgspec
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_playtest(postgres_service: PostgresService, global_thread_id_tracker: set[int]):
    """Factory fixture for creating test playtest metadata.

    Returns a function that creates a playtest with the given map_id and optional thread_id.

    Usage:
        playtest_id = await create_test_playtest(map_id)
        playtest_id = await create_test_playtest(map_id, thread_id=unique_thread_id)
    """

    async def _create(map_id: int, thread_id: int | None = None, **overrides: Any) -> int:
        # Generate thread_id if not provided
        if thread_id is None:
            while True:
                thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                if thread_id not in global_thread_id_tracker:
                    global_thread_id_tracker.add(thread_id)
                    break

        # Default values
        data = {
            "verification_id": None,
            "initial_difficulty": 5.0,  # Default mid-range difficulty
            "completed": False,
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
                playtest_id = await conn.fetchval(
                    """
                    INSERT INTO playtests.meta (
                        thread_id, map_id, verification_id, initial_difficulty, completed
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    thread_id,
                    map_id,
                    data["verification_id"],
                    data["initial_difficulty"],
                    data["completed"],
                )
            return playtest_id
        finally:
            await pool.close()

    return _create


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
