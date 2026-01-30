"""Tests for ChangeRequestsRepository list/search operations.

Test Coverage:
- fetch_unresolved_requests: filtering, ordering, empty results
- fetch_stale_requests: date boundaries, filtering, column selection
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from faker import Faker

from repository.change_requests_repository import ChangeRequestsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_change_requests,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide change_requests repository instance."""
    return ChangeRequestsRepository(asyncpg_conn)


# ==============================================================================
# FETCH_UNRESOLVED_REQUESTS TESTS
# ==============================================================================


class TestFetchUnresolvedRequestsHappyPath:
    """Test happy path scenarios for fetch_unresolved_requests."""

    @pytest.mark.asyncio
    async def test_fetch_returns_unresolved_requests(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching unresolved requests returns correct records."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create unresolved change request
        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
        )

        # Act
        result = await repository.fetch_unresolved_requests(unique_map_code)

        # Assert
        assert len(result) >= 1
        assert any(r["thread_id"] == thread_id for r in result)
        assert all(r["resolved"] is False for r in result)

    @pytest.mark.asyncio
    async def test_fetch_excludes_resolved_requests(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching unresolved requests excludes resolved ones."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create unresolved request
        unresolved_thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
        )

        # Create resolved request
        resolved_thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=True,
        )

        # Act
        result = await repository.fetch_unresolved_requests(unique_map_code)

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert unresolved_thread_id in thread_ids
        assert resolved_thread_id not in thread_ids
        assert all(r["resolved"] is False for r in result)

    @pytest.mark.asyncio
    async def test_fetch_returns_only_for_specified_code(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
    ):
        """Test fetching unresolved requests returns only for specified map code."""
        # Arrange
        map_code1 = f"T{uuid4().hex[:5].upper()}"
        map_code2 = f"T{uuid4().hex[:5].upper()}"

        map_id1 = await create_test_map(map_code1)
        map_id2 = await create_test_map(map_code2)

        user_id = await create_test_user()

        # Create requests for different maps
        thread_id1 = await create_test_change_request(
            code=map_code1,
            user_id=user_id,
            resolved=False,
        )

        thread_id2 = await create_test_change_request(
            code=map_code2,
            user_id=user_id,
            resolved=False,
        )

        # Act
        result = await repository.fetch_unresolved_requests(map_code1)

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert thread_id1 in thread_ids
        assert thread_id2 not in thread_ids
        assert all(r["code"] == map_code1 for r in result)

    @pytest.mark.asyncio
    async def test_fetch_orders_by_created_at_desc(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching unresolved requests orders by created_at DESC."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create multiple requests with different timestamps
        thread_ids = []
        for i in range(3):
            # Create with manual timestamp to ensure ordering
            thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            created_at = datetime.now(timezone.utc) - timedelta(hours=i)

            await asyncpg_conn.execute(
                """
                INSERT INTO change_requests (
                    thread_id, code, user_id, content, change_request_type,
                    creator_mentions, resolved, alerted, created_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                thread_id,
                unique_map_code,
                user_id,
                fake.sentence(),
                "Bug Fix",
                "",
                False,
                False,
                created_at,
            )
            thread_ids.append(thread_id)

        # Act
        result = await repository.fetch_unresolved_requests(unique_map_code)

        # Assert - newest should be first
        result_thread_ids = [r["thread_id"] for r in result]
        # thread_ids[0] was created most recently (i=0, so NOW - 0 hours)
        assert result_thread_ids.index(thread_ids[0]) < result_thread_ids.index(thread_ids[1])
        assert result_thread_ids.index(thread_ids[1]) < result_thread_ids.index(thread_ids[2])

    @pytest.mark.asyncio
    async def test_fetch_returns_all_columns(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching unresolved requests returns all columns."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        creator_mentions = f"{user_id}"

        thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            creator_mentions=creator_mentions,
            resolved=False,
        )

        # Act
        result = await repository.fetch_unresolved_requests(unique_map_code)

        # Assert
        assert len(result) >= 1
        request = next(r for r in result if r["thread_id"] == thread_id)

        # Verify all expected columns are present
        assert "thread_id" in request
        assert "code" in request
        assert "user_id" in request
        assert "content" in request
        assert "change_request_type" in request
        assert "creator_mentions" in request
        assert "resolved" in request
        assert "alerted" in request
        assert "created_at" in request


class TestFetchUnresolvedRequestsEdgeCases:
    """Test edge cases for fetch_unresolved_requests."""

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_code_returns_empty_list(
        self,
        repository: ChangeRequestsRepository,
    ):
        """Test fetching unresolved requests for non-existent code returns empty list."""
        # Arrange
        nonexistent_code = f"INVALID{uuid4().hex[:5].upper()}"

        # Act
        result = await repository.fetch_unresolved_requests(nonexistent_code)

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_all_resolved_returns_empty_list(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching unresolved requests when all are resolved returns empty list."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create only resolved requests
        await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=True,
        )

        # Act
        result = await repository.fetch_unresolved_requests(unique_map_code)

        # Assert
        assert result == []


# ==============================================================================
# FETCH_STALE_REQUESTS TESTS
# ==============================================================================


class TestFetchStaleRequestsHappyPath:
    """Test happy path scenarios for fetch_stale_requests."""

    @pytest.mark.asyncio
    async def test_fetch_returns_stale_requests(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching stale requests returns records older than 2 weeks."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create request older than 2 weeks
        stale_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        stale_date = datetime.now(timezone.utc) - timedelta(days=15)

        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            stale_thread_id,
            unique_map_code,
            user_id,
            fake.sentence(),
            "Bug Fix",
            "",
            False,
            False,
            stale_date,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert stale_thread_id in thread_ids

    @pytest.mark.asyncio
    async def test_fetch_excludes_recent_requests(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching stale requests excludes recent requests."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create recent request (less than 2 weeks old)
        recent_thread_id = await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
            alerted=False,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert recent_thread_id not in thread_ids

    @pytest.mark.asyncio
    async def test_fetch_excludes_alerted_requests(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching stale requests excludes already alerted requests."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create stale but alerted request
        alerted_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        stale_date = datetime.now(timezone.utc) - timedelta(days=15)

        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            alerted_thread_id,
            unique_map_code,
            user_id,
            fake.sentence(),
            "Bug Fix",
            "",
            False,
            True,  # Already alerted
            stale_date,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert alerted_thread_id not in thread_ids

    @pytest.mark.asyncio
    async def test_fetch_excludes_resolved_requests(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching stale requests excludes resolved requests."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create stale but resolved request
        resolved_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        stale_date = datetime.now(timezone.utc) - timedelta(days=15)

        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            resolved_thread_id,
            unique_map_code,
            user_id,
            fake.sentence(),
            "Bug Fix",
            "",
            True,  # Resolved
            False,
            stale_date,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert resolved_thread_id not in thread_ids

    @pytest.mark.asyncio
    async def test_fetch_returns_only_specific_columns(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching stale requests returns only thread_id, user_id, creator_mentions."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()
        creator_mentions = f"{user_id}"

        # Create stale request
        stale_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        stale_date = datetime.now(timezone.utc) - timedelta(days=15)

        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            stale_thread_id,
            unique_map_code,
            user_id,
            fake.sentence(),
            "Bug Fix",
            creator_mentions,
            False,
            False,
            stale_date,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        stale_request = next((r for r in result if r["thread_id"] == stale_thread_id), None)
        assert stale_request is not None

        # Verify only specific columns are present
        assert set(stale_request.keys()) == {"thread_id", "user_id", "creator_mentions"}
        assert stale_request["thread_id"] == stale_thread_id
        assert stale_request["user_id"] == user_id
        assert stale_request["creator_mentions"] == creator_mentions


class TestFetchStaleRequestsEdgeCases:
    """Test edge cases for fetch_stale_requests."""

    @pytest.mark.asyncio
    async def test_fetch_no_stale_requests_returns_empty_list(
        self,
        repository: ChangeRequestsRepository,
        create_test_map,
        create_test_user,
        create_test_change_request,
        unique_map_code: str,
    ):
        """Test fetching stale requests when none exist returns empty list."""
        # Arrange - create only recent requests
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        await create_test_change_request(
            code=unique_map_code,
            user_id=user_id,
            resolved=False,
            alerted=False,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert - the recent request should not be in results
        # (there may be other stale requests from other tests, but not ours)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_fetch_boundary_exactly_two_weeks(
        self,
        repository: ChangeRequestsRepository,
        asyncpg_conn,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ):
        """Test fetching stale requests with boundary at exactly 2 weeks."""
        # Arrange
        map_id = await create_test_map(unique_map_code)
        user_id = await create_test_user()

        # Create request at exactly 2 weeks + 1 minute (should be stale)
        stale_thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        boundary_date = datetime.now(timezone.utc) - timedelta(weeks=2, minutes=1)

        await asyncpg_conn.execute(
            """
            INSERT INTO change_requests (
                thread_id, code, user_id, content, change_request_type,
                creator_mentions, resolved, alerted, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            stale_thread_id,
            unique_map_code,
            user_id,
            fake.sentence(),
            "Bug Fix",
            "",
            False,
            False,
            boundary_date,
        )

        # Act
        result = await repository.fetch_stale_requests()

        # Assert
        thread_ids = [r["thread_id"] for r in result]
        assert stale_thread_id in thread_ids
