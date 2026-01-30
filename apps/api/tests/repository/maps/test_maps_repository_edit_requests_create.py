"""Tests for MapsRepository edit request create operations.

Test Coverage:
- create_edit_request: Create new edit request with validation
"""

import json

import pytest
from faker import Faker

from repository.exceptions import ForeignKeyViolationError
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
# CREATE EDIT REQUEST TESTS
# ==============================================================================


class TestCreateEditRequest:
    """Test creating edit requests."""

    @pytest.mark.asyncio
    async def test_create_edit_request_with_valid_data_returns_dict(
        self,
        repository: MapsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test creating edit request with valid data returns dict with ID."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        proposed_changes = {"difficulty": "Hard", "checkpoints": 15}
        reason = fake.sentence(nb_words=10)

        # Act
        result = await repository.create_edit_request(
            map_id=map_id,
            code=unique_map_code,
            proposed_changes=proposed_changes,
            reason=reason,
            created_by=user_id,
        )

        # Assert
        assert isinstance(result, dict)
        assert "id" in result
        assert isinstance(result["id"], int)
        assert result["id"] > 0
        assert result["map_id"] == map_id
        assert result["code"] == unique_map_code
        assert result["created_by"] == user_id
        assert result["reason"] == reason

    @pytest.mark.asyncio
    async def test_create_edit_request_with_invalid_map_id_raises_foreign_key_error(
        self,
        repository: MapsRepository,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test creating edit request with invalid map_id raises ForeignKeyViolationError."""
        # Arrange
        invalid_map_id = 999999999
        user_id = await create_test_user()
        proposed_changes = {"difficulty": "Hard"}
        reason = fake.sentence()

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.create_edit_request(
                map_id=invalid_map_id,
                code=unique_map_code,
                proposed_changes=proposed_changes,
                reason=reason,
                created_by=user_id,
            )

        assert exc_info.value.table == "maps.edit_requests"
        assert "map_id" in exc_info.value.constraint_name or "fk" in exc_info.value.constraint_name.lower()

    @pytest.mark.asyncio
    async def test_create_edit_request_with_invalid_user_id_raises_foreign_key_error(
        self,
        repository: MapsRepository,
        create_test_map,
        unique_map_code: str,
    ) -> None:
        """Test creating edit request with invalid user_id raises ForeignKeyViolationError."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        invalid_user_id = 999999999999999999
        proposed_changes = {"difficulty": "Hard"}
        reason = fake.sentence()

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.create_edit_request(
                map_id=map_id,
                code=unique_map_code,
                proposed_changes=proposed_changes,
                reason=reason,
                created_by=invalid_user_id,
            )

        assert exc_info.value.table == "maps.edit_requests"
        assert "created_by" in exc_info.value.constraint_name or "fk" in exc_info.value.constraint_name.lower()

    @pytest.mark.asyncio
    async def test_create_edit_request_with_empty_proposed_changes(
        self,
        repository: MapsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test creating edit request with empty proposed_changes dict succeeds."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        proposed_changes = {}
        reason = fake.sentence()

        # Act
        result = await repository.create_edit_request(
            map_id=map_id,
            code=unique_map_code,
            proposed_changes=proposed_changes,
            reason=reason,
            created_by=user_id,
        )

        # Assert
        assert isinstance(result, dict)
        assert result["id"] > 0
        # proposed_changes is returned as JSON string from PostgreSQL
        assert json.loads(result["proposed_changes"]) == {}

    @pytest.mark.asyncio
    async def test_create_edit_request_with_complex_proposed_changes(
        self,
        repository: MapsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test creating edit request with complex proposed_changes dict."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        proposed_changes = {
            "difficulty": "Extreme",
            "checkpoints": 42,
            "description": "New description with special chars: @#$%",
            "title": "Updated Title",
            "mechanics": ["Bhop", "Slide"],
            "tags": ["XP Based"],
            "nested": {"key": "value"},
        }
        reason = fake.sentence()

        # Act
        result = await repository.create_edit_request(
            map_id=map_id,
            code=unique_map_code,
            proposed_changes=proposed_changes,
            reason=reason,
            created_by=user_id,
        )

        # Assert
        assert isinstance(result, dict)
        assert result["id"] > 0
        # proposed_changes is returned as JSON string from PostgreSQL
        assert json.loads(result["proposed_changes"]) == proposed_changes

    @pytest.mark.asyncio
    async def test_create_edit_request_returns_all_expected_fields(
        self,
        repository: MapsRepository,
        create_test_map,
        create_test_user,
        unique_map_code: str,
    ) -> None:
        """Test created edit request contains all expected fields."""
        # Arrange
        map_id = await create_test_map(code=unique_map_code)
        user_id = await create_test_user()
        proposed_changes = {"difficulty": "Hard"}
        reason = fake.sentence()

        # Act
        result = await repository.create_edit_request(
            map_id=map_id,
            code=unique_map_code,
            proposed_changes=proposed_changes,
            reason=reason,
            created_by=user_id,
        )

        # Assert - verify all fields present
        assert "id" in result
        assert "map_id" in result
        assert "code" in result
        assert "proposed_changes" in result
        assert "reason" in result
        assert "created_by" in result
        assert "created_at" in result
        assert "message_id" in result
        assert "resolved_at" in result
        assert "accepted" in result
        assert "resolved_by" in result
        assert "rejection_reason" in result

        # Assert - verify initial state
        assert result["message_id"] is None
        assert result["resolved_at"] is None
        assert result["accepted"] is None
        assert result["resolved_by"] is None
        assert result["rejection_reason"] is None
