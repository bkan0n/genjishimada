"""Integration tests for Completions v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_completions,
]


class TestGetCompletionsForUser:
    """GET /api/v4/completions/ with user_id query param"""

    async def test_happy_path(self, test_client, create_test_user, create_test_map, unique_map_code):
        """Get completions for user returns list with valid structure."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit a completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }
        await test_client.post("/api/v4/completions/", json=completion_payload)

        response = await test_client.get("/api/v4/completions/", params={"user_id": user_id})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate response structure if completions exist
        if data:
            completion = data[0]
            assert "id" in completion
            assert "user_id" in completion
            assert completion["user_id"] == user_id
            assert "code" in completion
            assert "time" in completion
            assert isinstance(completion["time"], (int, float))
            assert "created_at" in completion

    async def test_requires_auth(self, unauthenticated_client, create_test_user):
        """Get completions without auth returns 401."""
        user_id = await create_test_user()

        response = await unauthenticated_client.get(
            "/api/v4/completions/",
            params={"user_id": user_id},
        )

        assert response.status_code == 401


class TestGetWorldRecordsPerUser:
    """GET /api/v4/completions/world-records with user_id query param"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get world records for user returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get("/api/v4/completions/world-records", params={"user_id": user_id})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate response structure (list of CompletionResponse)
        for record in data:
            assert "id" in record
            assert "user_id" in record
            assert "code" in record
            assert "time" in record
            assert isinstance(record["time"], (int, float))

    async def test_requires_auth(self, unauthenticated_client, create_test_user):
        """Get world records without auth returns 401."""
        user_id = await create_test_user()

        response = await unauthenticated_client.get(
            "/api/v4/completions/world-records",
            params={"user_id": user_id},
        )

        assert response.status_code == 401


class TestSubmitCompletion:
    """POST /api/v4/completions/"""

    async def test_happy_path(self, test_client, create_test_user, create_test_map, unique_map_code):
        """Submit completion creates record."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }

        response = await test_client.post("/api/v4/completions/", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert "completion_id" in data
        assert "job_status" in data

    async def test_map_not_found_returns_404(self, test_client, create_test_user):
        """Submit completion for non-existent map should return 404."""
        user_id = await create_test_user()

        payload = {
            "user_id": user_id,
            "code": "ZZZZZZ",  # Valid length, but non-existent map
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }

        response = await test_client.post("/api/v4/completions/", json=payload)

        assert response.status_code == 404

    async def test_duplicate_completion_returns_400(
        self, test_client, create_test_user, create_test_map, unique_map_code
    ):
        """Submit duplicate completion with same time should return 400 (SlowerThanPendingError)."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }

        # First submission
        response1 = await test_client.post("/api/v4/completions/", json=payload)
        assert response1.status_code == 201

        # Duplicate submission (same user + map, same time) - should return 400
        payload["message_id"] = 987654321
        response2 = await test_client.post("/api/v4/completions/", json=payload)

        assert response2.status_code == 400


class TestGetPendingVerifications:
    """GET /api/v4/completions/pending"""

    async def test_happy_path(self, test_client):
        """Get pending verifications returns list with valid structure."""
        response = await test_client.get("/api/v4/completions/pending")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate pending verification entries if any exist
        for verification in data:
            assert "id" in verification
            assert "user_id" in verification
            assert "code" in verification
            assert "time" in verification
            assert isinstance(verification["time"], (int, float))
            assert "message_id" in verification
            assert "created_at" in verification


class TestGetCompletionsLeaderboard:
    """GET /api/v4/completions/{code}"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get leaderboard returns list with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v4/completions/{code}")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate leaderboard entries if any exist
        for entry in data:
            assert "id" in entry
            assert "user_id" in entry
            assert "code" in entry
            assert entry["code"] == code
            assert "time" in entry
            assert isinstance(entry["time"], (int, float))
            assert "created_at" in entry

    async def test_requires_auth(self, unauthenticated_client, create_test_map, unique_map_code):
        """Get leaderboard without auth returns 401."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await unauthenticated_client.get(
            f"/api/v4/completions/{code}",
        )

        assert response.status_code == 401

    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    @pytest.mark.parametrize("page_number", [1, 2])
    async def test_pagination(self, test_client, create_test_map, unique_map_code, page_size, page_number):
        """Leaderboard pagination works."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(
            f"/api/v4/completions/{code}",
            params={"page_size": page_size, "page_number": page_number},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestGetAllCompletions:
    """GET /api/v4/completions/all"""

    async def test_happy_path(self, test_client):
        """Get all completions returns list with valid structure."""
        response = await test_client.get("/api/v4/completions/all")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate completion entries if any exist
        for completion in data:
            assert "id" in completion
            assert "user_id" in completion
            assert "code" in completion
            assert "time" in completion
            assert isinstance(completion["time"], (int, float))
            assert "verified" in completion
            assert "created_at" in completion


