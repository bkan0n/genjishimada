import uuid
from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestJobsEndpoints:
    """Tests for internal job management endpoints."""

    # =========================================================================
    # GET JOB STATUS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_job_pending(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a pending job."""
        job_id = "550e8400-e29b-41d4-a716-446655440001"
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "queued"
        assert data["error_code"] is None
        assert data["error_msg"] is None

    @pytest.mark.asyncio
    async def test_get_job_succeeded(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a succeeded job with result."""
        job_id = "550e8400-e29b-41d4-a716-446655440002"
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "succeeded"
        assert data["error_code"] is None
        assert data["error_msg"] is None

    @pytest.mark.asyncio
    async def test_get_job_failed(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a failed job with error."""
        job_id = "550e8400-e29b-41d4-a716-446655440003"
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == job_id
        assert data["status"] == "failed"
        assert data["error_code"] is not None
        assert data["error_msg"] is not None

    @pytest.mark.asyncio
    async def test_get_job_nonexistent(self, test_client: AsyncTestClient[Litestar]):
        """Test getting a non-existent job returns 404."""
        job_id = "550e8400-e29b-41d4-a716-999999999999"
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        # Expecting 404 or some error response
        assert response.status_code >= 400

    # =========================================================================
    # UPDATE JOB STATUS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_update_job_pending_to_succeeded(self, test_client: AsyncTestClient[Litestar]):
        """Test updating a pending job to succeeded status."""
        job_id = "550e8400-e29b-41d4-a716-446655440001"
        response = await test_client.patch(
            f"/api/v3/internal/jobs/{job_id}",
            json={
                "status": "succeeded",
                "result": {"message": "Updated successfully"},
            },
        )
        assert response.status_code == HTTP_200_OK

        # Verify the update
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        data = response.json()
        assert data["status"] == "succeeded"
        assert data["error_code"] is None
        assert data["error_msg"] is None

    @pytest.mark.asyncio
    async def test_update_job_pending_to_failed(self, test_client: AsyncTestClient[Litestar]):
        """Test updating a pending job to failed status with error."""
        # Create a new pending job first
        new_job_id = str(uuid.uuid4())
        # We need to manually insert a job for this test
        # For now, let's use an existing pending job and check behavior

        job_id = "550e8400-e29b-41d4-a716-446655440001"
        response = await test_client.patch(
            f"/api/v3/internal/jobs/{job_id}",
            json={
                "status": "failed",
                "error_code": "test_error",
                "error_msg": "Test error message",
            },
        )
        assert response.status_code == HTTP_200_OK

        # Verify the update
        response = await test_client.get(f"/api/v3/internal/jobs/{job_id}")
        data = response.json()
        assert data["status"] == "failed"
        assert data["error_code"] == "test_error"
        assert data["error_msg"] == "Test error message"

    # =========================================================================
    # IDEMPOTENCY CLAIM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_claim_new_idempotency_key(self, test_client: AsyncTestClient[Litestar]):
        """Test claiming a new idempotency key returns claimed=true."""
        response = await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "new-unique-claim-key-999"},
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["claimed"] is True

    @pytest.mark.asyncio
    async def test_claim_existing_idempotency_key(self, test_client: AsyncTestClient[Litestar]):
        """Test claiming an existing idempotency key returns claimed=false."""
        response = await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "existing-claim-key-123"},
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["claimed"] is False

    @pytest.mark.asyncio
    async def test_claim_same_key_twice(self, test_client: AsyncTestClient[Litestar]):
        """Test claiming the same key twice in sequence."""
        # First claim
        response = await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "double-claim-test-key"},
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["claimed"] is True

        # Second claim (should be false)
        response = await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "double-claim-test-key"},
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["claimed"] is False

    # =========================================================================
    # DELETE IDEMPOTENCY CLAIM TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_delete_existing_claim(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting an existing idempotency claim."""
        # First create a claim
        await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "claim-to-delete"},
        )

        # Delete it
        response = await test_client.request(
            "DELETE",
            "/api/v3/internal/idempotency/claim",
            json={"key": "claim-to-delete"},
        )
        assert response.status_code == HTTP_204_NO_CONTENT

        # Verify we can claim it again
        response = await test_client.post(
            "/api/v3/internal/idempotency/claim",
            json={"key": "claim-to-delete"},
        )
        data = response.json()
        assert data["claimed"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_claim(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting a non-existent claim doesn't error."""
        response = await test_client.request(
            "DELETE",
            "/api/v3/internal/idempotency/claim",
            json={"key": "never-existed-claim-key"},
        )
        # Should not error
        assert response.status_code == HTTP_204_NO_CONTENT
