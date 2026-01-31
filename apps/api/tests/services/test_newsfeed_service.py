"""Unit tests for NewsfeedService."""

import datetime as dt

import msgspec
import pytest
from genjishimada_sdk.maps import MapPatchRequest, MapResponse, MedalsResponse
from genjishimada_sdk.newsfeed import (
    NewsfeedDispatchEvent,
    NewsfeedEvent,
    NewsfeedFieldChange,
    NewsfeedMapEdit,
)
from genjishimada_sdk.users import CreatorFull
from litestar.datastructures import Headers

from services.newsfeed_service import (
    NewsfeedService,
    _friendly_value,
    _labelize,
    _list_norm,
    _to_builtin,
    _values_equal,
)

pytestmark = [
    pytest.mark.domain_newsfeed,
]


def _create_test_map(**overrides):
    """Helper to create a test MapResponse with sensible defaults."""
    defaults = {
        "id": 1,
        "code": "TEST",
        "map_name": "Workshop Island",
        "category": "Classic",
        "creators": [],
        "checkpoints": 10,
        "difficulty": "Hard",
        "official": False,
        "playtesting": "Approved",
        "archived": False,
        "hidden": False,
        "created_at": dt.datetime.now(dt.timezone.utc),
        "updated_at": dt.datetime.now(dt.timezone.utc),
        "ratings": None,
        "playtest": None,
        "guides": None,
        "raw_difficulty": None,
        "mechanics": [],
        "restrictions": [],
        "tags": [],
        "description": None,
        "medals": None,
        "title": None,
        "map_banner": "",
        "time": None,
        "total_results": None,
        "linked_code": None,
    }
    defaults.update(overrides)
    return MapResponse(**defaults)


class TestNewsfeedServiceHelpers:
    """Test static helper functions."""

    def test_labelize_snake_case_to_title(self):
        """_labelize converts snake_case to Title Case."""
        assert _labelize("map_name") == "Map Name"
        assert _labelize("difficulty") == "Difficulty"
        assert _labelize("creators") == "Creators"

    def test_labelize_single_word(self):
        """_labelize handles single-word field names."""
        assert _labelize("code") == "Code"
        assert _labelize("reason") == "Reason"

    def test_to_builtin_primitives(self):
        """_to_builtin converts msgspec types to builtins."""
        assert _to_builtin("test") == "test"
        assert _to_builtin(42) == 42
        assert _to_builtin(None) is None

    def test_list_norm_sorts_strings(self):
        """_list_norm sorts strings alphabetically."""
        result = _list_norm(["zebra", "alpha", "beta"])
        assert result == ["alpha", "beta", "zebra"]

    def test_list_norm_handles_none(self):
        """_list_norm treats None as empty list."""
        result = _list_norm(None)
        assert result == []

    def test_list_norm_handles_empty_list(self):
        """_list_norm handles empty list."""
        result = _list_norm([])
        assert result == []

    def test_list_norm_converts_to_builtins(self):
        """_list_norm converts items to builtins before sorting."""
        result = _list_norm([3, 1, 2])
        assert result == [1, 2, 3]

    def test_values_equal_strings(self):
        """_values_equal compares string values."""
        assert _values_equal("map_name", "Test", "Test") is True
        assert _values_equal("map_name", "Test", "Other") is False

    def test_values_equal_list_fields_order_insensitive(self):
        """_values_equal compares list fields order-insensitively."""
        assert _values_equal("creators", ["Alice", "Bob"], ["Bob", "Alice"]) is True
        assert _values_equal("mechanics", ["Bhop", "Edge Climb"], ["Edge Climb", "Bhop"]) is True

    def test_values_equal_list_fields_different_content(self):
        """_values_equal detects different list content."""
        assert _values_equal("creators", ["Alice"], ["Bob"]) is False
        assert _values_equal("mechanics", ["Bhop"], ["Edge Climb"]) is False

    def test_values_equal_non_list_fields(self):
        """_values_equal compares non-list fields normally."""
        assert _values_equal("difficulty", "Hard", "Hard") is True
        assert _values_equal("difficulty", "Hard", "Easy") is False