class TestGetSuspiciousFlags:
    """GET /api/v4/completions/suspicious"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get suspicious flags returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get(
            "/api/v4/completions/suspicious",
            params={"user_id": user_id},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate suspicious flag entries if any exist
        for flag in data:
            assert "verification_id" in flag
            assert "message_id" in flag
            assert "reason" in flag
            assert "created_at" in flag


class TestEditCompletion:
    """PATCH /api/v4/completions/{record_id}"""

    async def test_not_found_returns_404(self, test_client):
        """Edit non-existent completion should return 404."""
        record_id = 999999999

        response = await test_client.patch(
            f"/api/v4/completions/{record_id}",
            json={"time": 30.5},
        )

        assert response.status_code == 404


class TestGetCompletionSubmission:
    """GET /api/v4/completions/{record_id}/submission"""

    async def test_not_found_returns_404(self, test_client):
        """Get non-existent completion submission should return 404."""
        record_id = 999999999

        response = await test_client.get(f"/api/v4/completions/{record_id}/submission")

        assert response.status_code == 404


class TestVerifyCompletion:
    """PUT /api/v4/completions/{record_id}/verification"""

    async def test_not_found_returns_404(self, test_client):
        """Verify non-existent completion should return 404."""
        record_id = 999999999
        payload = {
            "verified": True,
            "verified_by": 123,
            "reason": None,
        }

        response = await test_client.put(f"/api/v4/completions/{record_id}/verification", json=payload)

        assert response.status_code == 404


class TestSetSuspiciousFlag:
    """POST /api/v4/completions/suspicious"""

    async def test_requires_message_id_or_verification_id(self, test_client):
        """Setting suspicious flag without required fields returns 400."""
        payload = {"reason": "Suspicious activity"}

        response = await test_client.post("/api/v4/completions/suspicious", json=payload)

        assert response.status_code == 400


class TestUpvoteSubmission:
    """POST /api/v4/completions/upvoting"""

    async def test_non_existent_message_returns_404(self, test_client):
        """Upvoting non-existent message should return 404."""
        payload = {"message_id": 999999999, "user_id": 999}

        response = await test_client.post("/api/v4/completions/upvoting", json=payload)

        assert response.status_code == 404

    async def test_duplicate_upvote_returns_409(
        self, test_client, create_test_user, create_test_map, unique_map_code
    ):
        """Duplicate upvote should return 409."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit a completion
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": 123456789,
        }
        response = await test_client.post("/api/v4/completions/", json=completion_payload)
        assert response.status_code == 201
        completion_id = response.json()["completion_id"]

        # Patch the completion to set message_id
        await test_client.patch(
            f"/api/v4/completions/{completion_id}",
            json={"message_id": 123456789},
        )

        upvote_payload = {"message_id": 123456789, "user_id": user_id}

        # First upvote
        response1 = await test_client.post("/api/v4/completions/upvoting", json=upvote_payload)
        assert response1.status_code == 201

        # Duplicate upvote
        response2 = await test_client.post("/api/v4/completions/upvoting", json=upvote_payload)

        assert response2.status_code == 409


