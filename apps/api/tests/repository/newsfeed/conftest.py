"""Newsfeed domain fixtures."""

import datetime as dt
import json
from typing import Any

import asyncpg
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_newsfeed_event(postgres_service: PostgresService):
    """Factory fixture for creating test newsfeed events.

    Returns a function that creates a newsfeed event with optional parameters.

    Usage:
        event_id = await create_test_newsfeed_event()
        event_id = await create_test_newsfeed_event(payload={"type": "custom", "data": "value"})
    """

    async def _create(
        timestamp: Any | None = None,
        payload: dict | None = None,
    ) -> int:
        # Generate timestamp if not provided
        if timestamp is None:
            timestamp = dt.datetime.now(dt.timezone.utc)

        # Generate payload if not provided
        if payload is None:
            payload = {
                "type": fake.word(),
                "data": fake.sentence(),
            }

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
                    INSERT INTO public.newsfeed (timestamp, payload)
                    VALUES ($1, $2::jsonb)
                    RETURNING id
                    """,
                    timestamp,
                    json.dumps(payload),
                )
            return event_id
        finally:
            await pool.close()

    return _create
