"""Integration tests for Completions v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

from faker import Faker
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_completions,
]

faker = Faker()


class TestGetCompletionsForUser:
    """GET /api/v3/completions/ with user_id query param"""

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
        await test_client.post("/api/v3/completions/", json=completion_payload)

        response = await test_client.get("/api/v3/completions/", params={"user_id": user_id})

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

    async def test_requires_auth(self, unauthenticated_client, create_test_user):
        """Get completions without auth returns 401."""
        user_id = await create_test_user()

        response = await unauthenticated_client.get(
            "/api/v3/completions/",
            params={"user_id": user_id},
        )

        assert response.status_code == 401

    async def test_difficulty_filter(self, test_client, create_test_user, create_test_map, unique_message_id):
        """Difficulty filter returns only matching difficulty completions."""
        from uuid import uuid4

        user_id = await create_test_user()

        # Create 3 maps with different difficulties using unique codes
        easy_code = f"T{uuid4().hex[:5].upper()}"
        medium_code = f"T{uuid4().hex[:5].upper()}"
        hard_code = f"T{uuid4().hex[:5].upper()}"

        await create_test_map(code=easy_code, difficulty="Easy", checkpoints=10)
        await create_test_map(code=medium_code, difficulty="Medium", checkpoints=10)
        await create_test_map(code=hard_code, difficulty="Hard", checkpoints=10)

        # Submit completions for all 3 maps
        for code in [easy_code, medium_code, hard_code]:
            msg_id = unique_message_id + hash(code) % 1000000
            completion_payload = {
                "user_id": user_id,
                "code": code,
                "time": 45.5,
                "video": "https://youtube.com/watch?v=test",
                "screenshot": "https://example.com/screenshot.png",
                "message_id": msg_id,
            }
            submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
            assert submit_response.status_code == 201

            # Verify each completion so it appears in results
            completion_id = submit_response.json()["completion_id"]
            verify_payload = {"verified": True, "verified_by": user_id, "reason": None}
            await test_client.put(f"/api/v3/completions/{completion_id}/verification", json=verify_payload)

            # Patch with message_id after verification
            patch_payload = {"message_id": msg_id}
            await test_client.patch(f"/api/v3/completions/{completion_id}", json=patch_payload)

        # Query with difficulty filter
        response = await test_client.get("/api/v3/completions/", params={"user_id": user_id, "difficulty": "Medium"})

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should only return Medium difficulty completion
        assert len(data) >= 1
        for completion in data:
            # Verify it's the medium code by checking the code field
            assert completion["code"] == medium_code



class TestGetWorldRecordsPerUser:
    """GET /api/v3/completions/world-records with user_id query param"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get world records for user returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get("/api/v3/completions/world-records", params={"user_id": user_id})

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
            "/api/v3/completions/world-records",
            params={"user_id": user_id},
        )

        assert response.status_code == 401


class TestSubmitCompletion:
    """POST /api/v3/completions/"""

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

        response = await test_client.post("/api/v3/completions/", json=payload)

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

        response = await test_client.post("/api/v3/completions/", json=payload)

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
        response1 = await test_client.post("/api/v3/completions/", json=payload)
        assert response1.status_code == 201

        # Duplicate submission (same user + map, same time) - should return 400
        payload["message_id"] = 987654321
        response2 = await test_client.post("/api/v3/completions/", json=payload)

        assert response2.status_code == 400


class TestGetPendingVerifications:
    """GET /api/v3/completions/pending"""

    async def test_happy_path(self, test_client):
        """Get pending verifications returns list with valid structure."""
        response = await test_client.get("/api/v3/completions/pending")

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
    """GET /api/v3/completions/{code}"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get leaderboard returns list with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v3/completions/{code}")

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
            f"/api/v3/completions/{code}",
        )

        assert response.status_code == 401

    @pytest.mark.parametrize("page_size", [10, 20, 25, 50])
    @pytest.mark.parametrize("page_number", [1, 2])
    async def test_pagination(self, test_client, create_test_map, unique_map_code, page_size, page_number):
        """Leaderboard pagination works."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(
            f"/api/v3/completions/{code}",
            params={"page_size": page_size, "page_number": page_number},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestGetAllCompletions:
    """GET /api/v3/completions/all"""

    async def test_happy_path(self, test_client):
        """Get all completions returns list with valid structure."""
        response = await test_client.get("/api/v3/completions/all")

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


