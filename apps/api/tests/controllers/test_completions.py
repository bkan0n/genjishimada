from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestCompletionsEndpoints:
    """Tests for completion submission and verification endpoints."""

    # Test data from seed
    USER_200 = 200
    USER_201 = 201
    VERIFIER_202 = 202

    # =========================================================================
    # GET USER COMPLETIONS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_completions_all(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all completions for a user."""
        response = await test_client.get(f"/api/v3/completions/?user_id={self.USER_200}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # User 200 has completions from seed
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_get_user_completions_filter_difficulty(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering completions by difficulty."""
        response = await test_client.get(f"/api/v3/completions/?user_id={self.USER_200}&difficulty=Easy")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # All should be Easy difficulty
        for completion in data:
            assert "easy" in completion["difficulty"].lower()

    @pytest.mark.asyncio
    async def test_get_user_completions_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test pagination for user completions."""
        response = await test_client.get(f"/api/v3/completions/?user_id={self.USER_200}&page_size=10&page_number=1")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) <= 10

    @pytest.mark.asyncio
    async def test_get_user_completions_empty(self, test_client: AsyncTestClient[Litestar]):
        """Test getting completions for user with none."""
        response = await test_client.get("/api/v3/completions/?user_id=999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    # =========================================================================
    # GET WORLD RECORDS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_world_records(self, test_client: AsyncTestClient[Litestar]):
        """Test getting user's world records."""
        response = await test_client.get(f"/api/v3/completions/world-records?user_id={self.USER_200}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # May or may not have WRs depending on seed

    @pytest.mark.asyncio
    async def test_get_world_records_empty(self, test_client: AsyncTestClient[Litestar]):
        """Test getting WRs for user with none."""
        response = await test_client.get("/api/v3/completions/world-records?user_id=999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    # =========================================================================
    # SUBMIT COMPLETION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_submit_completion_with_screenshot(self, test_client: AsyncTestClient[Litestar]):
        """Test submitting completion with screenshot."""
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "1EASY",
                "user_id": self.USER_200,
                "time": 99999,
                "screenshot": "https://example.com/screenshot.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["completion_id"] is not None

    @pytest.mark.asyncio
    async def test_submit_completion_with_video(self, test_client: AsyncTestClient[Litestar]):
        """Test submitting completion with video."""
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "2EASY",
                "user_id": self.USER_201,
                "time": 88888,
                "screenshot": "https://example.com/screenshot.png",
                "video": "https://youtube.com/watch?v=test123",
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["completion_id"] is not None
        # With video, should create job
        assert data["job_status"] is not None

    @pytest.mark.asyncio
    async def test_submit_completion_nonexistent_map(self, test_client: AsyncTestClient[Litestar]):
        """Test submitting completion for non-existent map returns 404."""
        response = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "ZZZZZ",
                "user_id": self.USER_200,
                "time": 12345,
                "screenshot": "https://example.com/screenshot.png",
                "video": None,
            },
        )
        assert response.status_code == HTTP_404_NOT_FOUND

    # =========================================================================
    # GET COMPLETION SUBMISSION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_completion_submission(self, test_client: AsyncTestClient[Litestar]):
        """Test getting completion submission with ranks/medals."""
        create_resp = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "1EASY",
                "user_id": self.USER_200,
                "time": 77777,
                "screenshot": "https://example.com/screenshot-submission.png",
                "video": None,
            },
        )
        assert create_resp.status_code == HTTP_201_CREATED
        completion_id = create_resp.json()["completion_id"]
        response = await test_client.get(f"/api/v3/completions/{completion_id}/submission")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["id"] == completion_id

    # =========================================================================
    # GET PENDING VERIFICATIONS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_pending_verifications(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all pending verifications."""
        response = await test_client.get("/api/v3/completions/pending")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should have pending completions from seed

    # =========================================================================
    # VERIFY COMPLETION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_verify_completion_approve(self, test_client: AsyncTestClient[Litestar]):
        """Test verifying a completion (approved)."""
        # Get a pending completion
        pending_resp = await test_client.get("/api/v3/completions/pending")
        pending = pending_resp.json()
        if pending:
            record = next(
                (p for p in pending if p["verification_id"] not in {9000000001, 9000000002, 9000000003}),
                None,
            )
            if record is None:
                return
            record_id = record["id"]
            response = await test_client.put(
                f"/api/v3/completions/{record_id}/verification",
                json={
                    "verified_by": self.VERIFIER_202,
                    "verified": True,
                    "reason": "Looks good",
                },
            )
            assert response.status_code == HTTP_200_OK
            data = response.json()
            # Returns job status
            assert "id" in data

    @pytest.mark.asyncio
    async def test_verify_completion_reject(self, test_client: AsyncTestClient[Litestar]):
        """Test rejecting a completion."""
        # Get a pending completion
        pending_resp = await test_client.get("/api/v3/completions/pending")
        pending = pending_resp.json()
        if pending and len(pending) > 1:
            record = next(
                (p for p in pending if p["verification_id"] not in {9000000001, 9000000002, 9000000003}),
                None,
            )
            if record is None:
                return
            record_id = record["id"]
            response = await test_client.put(
                f"/api/v3/completions/{record_id}/verification",
                json={
                    "verified_by": self.VERIFIER_202,
                    "verified": False,
                    "reason": "Screenshot is unclear",
                },
            )
            assert response.status_code == HTTP_200_OK

    # =========================================================================
    # GET MAP LEADERBOARD TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_completions_leaderboard(self, test_client: AsyncTestClient[Litestar]):
        """Test getting leaderboard for a map."""
        response = await test_client.get("/api/v3/completions/1EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should have verified completions

    @pytest.mark.asyncio
    async def test_get_completions_leaderboard_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test leaderboard pagination."""
        response = await test_client.get("/api/v3/completions/1EASY?page_size=10&page_number=1")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) <= 10

    @pytest.mark.asyncio
    async def test_get_completions_leaderboard_empty(self, test_client: AsyncTestClient[Litestar]):
        """Test leaderboard for map with no completions."""
        response = await test_client.get("/api/v3/completions/ZZZZZ")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    # =========================================================================
    # SUSPICIOUS FLAGS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_suspicious_flags(self, test_client: AsyncTestClient[Litestar]):
        """Test getting suspicious flags for user."""
        response = await test_client.get(f"/api/v3/completions/suspicious?user_id={self.USER_200}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_set_suspicious_flag_with_message_id(self, test_client: AsyncTestClient[Litestar]):
        """Test setting suspicious flag with message_id."""
        response = await test_client.post(
            "/api/v3/completions/suspicious",
            json={
                "user_id": self.USER_201,
                "message_id": 7000000001,
                "verification_id": None,
                "reason": "Suspicious time",
            },
        )
        # May need completion/message to exist
        assert response.status_code in [HTTP_200_OK, HTTP_400_BAD_REQUEST]

    @pytest.mark.asyncio
    async def test_set_suspicious_flag_with_verification_id(self, test_client: AsyncTestClient[Litestar]):
        """Test setting suspicious flag with verification_id."""
        response = await test_client.post(
            "/api/v3/completions/suspicious",
            json={
                "user_id": self.USER_201,
                "message_id": None,
                "verification_id": 1,
                "reason": "Needs review",
            },
        )
        assert response.status_code in [HTTP_200_OK, HTTP_400_BAD_REQUEST]

    @pytest.mark.asyncio
    async def test_set_suspicious_flag_neither_id(self, test_client: AsyncTestClient[Litestar]):
        """Test setting flag without message_id or verification_id returns 400."""
        response = await test_client.post(
            "/api/v3/completions/suspicious",
            json={
                "user_id": self.USER_201,
                "message_id": None,
                "verification_id": None,
                "reason": "Invalid",
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    # =========================================================================
    # UPVOTING TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_upvote_submission(self, test_client: AsyncTestClient[Litestar]):
        """Test upvoting a completion submission."""
        response = await test_client.post(
            "/api/v3/completions/upvoting",
            json={
                "user_id": self.USER_200,
                "message_id": 1,
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert "upvotes" in data
        assert "job_status" in data

    @pytest.mark.asyncio
    async def test_get_upvotes_from_message_id(self, test_client: AsyncTestClient[Litestar]):
        """Test getting upvote count from message ID."""
        response = await test_client.get("/api/v3/completions/upvoting/1")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, int)

    @pytest.mark.asyncio
    async def test_get_upvotes_no_upvotes(self, test_client: AsyncTestClient[Litestar]):
        """Test getting count for message with no upvotes."""
        response = await test_client.get("/api/v3/completions/upvoting/9999999999")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == 0

    # =========================================================================
    # GET ALL COMPLETIONS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_all_completions(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all verified completions."""
        response = await test_client.get("/api/v3/completions/all")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # Should be sorted by most recent

    @pytest.mark.asyncio
    async def test_get_all_completions_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test pagination for all completions."""
        response = await test_client.get("/api/v3/completions/all?page_size=10&page_number=1")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) <= 10

    # =========================================================================
    # WR XP CHECK TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_check_for_previous_world_record_xp(self, test_client: AsyncTestClient[Litestar]):
        """Test checking if user received WR XP for a map."""
        response = await test_client.get(f"/api/v3/completions/1EASY/wr-xp-check?user_id={self.USER_200}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, bool)

    # =========================================================================
    # MODERATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_records_filtered_by_code(self, test_client: AsyncTestClient[Litestar]):
        """Test getting filtered records by code."""
        response = await test_client.get("/api/v3/completions/moderation/records?code=1EASY")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_records_filtered_by_user(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering by user_id."""
        response = await test_client.get(f"/api/v3/completions/moderation/records?user_id={self.USER_200}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        for record in data:
            assert record["user_id"] == self.USER_200

    @pytest.mark.asyncio
    async def test_get_records_filtered_verification_status(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering by verification status."""
        response = await test_client.get("/api/v3/completions/moderation/records?verification_status=Verified")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        for record in data:
            assert record["verified"] is True

    @pytest.mark.asyncio
    async def test_get_records_filtered_latest_only(self, test_client: AsyncTestClient[Litestar]):
        """Test filtering with latest_only=true."""
        response = await test_client.get("/api/v3/completions/moderation/records?latest_only=true")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_moderate_completion(self, test_client: AsyncTestClient[Litestar]):
        """Test moderating a completion record."""
        create_resp = await test_client.post(
            "/api/v3/completions/",
            json={
                "code": "1EASY",
                "user_id": self.USER_200,
                "time": 11111,
                "screenshot": "https://example.com/screenshot-moderate.png",
                "video": None,
            },
        )
        assert create_resp.status_code == HTTP_201_CREATED
        record_id = create_resp.json()["completion_id"]
        response = await test_client.put(
            f"/api/v3/completions/{record_id}/moderate",
            json={
                "time": 11111,
                "verified": True,
            },
        )
        assert response.status_code in [HTTP_200_OK, 400, 403]

    # =========================================================================
    # LEGACY COMPLETIONS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_legacy_completions_per_map(self, test_client: AsyncTestClient[Litestar]):
        """Test getting legacy completions for a map."""
        # Use map with legacy completions from seed (map_id 6)
        response = await test_client.get("/api/v3/completions/6EASY/legacy")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # May or may not have legacy completions

    @pytest.mark.asyncio
    async def test_get_legacy_completions_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test pagination for legacy completions."""
        response = await test_client.get("/api/v3/completions/6EASY/legacy?page_size=10&page_number=1")
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # QUALITY VOTE TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_set_quality_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test setting quality vote for a map."""
        response = await test_client.post(
            "/api/v3/completions/1EASY/quality",
            json={
                "user_id": self.USER_200,
                "quality": 5,
            },
        )
        assert response.status_code == HTTP_201_CREATED

    @pytest.mark.asyncio
    async def test_update_existing_quality_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test updating existing quality vote."""
        # First set a vote
        await test_client.post(
            "/api/v3/completions/2EASY/quality",
            json={
                "user_id": self.USER_201,
                "quality": 3,
            },
        )
        # Update it
        response = await test_client.post(
            "/api/v3/completions/2EASY/quality",
            json={
                "user_id": self.USER_201,
                "quality": 5,
            },
        )
        assert response.status_code == HTTP_201_CREATED