class TestCheckWorldRecordXp:
    """GET /api/v4/completions/{code}/wr-xp-check"""

    async def test_returns_boolean(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Check WR XP returns boolean with correct type."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        response = await test_client.get(
            f"/api/v4/completions/{code}/wr-xp-check",
            params={"user_id": user_id},
        )

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        # Should be False for new user with no WR XP history
        assert result is False


class TestGetRecordsFiltered:
    """GET /api/v4/completions/moderation/records"""

    async def test_happy_path(self, test_client):
        """Get filtered records for moderation with valid structure."""
        response = await test_client.get("/api/v4/completions/moderation/records")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate moderation record entries if any exist
        for record in data:
            assert "id" in record
            assert "user_id" in record
            assert "code" in record
            assert "time" in record
            assert isinstance(record["time"], (int, float))
            assert "verified" in record
            assert isinstance(record["verified"], bool)

    @pytest.mark.parametrize("verification_status", ["Verified", "Unverified", "All"])
    @pytest.mark.parametrize("latest_only", [True, False])
    async def test_filter_combinations(self, test_client, verification_status, latest_only):
        """Test various filter combinations."""
        response = await test_client.get(
            "/api/v4/completions/moderation/records",
            params={"verification_status": verification_status, "latest_only": latest_only},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestModerateCompletion:
    """PUT /api/v4/completions/{record_id}/moderate"""

    async def test_not_found_returns_404(self, test_client):
        """Moderate non-existent completion should return 404."""
        record_id = 999999999
        payload = {
            "moderated_by": 123,
            "time": 45.0,
        }

        response = await test_client.put(f"/api/v4/completions/{record_id}/moderate", json=payload)

        assert response.status_code == 404


class TestGetLegacyCompletions:
    """GET /api/v4/completions/{code}/legacy"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get legacy completions for a map with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v4/completions/{code}/legacy")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Validate legacy completion entries if any exist
        for completion in data:
            assert "id" in completion
            assert "user_id" in completion
            assert "code" in completion
            assert completion["code"] == code
            assert "time" in completion
            assert isinstance(completion["time"], (int, float))

    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    @pytest.mark.parametrize("page_number", [1, 2])
    async def test_pagination(self, test_client, create_test_map, unique_map_code, page_size, page_number):
        """Test pagination parameters."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(
            f"/api/v4/completions/{code}/legacy",
            params={"page_size": page_size, "page_number": page_number},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestSetQualityVote:
    """POST /api/v4/completions/{code}/quality"""

    async def test_set_quality_vote(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Set quality vote for a map."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        payload = {"user_id": user_id, "quality": 5}

        response = await test_client.post(f"/api/v4/completions/{code}/quality", json=payload)

        assert response.status_code == 201

    async def test_map_not_found_returns_404(self, test_client, create_test_user):
        """Quality vote for non-existent map should return 404."""
        user_id = await create_test_user()

        payload = {"user_id": user_id, "quality": 5}

        response = await test_client.post("/api/v4/completions/ZZZZZZ/quality", json=payload)

        assert response.status_code == 404

    async def test_duplicate_vote_allows_update(self, test_client, create_test_user, create_test_map, unique_map_code):
        """Duplicate quality vote should update existing vote (upsert behavior)."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)

        payload = {"user_id": user_id, "quality": 5}

        # First vote
        response1 = await test_client.post(f"/api/v4/completions/{code}/quality", json=payload)
        assert response1.status_code == 201

        # Duplicate vote (upsert updates existing)
        response2 = await test_client.post(f"/api/v4/completions/{code}/quality", json=payload)

        assert response2.status_code == 201


class TestGetUpvotesFromMessageId:
    """GET /api/v4/completions/upvoting/{message_id}"""

    async def test_returns_integer_count(self, test_client):
        """Get upvote count returns integer with correct type and value."""
        message_id = 123456789

        response = await test_client.get(f"/api/v4/completions/upvoting/{message_id}")

        assert response.status_code == 200
        count = response.json()
        assert isinstance(count, int)
        assert count >= 0  # Count should never be negative
