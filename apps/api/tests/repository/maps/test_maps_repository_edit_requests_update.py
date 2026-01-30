"""Tests for MapsRepository edit request update operations.

Test Coverage:
- set_edit_request_message_id: Set Discord message ID for edit request
- resolve_edit_request: Mark edit request as resolved (accepted/rejected)
"""

import datetime as dt

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
# SET EDIT REQUEST MESSAGE ID TESTS
# ==============================================================================


class TestSetEditRequestMessageId:
    """Test setting Discord message ID."""

    @pytest.mark.asyncio
    async def test_set_message_id_updates_field(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        asyncpg_conn,
    ) -> None:
        """Test set_edit_request_message_id updates the message_id field."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)
        message_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Act
        await repository.set_edit_request_message_id(edit_id, message_id)

        # Assert - verify in database
        result = await asyncpg_conn.fetchrow(
            "SELECT message_id FROM maps.edit_requests WHERE id = $1",
            edit_id,
        )
        assert result["message_id"] == message_id


# ==============================================================================
# RESOLVE EDIT REQUEST TESTS
# ==============================================================================


class TestResolveEditRequest:
    """Test resolving edit requests."""

    @pytest.mark.asyncio
    async def test_resolve_accept_sets_accepted_true(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        asyncpg_conn,
    ) -> None:
        """Test resolve_edit_request with accepted=True sets field correctly."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        resolver_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        await repository.resolve_edit_request(
            edit_id,
            accepted=True,
            resolved_by=resolver_id,
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT accepted FROM maps.edit_requests WHERE id = $1",
            edit_id,
        )
        assert result["accepted"] is True

    @pytest.mark.asyncio
    async def test_resolve_reject_sets_accepted_false(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        asyncpg_conn,
    ) -> None:
        """Test resolve_edit_request with accepted=False sets field correctly."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        resolver_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        await repository.resolve_edit_request(
            edit_id,
            accepted=False,
            resolved_by=resolver_id,
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT accepted FROM maps.edit_requests WHERE id = $1",
            edit_id,
        )
        assert result["accepted"] is False

    @pytest.mark.asyncio
    async def test_resolve_sets_resolved_by(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        asyncpg_conn,
    ) -> None:
        """Test resolve_edit_request sets resolved_by user ID."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        resolver_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)

        # Act
        await repository.resolve_edit_request(
            edit_id,
            accepted=True,
            resolved_by=resolver_id,
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT resolved_by FROM maps.edit_requests WHERE id = $1",
            edit_id,
        )
        assert result["resolved_by"] == resolver_id

    @pytest.mark.asyncio
    async def test_resolve_reject_with_reason(
        self,
        repository: MapsRepository,
        create_test_edit_request,
        create_test_map,
        create_test_user,
        unique_map_code: str,
        asyncpg_conn,
    ) -> None:
        """Test resolve_edit_request stores rejection reason when rejected."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        resolver_id = await create_test_user()
        edit_id = await create_test_edit_request(map_id, unique_map_code, user_id)
        rejection_reason = fake.sentence(nb_words=10)

        # Act
        await repository.resolve_edit_request(
            edit_id,
            accepted=False,
            resolved_by=resolver_id,
            rejection_reason=rejection_reason,
        )

        # Assert
        result = await asyncpg_conn.fetchrow(
            "SELECT rejection_reason FROM maps.edit_requests WHERE id = $1",
            edit_id,
        )
        assert result["rejection_reason"] == rejection_reason
