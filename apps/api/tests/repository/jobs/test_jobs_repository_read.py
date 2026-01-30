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
