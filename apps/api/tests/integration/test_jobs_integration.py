"""Integration tests for Jobs (Internal) v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_jobs,
]


class TestGetJob:
    """GET /api/v4/internal/jobs/{job_id}"""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Get job returns status with valid structure."""
        # Create test job directly in database
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status)
            VALUES ($1, $2, $3)
            """,
            job_id,
            "test-action",
            "queued",
        )

        response = await test_client.get(f"/api/v4/internal/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        # Validate response structure
        assert "id" in data
        assert "status" in data
        assert "error_code" in data
        assert "error_msg" in data
        # Validate field types and values
        assert data["id"] == str(job_id)
        assert isinstance(data["status"], str)
        assert data["status"] == "queued"
        assert data["error_code"] is None
        assert data["error_msg"] is None

    async def test_requires_auth(self, unauthenticated_client):
        """Get job without auth returns 401."""
        job_id = uuid.uuid4()
        response = await unauthenticated_client.get(f"/api/v4/internal/jobs/{job_id}")

        assert response.status_code == 401

    async def test_not_found_returns_404(self, test_client):
        """Get non-existent job returns 404."""
        # Use valid UUID that doesn't exist in database
        job_id = uuid.uuid4()
        response = await test_client.get(f"/api/v4/internal/jobs/{job_id}")

        assert response.status_code == 404

    async def test_invalid_uuid_returns_400(self, test_client):
        """Get job with invalid UUID format returns 400."""
        response = await test_client.get("/api/v4/internal/jobs/not-a-uuid")

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "status",
        ["processing", "succeeded", "failed", "timeout", "queued"],
    )
    async def test_all_status_values_serialize(self, test_client, asyncpg_conn, status):
        """All status enum values serialize correctly in responses."""
        # Create test job with specific status
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status)
            VALUES ($1, $2, $3)
            """,
            job_id,
            "test-action",
            status,
        )

        response = await test_client.get(f"/api/v4/internal/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == status
        assert isinstance(data["status"], str)

    async def test_failed_job_with_error_info(self, test_client, asyncpg_conn):
        """Get failed job returns error_code and error_msg."""
        # Create failed job with error information
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status, error_code, error_msg)
            VALUES ($1, $2, $3, $4, $5)
            """,
            job_id,
            "test-action",
            "failed",
            "PROCESSING_ERROR",
            "Job failed due to invalid input",
        )

        response = await test_client.get(f"/api/v4/internal/jobs/{job_id}")

        assert response.status_code == 200
        data = response.json()
        # Validate complete response structure with error info
        assert data["id"] == str(job_id)
        assert data["status"] == "failed"
        assert data["error_code"] == "PROCESSING_ERROR"
        assert data["error_msg"] == "Job failed due to invalid input"
        assert isinstance(data["error_code"], str)
        assert isinstance(data["error_msg"], str)


class TestUpdateJob:
    """PATCH /api/v4/internal/jobs/{job_id}"""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Update job status returns 200."""
        # Create test job
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status)
            VALUES ($1, $2, $3)
            """,
            job_id,
            "test-action",
            "queued",
        )

        payload = {
            "status": "processing",
        }

        response = await test_client.patch(f"/api/v4/internal/jobs/{job_id}", json=payload)

        assert response.status_code == 200

    async def test_requires_auth(self, unauthenticated_client):
        """Update job without auth returns 401."""
        job_id = uuid.uuid4()
        payload = {"status": "processing"}
        response = await unauthenticated_client.patch(f"/api/v4/internal/jobs/{job_id}", json=payload)

        assert response.status_code == 401

    async def test_invalid_status_returns_400(self, test_client, asyncpg_conn):
        """Update job with invalid status enum value returns 400."""
        # Create test job
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status)
            VALUES ($1, $2, $3)
            """,
            job_id,
            "test-action",
            "queued",
        )

        payload = {"status": "invalid_status"}
        response = await test_client.patch(f"/api/v4/internal/jobs/{job_id}", json=payload)

        assert response.status_code == 400

    @pytest.mark.parametrize(
        "status",
        ["processing", "succeeded", "failed", "timeout", "queued"],
    )
    async def test_all_status_values(self, test_client, asyncpg_conn, status):
        """All status enum values work correctly."""
        # Create test job
        job_id = uuid.uuid4()
        await asyncpg_conn.execute(
            """
            INSERT INTO public.jobs (id, action, status)
            VALUES ($1, $2, $3)
            """,
            job_id,
            "test-action",
            "queued",
        )

        payload = {"status": status}
        response = await test_client.patch(f"/api/v4/internal/jobs/{job_id}", json=payload)

        assert response.status_code == 200


class TestClaimIdempotency:
    """POST /api/v4/internal/idempotency/claim"""

    async def test_happy_path(self, test_client):
        """Claim idempotency key returns claimed=True on first claim."""
        payload = {"key": f"test-key-{uuid.uuid4()}"}

        response = await test_client.post("/api/v4/internal/idempotency/claim", json=payload)

        assert response.status_code == 201
        data = response.json()
        # Validate response structure
        assert "claimed" in data
        assert isinstance(data["claimed"], bool)
        assert data["claimed"] is True

    async def test_requires_auth(self, unauthenticated_client):
        """Claim idempotency without auth returns 401."""
        payload = {"key": f"test-key-{uuid.uuid4()}"}
        response = await unauthenticated_client.post("/api/v4/internal/idempotency/claim", json=payload)

        assert response.status_code == 401

    async def test_duplicate_claim_returns_claimed_false(self, test_client):
        """Claiming same key twice returns claimed=False on second attempt."""
        key = f"test-key-{uuid.uuid4()}"
        payload = {"key": key}

        # First claim
        response1 = await test_client.post("/api/v4/internal/idempotency/claim", json=payload)
        assert response1.status_code == 201
        data1 = response1.json()
        assert data1["claimed"] is True

        # Second claim (duplicate)
        response2 = await test_client.post("/api/v4/internal/idempotency/claim", json=payload)
        assert response2.status_code == 201
        data2 = response2.json()
        assert data2["claimed"] is False


class TestDeleteClaimedIdempotency:
    """DELETE /api/v4/internal/idempotency/claim"""

    async def test_happy_path(self, test_client, asyncpg_conn):
        """Delete claimed idempotency key returns 204."""
        # Create claimed key
        key = f"test-key-{uuid.uuid4()}"
        await asyncpg_conn.execute(
            """
            INSERT INTO public.processed_messages (idempotency_key)
            VALUES ($1)
            """,
            key,
        )

        payload = {"key": key}

        # Use request() method for DELETE with body
        response = await test_client.request("DELETE", "/api/v4/internal/idempotency/claim", json=payload)

        assert response.status_code == 204

    async def test_requires_auth(self, unauthenticated_client):
        """Delete idempotency without auth returns 401."""
        payload = {"key": f"test-key-{uuid.uuid4()}"}
        response = await unauthenticated_client.request("DELETE", "/api/v4/internal/idempotency/claim", json=payload)

        assert response.status_code == 401
