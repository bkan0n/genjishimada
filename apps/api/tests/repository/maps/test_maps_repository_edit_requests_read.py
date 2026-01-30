"""Tests for MapsRepository edit request read operations.

Test Coverage:
- fetch_edit_request: Fetch specific edit request by ID
- check_pending_edit_request: Check if map has pending edit request
- fetch_pending_edit_requests: Fetch all pending edit requests
- fetch_edit_submission: Fetch enriched edit request for verification queue
- fetch_user_edit_requests: Fetch user's edit requests
"""

import pytest
from faker import Faker

from repository.maps_repository import MapsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_maps,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide maps repository instance."""
    return MapsRepository(asyncpg_conn)


# ==============================================================================
# FETCH EDIT REQUEST TESTS
# ==============================================================================


class TestFetchEditRequest:
    """Test fetching specific edit request."""

    @pytest.mark.asyncio
    async def test_fetch_edit_request_returns_dict_for_valid_id(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test fetch_edit_request returns dict for valid ID."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        result = await repository.fetch_edit_request(edit_id)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert result["id"] == edit_id
        assert result["map_id"] == map_id
        assert result["code"] == unique_map_code
        assert result["created_by"] == user_id



# ==============================================================================
# CHECK PENDING EDIT REQUEST TESTS
# ==============================================================================


class TestCheckPendingEditRequest:
    """Test checking for pending edit requests."""

    @pytest.mark.asyncio
    async def test_check_pending_returns_id_when_pending(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test check_pending_edit_request returns ID when map has pending request."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        result = await repository.check_pending_edit_request(map_id)

        # Assert
        assert result == edit_id

    @pytest.mark.asyncio
    async def test_check_pending_returns_none_when_resolved(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test check_pending_edit_request returns None when request is resolved."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Resolve the request
        await repository.resolve_edit_request(edit_id, accepted=True, resolved_by=user_id)

        # Act
        result = await repository.check_pending_edit_request(map_id)

        # Assert
        assert result is None



# ==============================================================================
# FETCH PENDING EDIT REQUESTS TESTS
# ==============================================================================


class TestFetchPendingEditRequests:
    """Test fetching all pending edit requests."""

    @pytest.mark.asyncio
    async def test_fetch_pending_returns_only_pending(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
    ) -> None:
        """Test fetch_pending_edit_requests returns only pending requests."""
        from uuid import uuid4

        # Arrange - create pending and resolved requests
        map_id1 = await create_test_map(code=f"T{uuid4().hex[:5].upper()}")
        map_id2 = await create_test_map(code=f"T{uuid4().hex[:5].upper()}")
        user_id = await create_test_user()

        code1 = f"T{uuid4().hex[:5].upper()}"
        code2 = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code1)
        global_code_tracker.add(code2)

        # Create pending request
        pending_id = await create_test_edit_request(map_id1, code1, user_id)

        # Create and resolve another request
        resolved_id = await create_test_edit_request(map_id2, code2, user_id)
        await repository.resolve_edit_request(resolved_id, accepted=True, resolved_by=user_id)

        # Act
        result = await repository.fetch_pending_edit_requests()

        # Assert
        assert isinstance(result, list)
        pending_ids = [r["id"] for r in result]
        assert pending_id in pending_ids
        assert resolved_id not in pending_ids

    @pytest.mark.asyncio
    async def test_fetch_pending_ordered_by_created_at(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
        asyncpg_conn,
    ) -> None:
        """Test fetch_pending_edit_requests ordered by created_at ascending."""
        import asyncio
        from uuid import uuid4

        # Arrange - create multiple pending requests with small delays
        user_id = await create_test_user()
        edit_ids = []

        for _ in range(3):
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)
            map_id = await create_test_map(code=code)
            edit_id = await create_test_edit_request(map_id, code, user_id)
            edit_ids.append(edit_id)
            await asyncio.sleep(0.01)  # Small delay to ensure different timestamps

        # Act
        result = await repository.fetch_pending_edit_requests()

        # Assert - find our created requests in order
        our_requests = [r for r in result if r["id"] in edit_ids]
        assert len(our_requests) == 3

        # Verify ordering (oldest first)
        for i in range(len(our_requests) - 1):
            assert our_requests[i]["id"] < our_requests[i + 1]["id"]


# ==============================================================================
# FETCH EDIT SUBMISSION TESTS
# ==============================================================================


class TestFetchEditSubmission:
    """Test fetching enriched edit submission."""

    @pytest.mark.asyncio
    async def test_fetch_submission_returns_enriched_data(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test fetch_edit_submission returns enriched dict with all sections."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        result = await repository.fetch_edit_submission(edit_id)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert "edit_request" in result
        assert "submitter_name" in result
        assert "current_map" in result
        assert "current_creators" in result
        assert "current_medals" in result

    @pytest.mark.asyncio
    async def test_fetch_submission_includes_current_map_data(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test fetch_edit_submission includes current map data."""
        # Arrange
        map_id = await create_test_map(
            code=unique_map_code,
            difficulty="Hard",
            checkpoints=25,
        )
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        result = await repository.fetch_edit_submission(edit_id)

        # Assert
        assert result is not None
        current_map = result["current_map"]
        assert current_map["code"] == unique_map_code
        assert current_map["difficulty"] == "Hard"
        assert current_map["checkpoints"] == 25