class TestNewsfeedServiceFriendlyValue:
    """Test _friendly_value async rendering."""

    async def test_friendly_value_none_returns_placeholder(self):
        """_friendly_value renders None as 'Empty'."""
        result = await _friendly_value("any_field", None)
        assert result == "Empty"

    async def test_friendly_value_string(self):
        """_friendly_value renders string values."""
        result = await _friendly_value("map_name", "Cool Map")
        assert result == "Cool Map"

    async def test_friendly_value_integer(self):
        """_friendly_value renders integer values."""
        result = await _friendly_value("checkpoints", 10)
        assert result == "10"

    async def test_friendly_value_list_field_sorted(self):
        """_friendly_value renders list fields as sorted, comma-separated."""
        result = await _friendly_value("mechanics", ["Edge Climb", "Bhop", "Dash"])
        assert result == "Bhop, Dash, Edge Climb"

    async def test_friendly_value_list_field_empty(self):
        """_friendly_value renders empty list as placeholder."""
        result = await _friendly_value("mechanics", [])
        assert result == "Empty"

    async def test_friendly_value_list_field_none(self):
        """_friendly_value renders None list as placeholder."""
        result = await _friendly_value("mechanics", None)
        assert result == "Empty"

    async def test_friendly_value_creators_with_names(self):
        """_friendly_value extracts creator names."""
        creators = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        result = await _friendly_value("creators", creators)
        assert result == "Alice, Bob"

    async def test_friendly_value_creators_sorted_case_insensitive(self):
        """_friendly_value sorts creators case-insensitively."""
        creators = [
            {"id": 1, "name": "zebra"},
            {"id": 2, "name": "Alpha"},
        ]
        result = await _friendly_value("creators", creators)
        assert result == "Alpha, zebra"

    async def test_friendly_value_creators_deduplicates(self):
        """_friendly_value deduplicates creator names."""
        creators = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Alice"},
        ]
        result = await _friendly_value("creators", creators)
        assert result == "Alice"

    async def test_friendly_value_creators_with_resolver(self):
        """_friendly_value uses resolver when name is missing."""

        def get_creator_name(creator_id: int) -> str:
            return f"User{creator_id}"

        creators = [{"id": 1}, {"id": 2}]
        result = await _friendly_value("creators", creators, get_creator_name=get_creator_name)
        assert "User1" in result
        assert "User2" in result

    async def test_friendly_value_creators_async_resolver(self):
        """_friendly_value handles async resolver."""

        async def get_creator_name(creator_id: int) -> str:
            return f"AsyncUser{creator_id}"

        creators = [{"id": 1}, {"id": 2}]
        result = await _friendly_value("creators", creators, get_creator_name=get_creator_name)
        assert "AsyncUser1" in result
        assert "AsyncUser2" in result

    async def test_friendly_value_creators_empty_list(self):
        """_friendly_value renders empty creators as placeholder."""
        result = await _friendly_value("creators", [])
        assert result == "Empty"


