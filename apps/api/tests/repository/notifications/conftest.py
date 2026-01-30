"""Notifications domain fixtures."""

import json
from typing import Any

import asyncpg
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_notification_event(postgres_service: PostgresService, global_user_id_tracker: set[int]):
    """Factory fixture for creating test notification events.

    Returns a function that creates a notification event with optional parameters.

    Usage:
        event_id = await create_test_notification_event(user_id)
        event_id = await create_test_notification_event(user_id, event_type="test_event", metadata={"key": "value"})
    """

    async def _create(
        user_id: int | None = None,
        event_type: str | None = None,
        title: str | None = None,
        body: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        # Generate user_id if not provided
        if user_id is None:
            while True:
                user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                if user_id not in global_user_id_tracker:
                    global_user_id_tracker.add(user_id)
                    break

            # Create user if we generated a new ID
            pool_for_user = await asyncpg.create_pool(
                user=postgres_service.user,
                password=postgres_service.password,
                host=postgres_service.host,
                port=postgres_service.port,
                database=postgres_service.database,
            )
            try:
                async with pool_for_user.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO core.users (id, nickname, global_name)
                        VALUES ($1, $2, $3)
                        """,
                        user_id,
                        fake.user_name(),
                        fake.user_name(),
                    )
            finally:
                await pool_for_user.close()

        # Generate defaults if not provided
        if event_type is None:
            event_type = fake.word()

        if title is None:
            title = fake.sentence(nb_words=5)

        if body is None:
            body = fake.sentence(nb_words=15)

        # metadata can be None or a dict
        metadata_json = json.dumps(metadata) if metadata is not None else None

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                event_id = await conn.fetchval(
                    """
                    INSERT INTO notifications.events (user_id, event_type, title, body, metadata)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    RETURNING id
                    """,
                    user_id,
                    event_type,
                    title,
                    body,
                    metadata_json,
                )
            return event_id
        finally:
            await pool.close()

    return _create
