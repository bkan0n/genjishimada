"""Tests for InternalJobsRepository update operations."""

from uuid import uuid4

import pytest
from faker import Faker
from genjishimada_sdk.internal import JobStatusUpdateRequest

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
# HAPPY PATH TESTS - UPDATE TO PROCESSING
# ==============================================================================


class TestUpdateJobToProcessing:
    """Test updating job to processing status."""

    async def test_update_to_processing_sets_started_at(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that updating to processing sets started_at timestamp."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="queued")
        update_data = JobStatusUpdateRequest(status="processing")

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at, finished_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["status"] == "processing"
        assert row["started_at"] is not None
        assert row["finished_at"] is None

    async def test_update_to_processing_preserves_started_at(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that subsequent updates to processing preserve started_at (COALESCE)."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="queued")
        update_data = JobStatusUpdateRequest(status="processing")

        # Act - First update
        await repository.update_job(unique_job_id, update_data)
        first_row = await asyncpg_conn.fetchrow(
            "SELECT started_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        first_started_at = first_row["started_at"]

        # Act - Second update
        await repository.update_job(unique_job_id, update_data)
        second_row = await asyncpg_conn.fetchrow(
            "SELECT started_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        second_started_at = second_row["started_at"]

        # Assert - started_at should be the same
        assert first_started_at == second_started_at


# ==============================================================================
# HAPPY PATH TESTS - UPDATE TO SUCCEEDED
# ==============================================================================


class TestUpdateJobToSucceeded:
    """Test updating job to succeeded status."""

    async def test_update_to_succeeded_sets_finished_at(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that updating to succeeded sets finished_at timestamp."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="processing")
        update_data = JobStatusUpdateRequest(status="succeeded")

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT status::text, finished_at, error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["status"] == "succeeded"
        assert row["finished_at"] is not None
        assert row["error_code"] is None
        assert row["error_msg"] is None

    async def test_update_to_succeeded_clears_error_fields(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that updating to succeeded clears error_code and error_msg."""
        # Arrange - Start with failed job
        await create_test_job(
            job_id=unique_job_id,
            action="test",
            status="failed",
            error_code="PREVIOUS_ERROR",
            error_msg="Previous error message",
        )
        update_data = JobStatusUpdateRequest(status="succeeded")

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["error_code"] is None
        assert row["error_msg"] is None


# ==============================================================================
# HAPPY PATH TESTS - UPDATE TO FAILED
# ==============================================================================


class TestUpdateJobToFailed:
    """Test updating job to failed status."""

    async def test_update_to_failed_sets_all_fields(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that updating to failed sets finished_at, error_code, and error_msg."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="processing")
        error_code = "TEST_ERROR"
        error_msg = "This is a test error"
        update_data = JobStatusUpdateRequest(
            status="failed",
            error_code=error_code,
            error_msg=error_msg,
        )

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT status::text, finished_at, error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["status"] == "failed"
        assert row["finished_at"] is not None
        assert row["error_code"] == error_code
        assert row["error_msg"] == error_msg

    async def test_update_to_failed_with_long_error_message(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test updating to failed with very long error message."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="processing")
        error_msg = fake.text(max_nb_chars=5000)
        update_data = JobStatusUpdateRequest(
            status="failed",
            error_code="LONG_ERROR",
            error_msg=error_msg,
        )

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["error_msg"] == error_msg


# ==============================================================================
# STATUS TRANSITION TESTS
# ==============================================================================


class TestJobStatusTransitions:
    """Test complete job status transition workflows."""

    async def test_full_transition_queued_to_succeeded(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test full workflow: queued -> processing -> succeeded."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="queued")

        # Act - Update to processing
        await repository.update_job(unique_job_id, JobStatusUpdateRequest(status="processing"))
        processing_row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at, finished_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        # Act - Update to succeeded
        await repository.update_job(unique_job_id, JobStatusUpdateRequest(status="succeeded"))
        succeeded_row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at, finished_at, error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        # Assert - Processing state
        assert processing_row["status"] == "processing"
        assert processing_row["started_at"] is not None
        assert processing_row["finished_at"] is None

        # Assert - Succeeded state
        assert succeeded_row["status"] == "succeeded"
        assert succeeded_row["started_at"] is not None  # Preserved
        assert succeeded_row["finished_at"] is not None  # Set
        assert succeeded_row["error_code"] is None
        assert succeeded_row["error_msg"] is None

    async def test_full_transition_queued_to_failed(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test full workflow: queued -> processing -> failed."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="queued")

        # Act - Update to processing
        await repository.update_job(unique_job_id, JobStatusUpdateRequest(status="processing"))

        # Act - Update to failed
        error_code = "WORKFLOW_ERROR"
        error_msg = "Workflow failed"
        await repository.update_job(
            unique_job_id,
            JobStatusUpdateRequest(status="failed", error_code=error_code, error_msg=error_msg),
        )
        failed_row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at, finished_at, error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        # Assert
        assert failed_row["status"] == "failed"
        assert failed_row["started_at"] is not None  # Preserved from processing
        assert failed_row["finished_at"] is not None  # Set on failed
        assert failed_row["error_code"] == error_code
        assert failed_row["error_msg"] == error_msg


# ==============================================================================
# IDEMPOTENCY TESTS
# ==============================================================================


class TestUpdateJobIdempotency:
    """Test idempotency of update operations."""

    async def test_multiple_updates_to_same_status_idempotent(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that multiple updates to same status are idempotent."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="queued")
        update_data = JobStatusUpdateRequest(status="processing")

        # Act - Update three times
        await repository.update_job(unique_job_id, update_data)
        first_row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        await repository.update_job(unique_job_id, update_data)
        await repository.update_job(unique_job_id, update_data)
        final_row = await asyncpg_conn.fetchrow(
            "SELECT status::text, started_at FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        # Assert - Status and started_at should remain the same
        assert first_row["status"] == final_row["status"] == "processing"
        assert first_row["started_at"] == final_row["started_at"]


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestUpdateJobEdgeCases:
    """Test edge cases for update_job."""

    async def test_update_nonexistent_job_silent_failure(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        unique_job_id,
    ) -> None:
        """Test that updating non-existent job doesn't raise error (silent failure)."""
        # Arrange
        update_data = JobStatusUpdateRequest(status="processing")

        # Act - Should not raise exception
        await repository.update_job(unique_job_id, update_data)

        # Assert - Job still doesn't exist
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row is None

    async def test_update_with_special_characters_in_error(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test updating with special characters in error fields."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="processing")
        error_msg = "Error with special chars: <>&\"'`\n\t\r"
        update_data = JobStatusUpdateRequest(
            status="failed",
            error_code="SPECIAL_CHARS",
            error_msg=error_msg,
        )

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["error_msg"] == error_msg

    async def test_update_with_unicode_in_error(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test updating with unicode characters in error fields."""
        # Arrange
        await create_test_job(job_id=unique_job_id, action="test", status="processing")
        error_msg = "错误消息：作业失败 🚨"
        update_data = JobStatusUpdateRequest(
            status="failed",
            error_code="UNICODE_ERROR",
            error_msg=error_msg,
        )

        # Act
        await repository.update_job(unique_job_id, update_data)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )
        assert row["error_msg"] == error_msg


# ==============================================================================
# VERIFICATION TESTS
# ==============================================================================


class TestUpdateJobVerification:
    """Test that updates modify database correctly."""

    async def test_update_only_affects_target_job(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        global_job_id_tracker,
    ) -> None:
        """Test that update only modifies the target job, not others."""
        # Arrange - Create two jobs
        job_id_1 = uuid4()
        job_id_2 = uuid4()
        global_job_id_tracker.add(job_id_1)
        global_job_id_tracker.add(job_id_2)
        await create_test_job(job_id=job_id_1, action="test1", status="queued")
        await create_test_job(job_id=job_id_2, action="test2", status="queued")

        # Act - Update only job_id_1
        await repository.update_job(job_id_1, JobStatusUpdateRequest(status="processing"))

        # Assert
        row1 = await asyncpg_conn.fetchrow(
            "SELECT status::text FROM public.jobs WHERE id=$1", job_id_1
        )
        row2 = await asyncpg_conn.fetchrow(
            "SELECT status::text FROM public.jobs WHERE id=$1", job_id_2
        )

        assert row1["status"] == "processing"
        assert row2["status"] == "queued"  # Unchanged
