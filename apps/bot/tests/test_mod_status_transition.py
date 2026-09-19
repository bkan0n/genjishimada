"""Regression tests for moderator status transitions."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from msgspec import UNSET

_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from extensions import moderator  # noqa: E402


def _map_data(playtesting: str) -> SimpleNamespace:
    return SimpleNamespace(
        code="ABCDE",
        hidden=False,
        official=False,
        archived=False,
        playtesting=playtesting,
    )


def test_send_to_playtest_does_not_set_in_progress_before_send(monkeypatch):
    view = SimpleNamespace(
        confirmed=True,
        playtest_status_select=SimpleNamespace(values=["In Progress"]),
        send_to_playtest_button=SimpleNamespace(enabled=True),
        playtest_difficulty_select=SimpleNamespace(values=["Medium"]),
        hidden_button=SimpleNamespace(enabled=False),
        official_button=SimpleNamespace(enabled=True),
        archived_button=SimpleNamespace(enabled=False),
        wait=AsyncMock(),
    )
    monkeypatch.setattr(moderator, "ModStatusView", lambda data: view)
    api = SimpleNamespace(
        get_map=AsyncMock(return_value=_map_data("Rejected")),
        edit_map=AsyncMock(),
        send_map_to_playtest=AsyncMock(),
    )
    bot = SimpleNamespace(api=api)
    interaction = SimpleNamespace(
        client=bot,
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )

    callback = cast(Any, moderator.ModeratorCog.edit_status.callback)
    asyncio.run(callback(moderator.ModeratorCog(cast(Any, bot)), interaction, "ABCDE"))

    assert api.edit_map.await_args.args[1].playtesting is UNSET
    api.send_map_to_playtest.assert_awaited_once()


def test_legacy_status_view_hides_send_action_for_active_playtest() -> None:
    view = moderator.ModStatusView(cast(Any, _map_data("In Progress")))

    assert view.send_to_playtest_button not in list(view.walk_children())


def test_map_edit_wizard_hides_send_action_for_active_playtest() -> None:
    select = moderator.FieldSelectionSelect(cast(Any, _map_data("In Progress")), is_mod=True)

    assert moderator.EditableField.SEND_TO_PLAYTEST.value not in {option.value for option in select.options}


def test_enabling_send_to_playtest_requires_difficulty_before_confirm() -> None:
    view = moderator.ModStatusView(cast(Any, _map_data("Rejected")))
    interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))

    asyncio.run(view.send_to_playtest_button.callback(cast(Any, interaction)))

    assert view.send_to_playtest_button.enabled is True
    assert view.confirmation_button.disabled is True


def test_send_to_playtest_requires_difficulty_at_submission(monkeypatch) -> None:
    view = SimpleNamespace(
        confirmed=True,
        playtest_status_select=SimpleNamespace(values=["Rejected"]),
        send_to_playtest_button=SimpleNamespace(enabled=True),
        playtest_difficulty_select=SimpleNamespace(values=[]),
        hidden_button=SimpleNamespace(enabled=False),
        official_button=SimpleNamespace(enabled=True),
        archived_button=SimpleNamespace(enabled=False),
        wait=AsyncMock(),
    )
    monkeypatch.setattr(moderator, "ModStatusView", lambda data: view)
    api = SimpleNamespace(
        get_map=AsyncMock(return_value=_map_data("Rejected")),
        edit_map=AsyncMock(),
        send_map_to_playtest=AsyncMock(),
    )
    bot = SimpleNamespace(api=api)
    interaction = SimpleNamespace(
        client=bot,
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_response=AsyncMock(),
    )

    callback = cast(Any, moderator.ModeratorCog.edit_status.callback)
    with pytest.raises(moderator.UserFacingError, match="difficulty"):
        asyncio.run(callback(moderator.ModeratorCog(cast(Any, bot)), interaction, "ABCDE"))

    api.edit_map.assert_not_awaited()
    api.send_map_to_playtest.assert_not_awaited()


def test_send_to_playtest_rejects_stale_active_map() -> None:
    api = SimpleNamespace(
        get_map=AsyncMock(return_value=_map_data("In Progress")),
        send_map_to_playtest=AsyncMock(),
    )

    with pytest.raises(moderator.UserFacingError, match="already in playtest"):
        asyncio.run(moderator._send_map_to_playtest(cast(Any, api), "ABCDE", "Medium"))

    api.send_map_to_playtest.assert_not_awaited()
