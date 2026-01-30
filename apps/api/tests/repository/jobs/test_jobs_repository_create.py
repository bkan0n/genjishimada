"""Tests for InternalJobsRepository create operations."""

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


class TestClaimIdempotencyHappyPath:
    """Test happy path scenarios for claim_idempotency."""

    async def test_first_claim_returns_claimed_true(
        self,
        repository: InternalJobsRepository,
        unique_idempotency_key: str,
    ) -> None:
        """Test that first claim of a key returns claimed=True."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

    async def test_duplicate_claim_returns_claimed_false(
        self,
        repository: InternalJobsRepository,
        unique_idempotency_key: str,
    ) -> None:
        """Test that duplicate claim returns claimed=False."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)  # First claim

        # Act
        result = await repository.claim_idempotency(request)  # Duplicate

        # Assert
        assert result.claimed is False
