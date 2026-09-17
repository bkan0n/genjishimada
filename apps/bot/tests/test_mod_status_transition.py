"""Regression tests for moderator status transitions."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from msgspec import UNSET

_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from extensions import moderator  # noqa: E402


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
        get_map=AsyncMock(return_value=SimpleNamespace(code="ABCDE")),
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