# ==============================================================================
# FETCH USER EDIT REQUESTS TESTS
# ==============================================================================


class TestFetchUserEditRequests:
    """Test fetching user's edit requests."""

    @pytest.mark.asyncio
    async def test_fetch_user_requests_excludes_resolved_by_default(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
    ) -> None:
        """Test fetch_user_edit_requests excludes resolved by default."""
        from uuid import uuid4

        # Arrange
        user_id = await create_test_user()
        resolver_id = await create_test_user()

        # Create pending request
        code1 = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code1)
        map_id1 = await create_test_map(code=code1)
        pending_id = await create_test_edit_request(map_id1, code1, user_id)

        # Create resolved request
        code2 = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code2)
        map_id2 = await create_test_map(code=code2)
        resolved_id = await create_test_edit_request(map_id2, code2, user_id)
        await repository.resolve_edit_request(resolved_id, accepted=True, resolved_by=resolver_id)

        # Act
        result = await repository.fetch_user_edit_requests(user_id, include_resolved=False)

        # Assert
        assert isinstance(result, list)
        request_ids = [r["id"] for r in result]
        assert pending_id in request_ids
        assert resolved_id not in request_ids

    @pytest.mark.asyncio
    async def test_fetch_user_requests_includes_resolved_when_true(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
    ) -> None:
        """Test fetch_user_edit_requests includes resolved when include_resolved=True."""
        from uuid import uuid4

        # Arrange
        user_id = await create_test_user()
        resolver_id = await create_test_user()

        # Create pending request
        code1 = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code1)
        map_id1 = await create_test_map(code=code1)
        pending_id = await create_test_edit_request(map_id1, code1, user_id)

        # Create resolved request
        code2 = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code2)
        map_id2 = await create_test_map(code=code2)
        resolved_id = await create_test_edit_request(map_id2, code2, user_id)
        await repository.resolve_edit_request(resolved_id, accepted=True, resolved_by=resolver_id)

        # Act
        result = await repository.fetch_user_edit_requests(user_id, include_resolved=True)

        # Assert
        assert isinstance(result, list)
        request_ids = [r["id"] for r in result]
        assert pending_id in request_ids
        assert resolved_id in request_ids

    @pytest.mark.asyncio
    async def test_fetch_user_requests_ordered_by_created_at_desc(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        global_code_tracker: set[str],
    ) -> None:
        """Test fetch_user_edit_requests ordered by created_at DESC (newest first)."""
        import asyncio
        from uuid import uuid4

        # Arrange - create multiple requests with small delays
        user_id = await create_test_user()
        edit_ids = []

        for _ in range(3):
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)
            map_id = await create_test_map(code=code)
            edit_id = await create_test_edit_request(map_id, code, user_id)
            edit_ids.append(edit_id)
            await asyncio.sleep(0.01)

        # Act
        result = await repository.fetch_user_edit_requests(user_id)

        # Assert - verify DESC order (newest first)
        our_requests = [r for r in result if r["id"] in edit_ids]
        assert len(our_requests) == 3

        for i in range(len(our_requests) - 1):
            # Newer IDs should come first
            assert our_requests[i]["id"] > our_requests[i + 1]["id"]

