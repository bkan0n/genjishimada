"""Tests for InternalJobsRepository read operations."""

from uuid import uuid4

import pytest
from faker import Faker
from litestar.exceptions import HTTPException

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


class TestGetJobHappyPath:
    """Test happy path scenarios for get_job."""

    async def test_get_job_returns_correct_status(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that get_job returns job with correct status."""
        # Arrange
        action = "test_action"
        await create_test_job(job_id=unique_job_id, action=action, status="queued")

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.id == unique_job_id
        assert result.status == "queued"
        assert result.error_code is None
        assert result.error_msg is None

    @pytest.mark.parametrize(
        "status",
        ["queued", "processing", "succeeded", "failed", "timeout"],
    )
    async def test_get_job_all_statuses(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        status: str,
    ) -> None:
        """Test getting jobs with all possible status values."""
        # Arrange
        job_id = uuid4()
        await create_test_job(job_id=job_id, action="test_action", status=status)

        # Act
        result = await repository.get_job(job_id)

        # Assert
        assert result.status == status

    async def test_get_job_with_error_fields_populated(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test getting job with error_code and error_msg populated."""
        # Arrange
        error_code = "TEST_ERROR"
        error_msg = "This is a test error message"
        await create_test_job(
            job_id=unique_job_id,
            action="test_action",
            status="failed",
            error_code=error_code,
            error_msg=error_msg,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.id == unique_job_id
        assert result.status == "failed"
        assert result.error_code == error_code
        assert result.error_msg == error_msg

    async def test_get_job_without_error_fields(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test getting job with NULL error_code and error_msg."""
        # Arrange
        await create_test_job(
            job_id=unique_job_id,
            action="test_action",
            status="succeeded",
            error_code=None,
            error_msg=None,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.id == unique_job_id
        assert result.status == "succeeded"
        assert result.error_code is None
        assert result.error_msg is None


# ==============================================================================
# ERROR CASE TESTS
# ==============================================================================


class TestGetJobErrorCases:
    """Test error handling for get_job."""

    async def test_get_nonexistent_job_raises_exception(
        self,
        repository: InternalJobsRepository,
        unique_job_id,
    ) -> None:
        """Test that getting non-existent job raises HTTPException.

        NOTE: There's a bug in the repository where HTTPException is called
        incorrectly with positional args instead of keyword args. This causes
        status_code to be 500 instead of 404. Expected fix:
        Change: raise HTTPException(404, "Job not found.")
        To: raise HTTPException(status_code=404, detail="Job not found.")
        """
        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await repository.get_job(unique_job_id)

        # Currently returns 500 due to bug, should be 404
        assert exc_info.value.status_code == 404
        # Detail is "404" (first positional arg) instead of "Job not found." (second arg)
        assert str(exc_info.value.detail) == "Job not found."

    async def test_get_random_uuid_raises_exception(
        self,
        repository: InternalJobsRepository,
    ) -> None:
        """Test that getting job with random UUID raises HTTPException.

        NOTE: See bug note in test_get_nonexistent_job_raises_exception.
        """
        # Arrange
        random_uuid = uuid4()

        # Act & Assert
        with pytest.raises(HTTPException) as exc_info:
            await repository.get_job(random_uuid)

        # Currently returns 500 due to bug, should be 404
        assert exc_info.value.status_code == 404


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestGetJobEdgeCases:
    """Test edge cases for get_job."""

    async def test_get_job_with_long_error_message(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test getting job with very long error message."""
        # Arrange
        error_msg = fake.text(max_nb_chars=5000)
        await create_test_job(
            job_id=unique_job_id,
            action="test_action",
            status="failed",
            error_code="LONG_ERROR",
            error_msg=error_msg,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.error_msg == error_msg

    async def test_get_job_with_special_characters_in_error(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test getting job with special characters in error fields."""
        # Arrange
        error_code = "ERROR_WITH_SPECIAL!@#$%^&*()"
        error_msg = "Error with special chars: <>&\"'`\n\t\r"
        await create_test_job(
            job_id=unique_job_id,
            action="test_action",
            status="failed",
            error_code=error_code,
            error_msg=error_msg,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.error_code == error_code
        assert result.error_msg == error_msg

    async def test_get_job_with_unicode_in_error(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test getting job with unicode characters in error fields."""
        # Arrange
        error_code = "ERROR_UNICODE"
        error_msg = "错误消息：这是一个包含中文的错误 🚨"
        await create_test_job(
            job_id=unique_job_id,
            action="test_action",
            status="failed",
            error_code=error_code,
            error_msg=error_msg,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.error_msg == error_msg


# ==============================================================================
# VERIFICATION TESTS
# ==============================================================================


class TestGetJobVerification:
    """Test that get_job returns data matching database."""

    async def test_get_job_matches_database(
        self,
        repository: InternalJobsRepository,
        asyncpg_conn,
        create_test_job,
        unique_job_id,
    ) -> None:
        """Test that get_job returns data exactly as stored in database."""
        # Arrange
        action = "test_action"
        status = "processing"
        error_code = "TEST_CODE"
        error_msg = "Test message"
        await create_test_job(
            job_id=unique_job_id,
            action=action,
            status=status,
            error_code=error_code,
            error_msg=error_msg,
        )

        # Get from database directly
        db_row = await asyncpg_conn.fetchrow(
            "SELECT id, status::text, error_code, error_msg FROM public.jobs WHERE id=$1",
            unique_job_id,
        )

        # Act
        result = await repository.get_job(unique_job_id)

        # Assert
        assert result.id == db_row["id"]
        assert result.status == db_row["status"]
        assert result.error_code == db_row["error_code"]
        assert result.error_msg == db_row["error_msg"]

    async def test_get_multiple_different_jobs(
        self,
        repository: InternalJobsRepository,
        create_test_job,
        global_job_id_tracker,
    ) -> None:
        """Test getting multiple different jobs returns correct data for each."""
        # Arrange
        jobs_data = []
        for i in range(5):
            job_id = uuid4()
            global_job_id_tracker.add(job_id)
            status = fake.random_element(["queued", "processing", "succeeded", "failed"])
            await create_test_job(job_id=job_id, action=f"action_{i}", status=status)
            jobs_data.append((job_id, status))

        # Act & Assert
        for job_id, expected_status in jobs_data:
            result = await repository.get_job(job_id)
            assert result.id == job_id
            assert result.status == expected_status
