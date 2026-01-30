"""Tests for InternalJobsRepository delete operations."""

from uuid import uuid4

import pytest
from faker import Faker
from genjishimada_sdk.internal import ClaimCreateRequest

from repository.jobs_repository import InternalJobsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_jobs,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide jobs repository instance."""
    return InternalJobsRepository(asyncpg_conn)


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestDeleteClaimedIdempotencyHappyPath:
    """Test happy path scenarios for delete_claimed_idempotency."""

    async def test_delete_existing_claim_removes_record(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_idempotency_key: str,
    ) -> None:
        """Test that deleting existing claim removes it from database."""
        # Arrange - Create claim first
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)

        # Verify claim exists
        row_before = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row_before is not None

        # Act
        await repository.delete_claimed_idempotency(request)

        # Assert - Claim should be deleted
        row_after = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row_after is None

    async def test_delete_then_claim_succeeds(
        self,
        repository: InternalJobsRepository,
        unique_idempotency_key: str,
    ) -> None:
        """Test that claiming after delete returns claimed=True."""
        # Arrange - Create and delete claim
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)
        await repository.delete_claimed_idempotency(request)

        # Act - Claim again
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True
