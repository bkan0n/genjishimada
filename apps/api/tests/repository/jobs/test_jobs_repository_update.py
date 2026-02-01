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


