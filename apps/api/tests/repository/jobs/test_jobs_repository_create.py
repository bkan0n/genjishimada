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

    async def test_claim_after_delete_returns_claimed_true(
        self,
        repository: InternalJobsRepository,
        unique_idempotency_key: str,
    ) -> None:
        """Test that claiming after delete returns claimed=True."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)  # First claim
        await repository.delete_claimed_idempotency(request)  # Delete

        # Act
        result = await repository.claim_idempotency(request)  # Claim again

        # Assert
        assert result.claimed is True

    async def test_multiple_different_keys_all_succeed(
        self,
        repository: InternalJobsRepository,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test that multiple different keys can all be claimed."""
        # Arrange
        keys = [f"idem-{uuid4().hex[:16]}" for _ in range(5)]
        for key in keys:
            global_idempotency_key_tracker.add(key)

        # Act
        results = []
        for key in keys:
            request = ClaimCreateRequest(key=key)
            result = await repository.claim_idempotency(request)
            results.append(result.claimed)

        # Assert
        assert all(results), "All different keys should be claimed successfully"


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestClaimIdempotencyEdgeCases:
    """Test edge cases for claim_idempotency."""

    async def test_claim_with_special_characters(
        self,
        repository: InternalJobsRepository,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test claiming key with special characters."""
        # Arrange
        key = f"idem-special!@#$%^&*()_+-=[]{{}}|;':,.<>?/{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

    async def test_claim_with_unicode_characters(
        self,
        repository: InternalJobsRepository,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test claiming key with unicode characters."""
        # Arrange
        key = f"idem-unicode-你好世界-{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

    async def test_claim_with_very_long_key(
        self,
        repository: InternalJobsRepository,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test claiming key with very long string."""
        # Arrange
        key = f"idem-{'x' * 1000}-{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

    async def test_claim_with_sql_injection_attempt(
        self,
        repository: InternalJobsRepository,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test claiming key with SQL injection attempt is safely handled."""
        # Arrange
        key = f"idem-'; DROP TABLE processed_messages; --{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

        # Verify table still exists by making another claim
        key2 = f"idem-{uuid4().hex[:16]}"
        global_idempotency_key_tracker.add(key2)
        request2 = ClaimCreateRequest(key=key2)
        result2 = await repository.claim_idempotency(request2)
        assert result2.claimed is True


# ==============================================================================
# VERIFICATION TESTS
# ==============================================================================


class TestClaimIdempotencyVerification:
    """Test that claims are actually persisted in database."""

    async def test_claimed_key_exists_in_database(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_idempotency_key: str,
    ) -> None:
        """Test that claimed key is persisted in database."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)

        # Act
        result = await repository.claim_idempotency(request)

        # Assert
        assert result.claimed is True

        # Verify in database
        row = await asyncpg_conn.fetchrow(
            "SELECT idempotency_key, processed_at FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row is not None
        assert row["idempotency_key"] == unique_idempotency_key
        assert row["processed_at"] is not None

    async def test_unclaimed_duplicate_not_in_database_twice(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_idempotency_key: str,
    ) -> None:
        """Test that duplicate claim doesn't create duplicate rows."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)

        # Act
        result = await repository.claim_idempotency(request)
        assert result.claimed is False

        # Assert - Only one row in database
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert count == 1
