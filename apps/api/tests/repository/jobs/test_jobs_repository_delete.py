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

    async def test_delete_multiple_times_idempotent(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_idempotency_key: str,
    ) -> None:
        """Test that deleting multiple times is idempotent (no error)."""
        # Arrange - Create claim
        request = ClaimCreateRequest(key=unique_idempotency_key)
        await repository.claim_idempotency(request)

        # Act - Delete three times
        await repository.delete_claimed_idempotency(request)
        await repository.delete_claimed_idempotency(request)
        await repository.delete_claimed_idempotency(request)

        # Assert - Should not raise error, claim should not exist
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row is None

    async def test_delete_nonexistent_claim_silent(
        self,
        repository: InternalJobsRepository,
        unique_idempotency_key: str,
    ) -> None:
        """Test that deleting non-existent claim doesn't raise error (silent)."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)

        # Act - Should not raise exception
        await repository.delete_claimed_idempotency(request)

        # Assert - Passes if no exception raised


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestDeleteClaimedIdempotencyEdgeCases:
    """Test edge cases for delete_claimed_idempotency."""

    async def test_delete_with_special_characters(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test deleting claim with special characters in key."""
        # Arrange
        key = f"idem-special!@#$%^&*()_+-=[]{{}}|;':,.<>?/{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)
        await repository.claim_idempotency(request)

        # Act
        await repository.delete_claimed_idempotency(request)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key,
        )
        assert row is None

    async def test_delete_with_unicode_characters(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test deleting claim with unicode characters in key."""
        # Arrange
        key = f"idem-unicode-你好世界-{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)
        await repository.claim_idempotency(request)

        # Act
        await repository.delete_claimed_idempotency(request)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key,
        )
        assert row is None

    async def test_delete_with_very_long_key(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test deleting claim with very long key."""
        # Arrange
        key = f"idem-{'x' * 1000}-{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)
        await repository.claim_idempotency(request)

        # Act
        await repository.delete_claimed_idempotency(request)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key,
        )
        assert row is None

    async def test_delete_with_sql_injection_attempt(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test deleting claim with SQL injection attempt is safely handled."""
        # Arrange
        key = f"idem-'; DELETE FROM processed_messages; --{uuid4().hex[:8]}"
        global_idempotency_key_tracker.add(key)
        request = ClaimCreateRequest(key=key)
        await repository.claim_idempotency(request)

        # Act
        await repository.delete_claimed_idempotency(request)

        # Assert - This claim should be deleted
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key,
        )
        assert row is None

        # Verify table still exists by creating another claim
        key2 = f"idem-{uuid4().hex[:16]}"
        global_idempotency_key_tracker.add(key2)
        request2 = ClaimCreateRequest(key=key2)
        result = await repository.claim_idempotency(request2)
        assert result.claimed is True


# ==============================================================================
# VERIFICATION TESTS
# ==============================================================================


class TestDeleteClaimedIdempotencyVerification:
    """Test that deletes work correctly and don't affect other data."""

    async def test_delete_only_affects_target_claim(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test that delete only removes target claim, not others."""
        # Arrange - Create two claims
        key1 = f"idem-{uuid4().hex[:16]}"
        key2 = f"idem-{uuid4().hex[:16]}"
        global_idempotency_key_tracker.add(key1)
        global_idempotency_key_tracker.add(key2)

        request1 = ClaimCreateRequest(key=key1)
        request2 = ClaimCreateRequest(key=key2)
        await repository.claim_idempotency(request1)
        await repository.claim_idempotency(request2)

        # Act - Delete only key1
        await repository.delete_claimed_idempotency(request1)

        # Assert
        row1 = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key1,
        )
        row2 = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            key2,
        )

        assert row1 is None  # Deleted
        assert row2 is not None  # Still exists

    async def test_delete_count_verification(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        global_idempotency_key_tracker: set[str],
    ) -> None:
        """Test that delete actually removes records from database."""
        # Arrange - Create multiple claims
        keys = [f"idem-{uuid4().hex[:16]}" for _ in range(5)]
        for key in keys:
            global_idempotency_key_tracker.add(key)
            await repository.claim_idempotency(ClaimCreateRequest(key=key))

        # Get initial count
        count_before = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM public.processed_messages WHERE idempotency_key = ANY($1::text[])",
            keys,
        )
        assert count_before == 5

        # Act - Delete first 3 claims
        for key in keys[:3]:
            await repository.delete_claimed_idempotency(ClaimCreateRequest(key=key))

        # Assert
        count_after = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM public.processed_messages WHERE idempotency_key = ANY($1::text[])",
            keys,
        )
        assert count_after == 2  # Only 2 remaining

    async def test_full_claim_lifecycle(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_idempotency_key: str,
    ) -> None:
        """Test complete lifecycle: claim -> delete -> claim again."""
        # Arrange
        request = ClaimCreateRequest(key=unique_idempotency_key)

        # Act & Assert - First claim
        result1 = await repository.claim_idempotency(request)
        assert result1.claimed is True
        row1 = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row1 is not None

        # Act & Assert - Delete
        await repository.delete_claimed_idempotency(request)
        row2 = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row2 is None

        # Act & Assert - Claim again
        result2 = await repository.claim_idempotency(request)
        assert result2.claimed is True
        row3 = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.processed_messages WHERE idempotency_key = $1",
            unique_idempotency_key,
        )
        assert row3 is not None
