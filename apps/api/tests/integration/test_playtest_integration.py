"""Integration tests for Playtest v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_playtests,
]


class TestGetPlaytest:
    """GET /api/v4/playtests/{thread_id}"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_map,
        create_test_playtest,
    ):
        """Get playtest by thread ID."""
        thread_id = unique_thread_id

        # Create map and playtest
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        response = await test_client.get(f"/api/v4/playtests/{thread_id}")

        assert response.status_code == 200
        data = response.json()

        # Validate response structure
        assert "thread_id" in data
        assert "code" in data
        assert data["thread_id"] == thread_id
        assert isinstance(data["code"], str)

    async def test_not_found_returns_404(self, test_client):
        """Get non-existent playtest returns 404."""
        thread_id = 999999999

        response = await test_client.get(f"/api/v4/playtests/{thread_id}")

        assert response.status_code == 404
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)


class TestCastVote:
    """POST /api/v4/playtests/{thread_id}/vote/{user_id}"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
        create_test_completion,
    ):
        """Cast vote for playtest."""
        thread_id = unique_thread_id
        user_id = await create_test_user()

        # Create map, playtest, and verified completion
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)
        await create_test_completion(user_id, map_id, verified=True, completion=False)

        payload = {
            "difficulty": 5.5,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/vote/{user_id}",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data

    async def test_no_submission_returns_400(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
    ):
        """Cast vote without verified submission returns 400."""
        thread_id = unique_thread_id
        user_id = await create_test_user()

        # Create map and playtest, but NO completion
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        payload = {
            "difficulty": 5.5,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/vote/{user_id}",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 400
        

class TestGetVotes:
    """GET /api/v4/playtests/{thread_id}/votes"""

    async def test_happy_path(self, test_client, unique_thread_id):
        """Get votes for playtest."""
        thread_id = unique_thread_id

        response = await test_client.get(f"/api/v4/playtests/{thread_id}/votes")

        assert response.status_code == 200
        data = response.json()

        # Validate response structure
        assert "votes" in data
        assert "average" in data
        assert isinstance(data["votes"], list)
        assert isinstance(data["average"], (int, float)) or data["average"] is None

        # If there are votes, validate their structure
        if data["votes"]:
            vote = data["votes"][0]
            assert "user_id" in vote
            assert "difficulty" in vote
            assert isinstance(vote["difficulty"], (int, float))


class TestDeleteVote:
    """DELETE /api/v4/playtests/{thread_id}/vote/{user_id}"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
        create_test_vote,
        create_test_completion,
    ):
        """Delete vote for playtest."""
        thread_id = unique_thread_id
        user_id = await create_test_user()

        # Create map, playtest, completion, and vote
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)
        await create_test_completion(user_id, map_id, verified=True, completion=False)
        await create_test_vote(user_id, map_id, thread_id)

        response = await test_client.delete(
            f"/api/v4/playtests/{thread_id}/vote/{user_id}",
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data

    async def test_no_vote_returns_400(self, test_client, unique_thread_id, create_test_user):
        """Delete non-existent vote returns 400."""
        thread_id = unique_thread_id
        user_id = await create_test_user()

        response = await test_client.delete(
            f"/api/v4/playtests/{thread_id}/vote/{user_id}",
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 400
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestDeleteAllVotes:
    """DELETE /api/v4/playtests/{thread_id}/vote"""

    async def test_happy_path(self, test_client, unique_thread_id):
        """Delete all votes for playtest."""
        thread_id = unique_thread_id

        response = await test_client.delete(f"/api/v4/playtests/{thread_id}/vote")

        assert response.status_code == 204


class TestEditPlaytestMeta:
    """PATCH /api/v4/playtests/{thread_id}"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_map,
        create_test_playtest,
    ):
        """Edit playtest metadata."""
        thread_id = unique_thread_id

        # Create map and playtest
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        payload = {
            "verification_id": 123456789,
        }

        response = await test_client.patch(
            f"/api/v4/playtests/{thread_id}",
            json=payload,
        )

        assert response.status_code == 204

    async def test_empty_patch_returns_400(self, test_client, unique_thread_id):
        """Empty patch request returns 400."""
        thread_id = unique_thread_id

        payload = {}

        response = await test_client.patch(
            f"/api/v4/playtests/{thread_id}",
            json=payload,
        )

        assert response.status_code == 400
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestAssociatePlaytestMeta:
    """PATCH /api/v4/playtests/"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_map,
        create_test_playtest,
    ):
        """Associate playtest with thread."""
        thread_id = unique_thread_id

        # Create map and playtest (without thread_id initially)
        map_id = await create_test_map()
        playtest_id = await create_test_playtest(map_id)

        payload = {
            "playtest_id": playtest_id,
            "thread_id": thread_id,
        }

        response = await test_client.patch(
            "/api/v4/playtests/",
            json=payload,
        )

        assert response.status_code == 200
        data = response.json()

        # Validate response structure
        assert "thread_id" in data
        assert "code" in data
        assert data["thread_id"] == thread_id
        assert isinstance(data["code"], str)

    async def test_not_found_returns_404(self, test_client, unique_thread_id):
        """Associate non-existent playtest returns 404."""
        thread_id = unique_thread_id

        payload = {
            "playtest_id": 999999999,
            "thread_id": thread_id,
        }

        response = await test_client.patch(
            "/api/v4/playtests/",
            json=payload,
        )

        assert response.status_code == 404
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestApprovePlaytest:
    """POST /api/v4/playtests/{thread_id}/approve"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
        create_test_vote,
        create_test_completion,
    ):
        """Approve playtest."""
        thread_id = unique_thread_id
        verifier_id = await create_test_user()

        # Create map, playtest, and at least one vote
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        # Create a user with a verified completion and vote for the playtest
        voter_id = await create_test_user()
        await create_test_completion(voter_id, map_id, verified=True, completion=False)
        await create_test_vote(voter_id, map_id, thread_id, difficulty=5.5)

        payload = {
            "verifier_id": verifier_id,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/approve",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()

        # Validate job status response structure
        assert "id" in data
        assert "status" in data
        assert isinstance(data["id"], str)

    async def test_not_found_returns_404(self, test_client, create_test_user):
        """Approve non-existent playtest returns 404."""
        thread_id = 999999999
        verifier_id = await create_test_user()

        payload = {
            "verifier_id": verifier_id,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/approve",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 404
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestForceAcceptPlaytest:
    """POST /api/v4/playtests/{thread_id}/force_accept"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
    ):
        """Force accept playtest."""
        thread_id = unique_thread_id
        verifier_id = await create_test_user()

        # Create map and playtest
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        payload = {
            "difficulty": "Easy -",
            "verifier_id": verifier_id,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/force_accept",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert "status" in data

    async def test_not_found_returns_404(self, test_client, create_test_user):
        """Force accept non-existent playtest returns 404."""
        thread_id = 999999999
        verifier_id = await create_test_user()

        payload = {
            "difficulty": "Easy -",
            "verifier_id": verifier_id,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/force_accept",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 404
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestForceDenyPlaytest:
    """POST /api/v4/playtests/{thread_id}/force_deny"""

    async def test_happy_path(
        self,
        test_client,
        unique_thread_id,
        create_test_user,
        create_test_map,
        create_test_playtest,
    ):
        """Force deny playtest."""
        thread_id = unique_thread_id
        verifier_id = await create_test_user()

        # Create map and playtest
        map_id = await create_test_map()
        await create_test_playtest(map_id, thread_id=thread_id)

        payload = {
            "verifier_id": verifier_id,
            "reason": "Test reason",
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/force_deny",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert "status" in data

    async def test_not_found_returns_404(self, test_client, create_test_user):
        """Force deny non-existent playtest returns 404."""
        thread_id = 999999999
        verifier_id = await create_test_user()

        payload = {
            "verifier_id": verifier_id,
            "reason": "Test reason",
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/force_deny",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 404
        # Validate error response structure
        data = response.json()
        assert isinstance(data, dict)
        

class TestResetPlaytest:
    """POST /api/v4/playtests/{thread_id}/reset"""

    async def test_happy_path(self, test_client, unique_thread_id, create_test_user):
        """Reset playtest."""
        thread_id = unique_thread_id
        verifier_id = await create_test_user()

        payload = {
            "verifier_id": verifier_id,
            "reason": "Test reset",
            "remove_votes": False,
            "remove_completions": False,
        }

        response = await test_client.post(
            f"/api/v4/playtests/{thread_id}/reset",
            json=payload,
            headers={"X-PYTEST-ENABLED": "1"},
        )

        assert response.status_code == 202
        data = response.json()

        # Validate job status response structure
        assert "id" in data
        assert "status" in data
        assert isinstance(data["id"], str)
        assert data["status"] in ("pending", "succeeded", "failed")
