"""Tests for pending verification handling logic.

Tests the behavior when users submit completions while they have
pending (unverified) submissions in the verification queue.
"""

from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_201_CREATED, HTTP_400_BAD_REQUEST
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestPendingVerificationHandling:
    """Tests for pending verification duplicate submission prevention."""

    # Test users from 0018-pending_verification_handling_seed.sql
    USER_600 = 600  # Has pending on map 7 with time 100.5, verification_id set
    USER_601 = 601  # Has pending on map 8 with time 200.75, verification_id set
    USER_602 = 602  # Has pending on map 9 with time 150.25, NO verification_id
    BOT_USER_ID = 969632729643753482

    # =========================================================================
    # BASELINE: Normal submission when no pending exists
    # =========================================================================

    @pytest.mark.asyncio
    async def test_submit_completion_no_pending_verification(self, test_client: AsyncTestClient[Litestar]):
        """Test normal submission when user has no pending verification."""
        # User 300 has no pending on map 1EASY
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "1EASY",
                "user_id": self.USER_600,
                "time": 45000,  # Faster than their verified time of 50000
                "screenshot": "https://example.com/test_no_pending.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["completion_id"] is not None

    # =========================================================================
    # REJECTION: Same time as pending
    # =========================================================================

    @pytest.mark.asyncio
    async def test_submit_same_time_as_pending_rejected(
        self, test_client: AsyncTestClient[Litestar], asyncpg_conn
    ):
        """Test that submitting same time as pending verification is rejected."""
        # Verify pending completion exists in database
        pending = await asyncpg_conn.fetchrow(
            """
            SELECT c.id, c.time, c.verified, c.verified_by
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE c.user_id = $1
              AND m.code = $2
            """,
            self.USER_600,
            "7EASY",
        )
        assert pending is not None, "Seed data: User 600 should have a completion on map 7EASY"
        assert pending["time"] == 100.5, f"Expected time 100.5, got {pending['time']}"
        assert pending["verified"] is False, "Completion should be unverified"
        assert pending["verified_by"] is None, "Completion should have no verifier"

        # User 600 has pending on map 7 (7EASY) with time 100.5
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "7EASY",
                "user_id": self.USER_600,
                "time": 100.5,  # Same as pending
                "screenshot": "https://example.com/test_same_time.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
        error_response = response.json()
        # Error might be in 'detail' or 'message' depending on exception format
        error_detail = error_response.get("detail") or error_response.get("message") or str(error_response)
        # Verify error message mentions pending verification
        assert "pending verification" in error_detail.lower()
        assert "100.5" in error_detail  # Should mention the pending time
        assert "must be faster" in error_detail.lower()

    # =========================================================================
    # REJECTION: Slower time than pending
    # =========================================================================

    @pytest.mark.asyncio
    async def test_submit_slower_time_than_pending_rejected(self, test_client: AsyncTestClient[Litestar]):
        """Test that submitting slower time than pending verification is rejected."""
        # User 300 has pending on map 7 (7EASY) with time 100.5
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "7EASY",
                "user_id": self.USER_600,
                "time": 150.0,  # Slower than pending 100.5
                "screenshot": "https://example.com/test_slower_time.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
        error_response = response.json()
        error_detail = error_response.get("detail") or error_response.get("message") or str(error_response)
        # Verify error message is clear about the issue
        assert "pending verification" in error_detail.lower()
        assert "100.5" in error_detail  # Pending time
        assert "150" in error_detail  # New time
        assert "must be faster" in error_detail.lower()

    # =========================================================================
    # ACCEPTANCE: Faster time replaces pending
    # =========================================================================

    @pytest.mark.asyncio
    async def test_submit_faster_time_replaces_pending(
        self, test_client: AsyncTestClient[Litestar], asyncpg_conn
    ):
        """Test that submitting faster time replaces pending verification."""
        # User 301 has pending on map 8 (8EASY) with time 200.75
        old_pending_time = 200.75
        new_faster_time = 150.0

        # Get the old pending completion ID before submission
        old_pending = await asyncpg_conn.fetchrow(
            """
            SELECT c.id, c.time, c.verification_id
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE c.user_id = $1
              AND m.code = $2
              AND c.verified IS FALSE
              AND c.verified_by IS NULL
            """,
            self.USER_601,
            "8EASY",
        )
        assert old_pending is not None
        assert old_pending["time"] == old_pending_time
        old_pending_id = old_pending["id"]
        old_verification_id = old_pending["verification_id"]

        # Submit faster time
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "8EASY",
                "user_id": self.USER_601,
                "time": new_faster_time,
                "screenshot": "https://example.com/test_faster_time.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        new_completion_id = data["completion_id"]
        assert new_completion_id is not None
        assert new_completion_id != old_pending_id  # Should be a new row

        # Verify old pending was marked as rejected by bot
        old_completion = await asyncpg_conn.fetchrow(
            "SELECT verified, verified_by FROM core.completions WHERE id = $1",
            old_pending_id,
        )
        assert old_completion["verified"] is False
        assert old_completion["verified_by"] == self.BOT_USER_ID

        # Verify new completion exists and is pending
        new_completion = await asyncpg_conn.fetchrow(
            "SELECT time, verified, verified_by FROM core.completions WHERE id = $1",
            new_completion_id,
        )
        assert new_completion["time"] == new_faster_time
        assert new_completion["verified"] is False
        assert new_completion["verified_by"] is None  # Still pending verification

    # =========================================================================
    # VERIFICATION ID HANDLING: Delete event should be published
    # =========================================================================

    @pytest.mark.asyncio
    async def test_faster_time_with_verification_id_present(
        self, test_client: AsyncTestClient[Litestar], asyncpg_conn
    ):
        """Test that verification_id is handled when replacing pending with faster time."""
        # User 600 has another pending on map 5 (6EASY) with verification_id = 9000000003
        # (We can't easily test the actual message deletion event in unit tests
        # since X-PYTEST-ENABLED=1 skips queue publishing, but we can verify
        # the old completion was rejected which would trigger the delete)

        # Get the old pending completion's verification_id
        old_pending = await asyncpg_conn.fetchrow(
            """
            SELECT c.id, c.verification_id
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE c.user_id = $1
              AND m.code = $2
              AND c.verified IS FALSE
              AND c.verified_by IS NULL
            """,
            self.USER_600,
            "6EASY",
        )
        assert old_pending is not None
        assert old_pending["verification_id"] is not None
        old_verification_id = old_pending["verification_id"]

        # Submit faster time
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "6EASY",
                "user_id": self.USER_600,
                "time": 200.0,  # Much faster than 300.5
                "screenshot": "https://example.com/test_verification_id.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_201_CREATED

        # Verify the old pending still has its verification_id
        # (it's not deleted from the database, just marked as rejected)
        old_completion = await asyncpg_conn.fetchrow(
            "SELECT verification_id, verified_by FROM core.completions WHERE id = $1",
            old_pending["id"],
        )
        assert old_completion["verification_id"] == old_verification_id
        assert old_completion["verified_by"] == self.BOT_USER_ID

    # =========================================================================
    # EDGE CASE: Pending without verification_id
    # =========================================================================

    @pytest.mark.asyncio
    async def test_faster_time_no_verification_id(
        self, test_client: AsyncTestClient[Litestar], asyncpg_conn
    ):
        """Test replacing pending that has no verification_id (edge case)."""
        # User 302 has pending on map 9 with NO verification_id
        # This tests that the code handles None verification_id gracefully

        # Submit faster time
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "9EASY",
                "user_id": self.USER_602,
                "time": 100.0,  # Faster than 150.25
                "screenshot": "https://example.com/test_no_verification_id.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["completion_id"] is not None

        # Verify old pending was still marked as rejected even without verification_id
        old_pending = await asyncpg_conn.fetchrow(
            """
            SELECT id, verified_by
            FROM core.completions
            WHERE user_id = $1
              AND map_id = 8
              AND time = 150.25
            """,
            self.USER_602,
        )
        assert old_pending["verified_by"] == self.BOT_USER_ID

    # =========================================================================
    # MULTIPLE SUBMISSIONS: Only fastest pending matters
    # =========================================================================

    @pytest.mark.asyncio
    async def test_multiple_pending_only_fastest_matters(
        self, test_client: AsyncTestClient[Litestar], asyncpg_conn
    ):
        """Test that when multiple pending exist, only the fastest is considered."""
        # Create a scenario with multiple pending completions
        # First, submit a completion for user 300 on a new map (map 10)
        first_response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "10EASY",
                "user_id": self.USER_600,
                "time": 300.0,
                "screenshot": "https://example.com/first.png",
                "video": None,
            },
        )
        assert first_response.status_code == HTTP_201_CREATED

        # Now try to submit a slower time - should be rejected against the 300.0 pending
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "10EASY",
                "user_id": self.USER_600,
                "time": 350.0,
                "screenshot": "https://example.com/second_slower.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
        error_response = response.json()
        error_detail = error_response.get("detail") or error_response.get("message") or str(error_response)
        assert "300" in error_detail  # Should reference the 300.0 time

        # Try to submit a faster time - should succeed and mark 300.0 as rejected
        faster_response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "10EASY",
                "user_id": self.USER_600,
                "time": 250.0,
                "screenshot": "https://example.com/third_faster.png",
                "video": None,
            },
        )
        assert faster_response.status_code == HTTP_201_CREATED

        # Verify the 300.0 submission was marked as rejected
        pending_300 = await asyncpg_conn.fetchrow(
            """
            SELECT verified_by
            FROM core.completions
            WHERE user_id = $1
              AND map_id = 9
              AND time = 300.0
            """,
            self.USER_600,
        )
        assert pending_300["verified_by"] == self.BOT_USER_ID