class TestGetSuspiciousFlags:
    """GET /api/v3/completions/suspicious"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get suspicious flags returns list with valid structure."""
        user_id = await create_test_user()

        response = await test_client.get(
            "/api/v3/completions/suspicious",
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
    """PATCH /api/v3/completions/{record_id}"""

    async def test_happy_path(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Edit completion updates fields successfully."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": unique_message_id,
        }
        submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert submit_response.status_code == 201
        completion_id = submit_response.json()["completion_id"]

        # Edit the completion (patch accepts message_id, completion, verification_id, legacy, legacy_medal, wr_xp_check)
        new_message_id = unique_message_id + 1
        edit_payload = {
            "message_id": new_message_id,
            "legacy": False,
        }
        response = await test_client.patch(f"/api/v3/completions/{completion_id}", json=edit_payload)

        assert response.status_code in [200, 204]

    async def test_not_found_returns_404(self, test_client):
        """Edit non-existent completion should return 404."""
        record_id = 999999999

        response = await test_client.patch(
            f"/api/v3/completions/{record_id}",
            json={"time": 30.5},
        )

        assert response.status_code == 404


class TestGetCompletionSubmission:
    """GET /api/v3/completions/{record_id}/submission"""

    async def test_happy_path(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Get completion submission returns enriched details."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": unique_message_id,
        }
        submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert submit_response.status_code == 201
        completion_id = submit_response.json()["completion_id"]

        # Get submission details
        response = await test_client.get(f"/api/v3/completions/{completion_id}/submission")

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "user_id" in data
        assert data["user_id"] == user_id
        assert "code" in data
        assert "time" in data

    async def test_not_found_returns_404(self, test_client):
        """Get non-existent completion submission should return 404."""
        record_id = 999999999

        response = await test_client.get(f"/api/v3/completions/{record_id}/submission")

        assert response.status_code == 404


class TestVerifyCompletion:
    """PUT /api/v3/completions/{record_id}/verification"""

    async def test_happy_path(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Verify completion returns JobStatusResponse."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": unique_message_id,
        }
        submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert submit_response.status_code == 201
        completion_id = submit_response.json()["completion_id"]

        # Verify the completion
        verify_payload = {
            "verified": True,
            "verified_by": user_id,
            "reason": None,
        }
        response = await test_client.put(f"/api/v3/completions/{completion_id}/verification", json=verify_payload)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "status" in data


    async def test_not_found_returns_404(self, test_client):
        """Verify non-existent completion should return 404."""
        record_id = 999999999
        payload = {
            "verified": True,
            "verified_by": 123,
            "reason": None,
        }

        response = await test_client.put(f"/api/v3/completions/{record_id}/verification", json=payload)

        assert response.status_code == 404


class TestSetSuspiciousFlag:
    """POST /api/v3/completions/suspicious"""

    async def test_happy_path(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Set suspicious flag succeeds."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": unique_message_id,
        }
        submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert submit_response.status_code == 201

        # Set suspicious flag
        flag_payload = {
            "message_id": unique_message_id,
            "context": "Suspicious completion time",
            "flag_type": "Cheating",  # Valid values: "Cheating" or "Scripting"
            "flagged_by": user_id,
        }
        response = await test_client.post("/api/v3/completions/suspicious", json=flag_payload)

        assert response.status_code in [200, 201, 204]


    async def test_requires_message_id_or_verification_id(self, test_client):
        """Setting suspicious flag without required fields returns 400."""
        payload = {"reason": "Suspicious activity"}

        response = await test_client.post("/api/v3/completions/suspicious", json=payload)

        assert response.status_code == 400


class TestUpvoteSubmission:
    """POST /api/v3/completions/upvoting"""

    async def test_non_existent_message_returns_404(self, test_client):
        """Upvoting non-existent message should return 404."""
        payload = {"message_id": 999999999, "user_id": 999}

        response = await test_client.post("/api/v3/completions/upvoting", json=payload)

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
        response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert response.status_code == 201
        completion_id = response.json()["completion_id"]

        # Patch the completion to set message_id
        await test_client.patch(
            f"/api/v3/completions/{completion_id}",
            json={"message_id": 123456789},
        )

        upvote_payload = {"message_id": 123456789, "user_id": user_id}

        # First upvote
        response1 = await test_client.post("/api/v3/completions/upvoting", json=upvote_payload)
        assert response1.status_code == 201

        # Duplicate upvote
        response2 = await test_client.post("/api/v3/completions/upvoting", json=upvote_payload)

        assert response2.status_code == 409


class TestCheckWorldRecordXp:
    """GET /api/v3/completions/{code}/wr-xp-check"""

    async def test_returns_boolean(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Check WR XP returns boolean with correct type."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        response = await test_client.get(
            f"/api/v3/completions/{code}/wr-xp-check",
            params={"user_id": user_id},
        )

        assert response.status_code == 200
        result = response.json()
        assert isinstance(result, bool)
        # Should be False for new user with no WR XP history
        assert result is False


class TestGetRecordsFiltered:
    """GET /api/v3/completions/moderation/records"""

    async def test_happy_path(self, test_client):
        """Get filtered records for moderation with valid structure."""
        response = await test_client.get("/api/v3/completions/moderation/records")

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
            "/api/v3/completions/moderation/records",
            params={"verification_status": verification_status, "latest_only": latest_only},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_verification_status_filter(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Verification status filter returns only matching completions."""
        user1 = await create_test_user()
        user2 = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit two completions
        msg_id1 = unique_message_id
        msg_id2 = unique_message_id + 1
        completion_ids = []

        for user, msg_id in [(user1, msg_id1), (user2, msg_id2)]:
            payload = {
                "user_id": user,
                "code": code,
                "time": faker.pyfloat(left_digits=8, right_digits=2),  # Different times to avoid conflicts
                "video": "https://youtube.com/watch?v=test",
                "screenshot": "https://example.com/screenshot.png",
                "message_id": msg_id,
            }
            response = await test_client.post("/api/v3/completions/", json=payload)
            assert response.status_code == 201
            completion_ids.append(response.json()["completion_id"])

        # Verify only the first one
        verify_payload = {"verified": True, "verified_by": user1, "reason": None}
        await test_client.put(f"/api/v3/completions/{completion_ids[0]}/verification", json=verify_payload)

        # Patch with message_id after verification
        patch_payload = {"message_id": msg_id1}
        await test_client.patch(f"/api/v3/completions/{completion_ids[0]}", json=patch_payload)

        # Filter by verified status
        response = await test_client.get(
            "/api/v3/completions/moderation/records",
            params={"code": code, "verification_status": "Verified"},
        )

        assert response.status_code == 200
        data = response.json()
        # Should return at least the verified completion
        verified_ids = [r["id"] for r in data if r.get("verified") is True]
        assert completion_ids[0] in verified_ids

    async def test_code_filter(self, test_client, create_test_user, create_test_map, unique_message_id):
        """Code filter returns only completions for that map."""
        from uuid import uuid4

        user = await create_test_user()

        # Create two maps
        code1 = f"T{uuid4().hex[:5].upper()}"
        code2 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code=code1, checkpoints=10)
        await create_test_map(code=code2, checkpoints=10)

        # Submit completions for both maps
        msg_id1 = unique_message_id
        msg_id2 = unique_message_id + 1

        for code, msg_id in [(code1, msg_id1), (code2, msg_id2)]:
            payload = {
                "user_id": user,
                "code": code,
                "time": 45.5,
                "video": "https://youtube.com/watch?v=test",
                "screenshot": "https://example.com/screenshot.png",
                "message_id": msg_id,
            }
            response = await test_client.post("/api/v3/completions/", json=payload)
            assert response.status_code == 201

        # Filter by specific code
        response = await test_client.get("/api/v3/completions/moderation/records", params={"code": code1})

        assert response.status_code == 200
        data = response.json()
        # All results should be for code1
        for record in data:
            if record["code"] == code1 or record["code"] == code2:
                assert record["code"] == code1

    async def test_user_id_filter(self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id):
        """User ID filter returns only completions for that user."""
        user1 = await create_test_user()
        user2 = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completions from both users
        msg_id1 = unique_message_id
        msg_id2 = unique_message_id + 1

        for user, msg_id in [(user1, msg_id1), (user2, msg_id2)]:
            payload = {
                "user_id": user,
                "code": code,
                "time": faker.pyfloat(left_digits=8, right_digits=2),  # Different times
                "video": "https://youtube.com/watch?v=test",
                "screenshot": "https://example.com/screenshot.png",
                "message_id": msg_id,
            }
            response = await test_client.post("/api/v3/completions/", json=payload)
            assert response.status_code == 201

        # Filter by user1
        response = await test_client.get("/api/v3/completions/moderation/records", params={"user_id": user1})

        assert response.status_code == 200
        data = response.json()
        # All results should be for user1
        for record in data:
            if record["user_id"] in [user1, user2]:
                assert record["user_id"] == user1

    async def test_latest_only_filter(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Latest only filter returns only most recent completion per user+map."""
        user = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit first completion
        msg_id1 = unique_message_id
        payload1 = {
            "user_id": user,
            "code": code,
            "time": 50.0,
            "video": "https://youtube.com/watch?v=test1",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": msg_id1,
        }
        response1 = await test_client.post("/api/v3/completions/", json=payload1)
        assert response1.status_code == 201
        completion_id1 = response1.json()["completion_id"]

        # Verify first completion
        verify_payload = {"verified": True, "verified_by": user, "reason": None}
        await test_client.put(f"/api/v3/completions/{completion_id1}/verification", json=verify_payload)

        # Edit to create a second version (simulates new submission)
        edit_payload = {"time": 45.0}
        await test_client.patch(f"/api/v3/completions/{completion_id1}", json=edit_payload)

        # Filter with latest_only=True should return only one
        response_latest = await test_client.get(
            "/api/v3/completions/moderation/records",
            params={"user_id": user, "code": code, "latest_only": True},
        )

        assert response_latest.status_code == 200
        data_latest = response_latest.json()
        # Should return at most 1 result for this user+map combination
        user_map_records = [r for r in data_latest if r["user_id"] == user and r["code"] == code]
        assert len(user_map_records) <= 1


class TestModerateCompletion:
    """PUT /api/v3/completions/{record_id}/moderate"""

    async def test_happy_path(
        self, test_client, create_test_user, create_test_map, unique_map_code, unique_message_id
    ):
        """Moderate completion succeeds."""
        user_id = await create_test_user()
        moderator_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code, checkpoints=10)

        # Submit completion first
        completion_payload = {
            "user_id": user_id,
            "code": code,
            "time": 45.5,
            "video": "https://youtube.com/watch?v=test",
            "screenshot": "https://example.com/screenshot.png",
            "message_id": unique_message_id,
        }
        submit_response = await test_client.post("/api/v3/completions/", json=completion_payload)
        assert submit_response.status_code == 201
        completion_id = submit_response.json()["completion_id"]

        # Moderate the completion
        moderate_payload = {
            "moderated_by": moderator_id,
            "time": 40.0,
            "time_change_reason": "Corrected timing error",
        }
        response = await test_client.put(f"/api/v3/completions/{completion_id}/moderate", json=moderate_payload)

        assert response.status_code in [200, 204]

    async def test_not_found_returns_404(self, test_client):
        """Moderate non-existent completion should return 404."""
        record_id = 999999999
        payload = {
            "moderated_by": 123,
            "time": 45.0,
        }

        response = await test_client.put(f"/api/v3/completions/{record_id}/moderate", json=payload)

        assert response.status_code == 404


class TestGetLegacyCompletions:
    """GET /api/v3/completions/{code}/legacy"""

    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        """Get legacy completions for a map with valid structure."""
        code = unique_map_code
        await create_test_map(code=code)

        response = await test_client.get(f"/api/v3/completions/{code}/legacy")

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
            f"/api/v3/completions/{code}/legacy",
            params={"page_size": page_size, "page_number": page_number},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestSetQualityVote:
    """POST /api/v3/completions/{code}/quality"""

    async def test_set_quality_vote(self, test_client, create_test_map, create_test_user, unique_map_code):
        """Set quality vote for a map."""
        code = unique_map_code
        user_id = await create_test_user()
        await create_test_map(code=code)

        payload = {"user_id": user_id, "quality": 5}

        response = await test_client.post(f"/api/v3/completions/{code}/quality", json=payload)

        assert response.status_code == 201

    async def test_map_not_found_returns_404(self, test_client, create_test_user):
        """Quality vote for non-existent map should return 404."""
        user_id = await create_test_user()

        payload = {"user_id": user_id, "quality": 5}

        response = await test_client.post("/api/v3/completions/ZZZZZZ/quality", json=payload)

        assert response.status_code == 404

    async def test_duplicate_vote_allows_update(self, test_client, create_test_user, create_test_map, unique_map_code):
        """Duplicate quality vote should update existing vote (upsert behavior)."""
        user_id = await create_test_user()
        code = unique_map_code
        await create_test_map(code=code)

        payload = {"user_id": user_id, "quality": 5}

        # First vote
        response1 = await test_client.post(f"/api/v3/completions/{code}/quality", json=payload)
        assert response1.status_code == 201

        # Duplicate vote (upsert updates existing)
        response2 = await test_client.post(f"/api/v3/completions/{code}/quality", json=payload)

        assert response2.status_code == 201


class TestGetUpvotesFromMessageId:
    """GET /api/v3/completions/upvoting/{message_id}"""

    async def test_returns_integer_count(self, test_client):
        """Get upvote count returns integer with correct type and value."""
        message_id = 123456789

        response = await test_client.get(f"/api/v3/completions/upvoting/{message_id}")

        assert response.status_code == 200
        count = response.json()
        assert isinstance(count, int)
        assert count >= 0  # Count should never be negative
