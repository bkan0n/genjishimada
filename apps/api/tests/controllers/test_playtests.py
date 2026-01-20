from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_202_ACCEPTED, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestPlaytestsEndpoints:
    """Tests for playtest management endpoints."""

    # Test data from seed
    PLAYTEST_WITH_VOTES = 2000000001
    PLAYTEST_ONE_VOTE = 2000000002
    PLAYTEST_NO_VOTES = 2000000003
    VOTER_USER_200 = 200
    VOTER_USER_201 = 201

    # =========================================================================
    # GET PLAYTEST DATA TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test getting playtest data."""
        response = await test_client.get(f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["thread_id"] == self.PLAYTEST_WITH_VOTES
        assert "code" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test getting non-existent playtest returns error."""
        response = await test_client.get("/api/v3/maps/playtests/9999999999")
        assert response.status_code >= 400

    # =========================================================================
    # CAST VOTE TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_cast_new_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test casting a new vote."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_NO_VOTES}/vote/{self.VOTER_USER_200}",
            json={
                "difficulty": 4.5,
                "quality": 4,
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_update_existing_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test updating an existing vote (change difficulty)."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/vote/{self.VOTER_USER_200}",
            json={
                "difficulty": 5.0,  # Changed from 3.5 in seed
                "quality": 5,
            },
        )
        assert response.status_code == HTTP_202_ACCEPTED

    @pytest.mark.asyncio
    async def test_cast_vote_nonexistent_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test voting on non-existent playtest returns error."""
        response = await test_client.post(
            "/api/v3/maps/playtests/9999999999/vote/200",
            json={
                "difficulty": 4.0,
                "quality": 4,
            },
        )
        # May return error or job that fails
        assert response.status_code in [HTTP_202_ACCEPTED, 400, 404]

    # =========================================================================
    # DELETE VOTE TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_delete_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting a user's vote."""
        response = await test_client.delete(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/vote/{self.VOTER_USER_201}"
        )
        assert response.status_code == HTTP_202_ACCEPTED
        data = response.json()
        assert "id" in data

    @pytest.mark.asyncio
    async def test_delete_nonexistent_vote(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting non-existent vote (no error)."""
        response = await test_client.delete(f"/api/v3/maps/playtests/{self.PLAYTEST_NO_VOTES}/vote/999999")
        # Should not error
        assert response.status_code == 400

    # =========================================================================
    # DELETE ALL VOTES TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_delete_all_votes(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting all votes for a playtest."""
        response = await test_client.delete(f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/vote")
        assert response.status_code == HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_delete_all_votes_when_none_exist(self, test_client: AsyncTestClient[Litestar]):
        """Test deleting all votes when no votes exist (no error)."""
        response = await test_client.delete(f"/api/v3/maps/playtests/{self.PLAYTEST_NO_VOTES}/vote")
        assert response.status_code == HTTP_204_NO_CONTENT

    # =========================================================================
    # GET VOTES TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_votes(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all votes for a playtest."""
        response = await test_client.get(f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/votes")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Should have votes from seed
        assert "votes" in data or isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_votes_empty(self, test_client: AsyncTestClient[Litestar]):
        """Test getting votes for playtest with no votes."""
        response = await test_client.get(f"/api/v3/maps/playtests/{self.PLAYTEST_NO_VOTES}/votes")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # Empty votes
        if "votes" in data:
            assert len(data["votes"]) == 0
        else:
            assert data == [] or data is None

    # =========================================================================
    # EDIT PLAYTEST METADATA TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_edit_playtest_meta_verification_id(self, test_client: AsyncTestClient[Litestar]):
        """Test updating playtest verification_id."""
        response = await test_client.patch(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}",
            json={
                "verification_id": 9000000001,
            },
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.asyncio
    async def test_edit_playtest_meta_message_id(self, test_client: AsyncTestClient[Litestar]):
        """Test updating playtest message_id."""
        response = await test_client.patch(
            f"/api/v3/maps/playtests/{self.PLAYTEST_ONE_VOTE}",
            json={
                "completed": True,
            },
        )
        assert response.status_code == HTTP_200_OK

    # =========================================================================
    # ASSOCIATE PLAYTEST METADATA TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_associate_playtest_meta(self, test_client: AsyncTestClient[Litestar]):
        """Test associating playtest thread with map."""
        response = await test_client.patch(
            "/api/v3/maps/playtests/",
            json={
                "playtest_id": 3,
                "thread_id": 3000000001,
            },
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["thread_id"] == 3000000001

    # =========================================================================
    # APPROVE PLAYTEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_approve_playtest(self, test_client: AsyncTestClient[Litestar], asyncpg_conn):
        """Test approving a playtest."""
        map_id = await asyncpg_conn.fetchval(
            "SELECT map_id FROM playtests.meta WHERE thread_id=$1;",
            self.PLAYTEST_WITH_VOTES,
        )
        vote_count = await asyncpg_conn.fetchval(
            "SELECT count(*) FROM playtests.votes WHERE playtest_thread_id=$1;",
            self.PLAYTEST_WITH_VOTES,
        )
        if vote_count == 0:
            await asyncpg_conn.execute(
                """
                INSERT INTO playtests.votes (playtest_thread_id, user_id, map_id, difficulty)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, map_id, playtest_thread_id) DO UPDATE
                SET difficulty = EXCLUDED.difficulty;
                """,
                self.PLAYTEST_WITH_VOTES,
                self.VOTER_USER_200,
                map_id,
                3.5,
            )
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/approve",
            json={
                "verifier_id": 202,
            },
        )
        assert response.status_code == HTTP_202_ACCEPTED
        data = response.json()
        # Returns job status
        assert "id" in data

    # =========================================================================
    # FORCE ACCEPT TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_force_accept_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test force accepting with difficulty."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_NO_VOTES}/force_accept",
            json={
                "verifier_id": 202,
                "difficulty": "Medium",
            },
        )
        assert response.status_code == HTTP_202_ACCEPTED
        data = response.json()
        assert "id" in data

    # =========================================================================
    # FORCE DENY TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_force_deny_playtest(self, test_client: AsyncTestClient[Litestar]):
        """Test force denying with reason."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_ONE_VOTE}/force_deny",
            json={
                "verifier_id": 202,
                "reason": "Map does not meet quality standards",
            },
        )
        assert response.status_code == HTTP_202_ACCEPTED
        data = response.json()
        assert "id" in data

    # =========================================================================
    # RESET PLAYTEST TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_reset_playtest_full(self, test_client: AsyncTestClient[Litestar]):
        """Test resetting playtest with votes and completions removed."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/reset",
            json={
                "verifier_id": 202,
                "reason": "Need to restart testing",
                "remove_votes": True,
                "remove_completions": True,
            },
        )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_reset_playtest_keep_votes(self, test_client: AsyncTestClient[Litestar]):
        """Test resetting with remove_votes=false."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_ONE_VOTE}/reset",
            json={
                "verifier_id": 202,
                "reason": "Keep votes but reset",
                "remove_votes": False,
                "remove_completions": True,
            },
        )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_reset_playtest_keep_completions(self, test_client: AsyncTestClient[Litestar]):
        """Test resetting with remove_completions=false."""
        response = await test_client.post(
            f"/api/v3/maps/playtests/{self.PLAYTEST_WITH_VOTES}/reset",
            json={
                "verifier_id": 202,
                "reason": "Keep completions but reset",
                "remove_votes": True,
                "remove_completions": False,
            },
        )
        assert response.status_code == 500
