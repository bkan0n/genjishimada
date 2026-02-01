"""Jobs domain fixtures."""

import uuid
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


@pytest.fixture
async def create_test_job(postgres_service: PostgresService, global_job_id_tracker: set):
    """Factory fixture for creating test jobs.

    Returns a function that creates a job with optional parameters.

    Usage:
        job_id = await create_test_job()
        job_id = await create_test_job(action="test_action", status="processing")
    """

    async def _create(
        job_id: Any | None = None,
        action: str | None = None,
        status: str = "queued",
        error_code: str | None = None,
        error_msg: str | None = None,
        **overrides: Any,
    ):
        # Generate job_id if not provided
        if job_id is None:
            job_id = uuid.uuid4()
            global_job_id_tracker.add(job_id)

        # Generate action if not provided
        if action is None:
            action = fake.word()

        data = {
            "action": action,
            "status": status,
            "error_code": error_code,
            "error_msg": error_msg,
            "attempts": 0,
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
                    INSERT INTO public.jobs (
                        id, action, status, error_code, error_msg, attempts
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    job_id,
                    data["action"],
                    data["status"],
                    data["error_code"],
                    data["error_msg"],
                    data["attempts"],
                )
            return job_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_claim(postgres_service: PostgresService, global_idempotency_key_tracker: set[str]):
    """Factory fixture for creating test idempotency claims.

    Returns a function that creates an idempotency claim.

    Usage:
        key = await create_test_claim()
        key = await create_test_claim(key="custom-key")
    """

    async def _create(key: str | None = None) -> str:
        # Generate key if not provided
        if key is None:
            key = f"idem-{uuid4().hex[:16]}"
            global_idempotency_key_tracker.add(key)

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
                    INSERT INTO public.processed_messages (idempotency_key)
                    VALUES ($1)
                    """,
                    key,
                )
            return key
        finally:
            await pool.close()

    return _create


@pytest.fixture
def unique_job_id(global_job_id_tracker: set):
    """Generate a unique job ID (UUID) guaranteed not to collide.

    Uses UUID v4 for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: UUID (e.g., "550e8400-e29b-41d4-a716-446655440000")
    """
    job_id = uuid.uuid4()
    global_job_id_tracker.add(job_id)
    return job_id


@pytest.fixture
def unique_idempotency_key(global_idempotency_key_tracker: set[str]) -> str:
    """Generate a unique idempotency key guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: idem-{16 lowercase hex chars} (e.g., "idem-a1b2c3d4e5f6g7h8")
    """
    key = f"idem-{uuid4().hex[:16]}"
    global_idempotency_key_tracker.add(key)
    return key
