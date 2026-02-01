"""Change requests domain fixtures."""

from typing import Any

import asyncpg
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_change_request(postgres_service: PostgresService, global_thread_id_tracker: set[int]):
    """Factory fixture for creating test change requests.

    Returns a function that creates a change request with the given parameters.

    Usage:
        thread_id = await create_test_change_request(map_code, user_id)
        thread_id = await create_test_change_request(map_code, user_id, change_request_type="Bug Fix")
    """

    async def _create(
        code: str,
        user_id: int,
        thread_id: int | None = None,
        content: str | None = None,
        change_request_type: str | None = None,
        creator_mentions: str | None = None,
        **overrides: Any,
    ) -> int:
        # Generate thread_id if not provided
        if thread_id is None:
            while True:
                thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                if thread_id not in global_thread_id_tracker:
                    global_thread_id_tracker.add(thread_id)
                    break

        # Default values
        if content is None:
            content = fake.sentence(nb_words=20)

        if change_request_type is None:
            change_request_type = fake.random_element(
                elements=["Bug Fix", "Feature Request", "Improvement", "Balance Change"]
            )

        if creator_mentions is None:
            creator_mentions = ""

        data = {
            "content": content,
            "change_request_type": change_request_type,
            "creator_mentions": creator_mentions,
            "resolved": False,
            "alerted": False,
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
                await conn.execute(
                    """
                    INSERT INTO change_requests (
                        thread_id, code, user_id, content, change_request_type,
                        creator_mentions, resolved, alerted
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    thread_id,
                    code,
                    user_id,
                    data["content"],
                    data["change_request_type"],
                    data["creator_mentions"],
                    data["resolved"],
                    data["alerted"],
                )
            return thread_id
        finally:
            await pool.close()

    return _create