class TestNewsfeedServiceListEvents:
    """Test list_events pagination logic."""

    async def test_list_events_calculates_offset_correctly(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """list_events calculates correct offset for pagination."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_newsfeed_repo.fetch_events.return_value = [
            {
                "id": 1,
                "timestamp": dt.datetime.now(dt.timezone.utc),
                "payload": {"type": "map_edit", "code": "TEST", "changes": [], "reason": "Test"},
                "event_type": "map_edit",
                "total_results": None,
            }
        ]

        # Page 1 with limit 10 -> offset 0
        await service.list_events(limit=10, page_number=1, type_=None)
        mock_newsfeed_repo.fetch_events.assert_called_with(limit=10, offset=0, event_type=None)

        # Page 2 with limit 10 -> offset 10
        await service.list_events(limit=10, page_number=2, type_=None)
        mock_newsfeed_repo.fetch_events.assert_called_with(limit=10, offset=10, event_type=None)

        # Page 3 with limit 25 -> offset 50
        await service.list_events(limit=25, page_number=3, type_=None)
        mock_newsfeed_repo.fetch_events.assert_called_with(limit=25, offset=50, event_type=None)

    async def test_list_events_handles_zero_page_number(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """list_events treats page 0 as page 1 (offset 0)."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_newsfeed_repo.fetch_events.return_value = [
            {
                "id": 1,
                "timestamp": dt.datetime.now(dt.timezone.utc),
                "payload": {"type": "map_edit", "code": "TEST", "changes": [], "reason": "Test"},
                "event_type": "map_edit",
                "total_results": None,
            }
        ]

        await service.list_events(limit=10, page_number=0, type_=None)
        # max(0 - 1, 0) * 10 = 0
        mock_newsfeed_repo.fetch_events.assert_called_with(limit=10, offset=0, event_type=None)

    async def test_list_events_returns_none_when_empty(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """list_events returns None when no events found."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_newsfeed_repo.fetch_events.return_value = []

        result = await service.list_events(limit=10, page_number=1, type_=None)
        assert result is None

    async def test_list_events_passes_type_filter(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """list_events passes event_type filter to repository."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_newsfeed_repo.fetch_events.return_value = [
            {
                "id": 1,
                "timestamp": dt.datetime.now(dt.timezone.utc),
                "payload": {"type": "map_edit", "code": "TEST", "changes": [], "reason": "Test"},
                "event_type": "map_edit",
                "total_results": None,
            }
        ]

        await service.list_events(limit=10, page_number=1, type_="map_edit")
        mock_newsfeed_repo.fetch_events.assert_called_with(limit=10, offset=0, event_type="map_edit")

    async def test_list_events_converts_to_newsfeed_events(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """list_events converts repository rows to NewsfeedEvent objects."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        timestamp = dt.datetime.now(dt.timezone.utc)
        mock_newsfeed_repo.fetch_events.return_value = [
            {
                "id": 1,
                "timestamp": timestamp,
                "payload": {"type": "map_edit", "code": "TEST", "changes": [], "reason": "Test"},
                "event_type": "map_edit",
                "total_results": None,
            }
        ]

        result = await service.list_events(limit=10, page_number=1, type_=None)
        assert result is not None
        assert len(result) == 1
        assert isinstance(result[0], NewsfeedEvent)
        assert result[0].id == 1


class TestNewsfeedServiceGetEvent:
    """Test get_event retrieval."""

    async def test_get_event_returns_none_when_not_found(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """get_event returns None when event not found."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_newsfeed_repo.fetch_event_by_id.return_value = None

        result = await service.get_event(999)
        assert result is None
        mock_newsfeed_repo.fetch_event_by_id.assert_called_once_with(999)

    async def test_get_event_converts_to_newsfeed_event(
        self, mock_pool, mock_state, mock_newsfeed_repo
    ):
        """get_event converts repository row to NewsfeedEvent."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        timestamp = dt.datetime.now(dt.timezone.utc)
        mock_newsfeed_repo.fetch_event_by_id.return_value = {
            "id": 1,
            "timestamp": timestamp,
            "payload": {"type": "map_edit", "code": "TEST", "changes": [], "reason": "Test"},
            "event_type": "map_edit",
            "total_results": None,
        }

        result = await service.get_event(1)
        assert result is not None
        assert isinstance(result, NewsfeedEvent)
        assert result.id == 1


class TestNewsfeedServiceCreateAndPublish:
    """Test create_and_publish orchestration."""

    async def test_create_and_publish_inserts_event(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """create_and_publish inserts event into repository."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mocker.patch.object(service, "publish_message", return_value={"status": "pending", "id": "job-1"})

        mock_newsfeed_repo.insert_event.return_value = 123

        timestamp = dt.datetime.now(dt.timezone.utc)
        event = NewsfeedEvent(
            id=None,
            timestamp=timestamp,
            payload=NewsfeedMapEdit(code="TEST", changes=[], reason="Testing"),
            event_type="map_edit",
            total_results=None,
        )
        headers = Headers({"x-pytest-enabled": "1"})

        result = await service.create_and_publish(event=event, headers=headers)

        # Verify repository called with correct data
        mock_newsfeed_repo.insert_event.assert_called_once()
        call_args = mock_newsfeed_repo.insert_event.call_args[1]
        assert call_args["timestamp"] == timestamp
        assert isinstance(call_args["payload"], dict)

        # Verify response contains new ID
        assert result.newsfeed_id == 123

    async def test_create_and_publish_publishes_to_rabbitmq(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """create_and_publish publishes event to RabbitMQ."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(
            service, "publish_message", return_value={"status": "pending", "id": "job-1"}
        )

        mock_newsfeed_repo.insert_event.return_value = 456

        timestamp = dt.datetime.now(dt.timezone.utc)
        event = NewsfeedEvent(
            id=None,
            timestamp=timestamp,
            payload=NewsfeedMapEdit(code="TEST", changes=[], reason="Testing"),
            event_type="map_edit",
            total_results=None,
        )
        headers = Headers({"x-pytest-enabled": "1"})

        await service.create_and_publish(event=event, headers=headers)

        # Verify publish_message called with correct routing key and event
        mock_publish.assert_called_once()
        call_args = mock_publish.call_args[1]
        assert call_args["routing_key"] == "api.newsfeed.create"
        assert isinstance(call_args["data"], NewsfeedDispatchEvent)
        assert call_args["data"].newsfeed_id == 456
        assert call_args["idempotency_key"] == "newsfeed:create:456"

    async def test_create_and_publish_converts_payload_to_builtins(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """create_and_publish converts msgspec payload to builtins for storage."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mocker.patch.object(service, "publish_message", return_value={"status": "pending", "id": "job-1"})
        mock_newsfeed_repo.insert_event.return_value = 789

        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = NewsfeedMapEdit(
            code="TEST",
            changes=[NewsfeedFieldChange(field="Map Name", old="Old", new="New")],
            reason="Testing",
        )
        event = NewsfeedEvent(
            id=None,
            timestamp=timestamp,
            payload=payload,
            event_type="map_edit",
            total_results=None,
        )
        headers = Headers({"x-pytest-enabled": "1"})

        await service.create_and_publish(event=event, headers=headers)

        # Verify payload was converted to dict
        call_args = mock_newsfeed_repo.insert_event.call_args[1]
        assert isinstance(call_args["payload"], dict)
        assert "code" in call_args["payload"]
        assert "changes" in call_args["payload"]


class TestNewsfeedServiceGenerateMapEdit:
    """Test generate_map_edit_newsfeed change detection."""

    async def test_generate_map_edit_no_changes_skips_publish(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed skips publishing when no changes detected."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Workshop Island")  # Using default value
        patch_data = MapPatchRequest(map_name="Workshop Island")  # Same value - no change
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="No change",
            headers=headers,
        )

        mock_publish.assert_not_called()

    async def test_generate_map_edit_detects_simple_field_change(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed detects simple field changes."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Eichenwalde")
        patch_data = MapPatchRequest(map_name="Workshop Chamber")
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="Name update",
            headers=headers,
        )

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args[1]
        event = call_args["event"]
        assert event.event_type == "map_edit"
        assert isinstance(event.payload, NewsfeedMapEdit)
        assert len(event.payload.changes) == 1
        assert event.payload.changes[0].field == "Map Name"
        assert event.payload.changes[0].old == "Eichenwalde"
        assert event.payload.changes[0].new == "Workshop Chamber"

    async def test_generate_map_edit_excludes_hidden_fields(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed excludes hidden, official, archived, playtesting."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Cool Map")
        patch_data = MapPatchRequest(hidden=True, official=True)
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="Admin update",
            headers=headers,
        )

        mock_publish.assert_not_called()

    async def test_generate_map_edit_ignores_msgspec_unset(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed ignores UNSET fields."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Cool Map")
        patch_data = MapPatchRequest()
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="No changes",
            headers=headers,
        )

        mock_publish.assert_not_called()

    async def test_generate_map_edit_list_fields_order_insensitive(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed treats list fields as order-insensitive."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Cool Map", mechanics=["Bhop", "Edge Climb"])
        patch_data = MapPatchRequest(mechanics=["Edge Climb", "Bhop"])
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="Order change",
            headers=headers,
        )

        mock_publish.assert_not_called()

    async def test_generate_map_edit_multiple_changes(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed detects multiple field changes."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Old Name", mechanics=["Bhop"], difficulty="Easy")
        patch_data = MapPatchRequest(
            map_name="Castillo",
            difficulty="Hard",
            mechanics=["Bhop", "Edge Climb"],
        )
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="Multiple updates",
            headers=headers,
        )

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args[1]
        event = call_args["event"]
        assert len(event.payload.changes) == 3

        field_names = {change.field for change in event.payload.changes}
        assert "Map Name" in field_names
        assert "Difficulty" in field_names
        assert "Mechanics" in field_names

    async def test_generate_map_edit_includes_reason(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed includes reason in payload."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(map_name="Old Name")
        patch_data = MapPatchRequest(map_name="Gogadoro")
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="User requested name change",
            headers=headers,
        )

        call_args = mock_publish.call_args[1]
        event = call_args["event"]
        assert event.payload.reason == "User requested name change"

    async def test_generate_map_edit_includes_map_code(
        self, mock_pool, mock_state, mock_newsfeed_repo, mocker
    ):
        """generate_map_edit_newsfeed includes map code in payload."""
        service = NewsfeedService(mock_pool, mock_state, mock_newsfeed_repo)

        mock_publish = mocker.patch.object(service, "create_and_publish")

        old_data = _create_test_map(code="AWESOME", map_name="Old Name")
        patch_data = MapPatchRequest(map_name="Lijiang Tower")
        headers = Headers({"x-pytest-enabled": "1"})

        await service.generate_map_edit_newsfeed(
            old_data=old_data,
            patch_data=patch_data,
            reason="Update",
            headers=headers,
        )

        call_args = mock_publish.call_args[1]
        event = call_args["event"]
        assert event.payload.code == "AWESOME"
