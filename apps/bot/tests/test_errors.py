"""Regression tests for bot command error reporting."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from utilities import errors  # noqa: E402


def test_unknown_command_error_is_captured_once_without_reraising(monkeypatch) -> None:
    capture_exception = Mock(return_value="event-id")
    error_view = SimpleNamespace(original_interaction=None)
    monkeypatch.setattr(errors.sentry_sdk, "capture_exception", capture_exception)
    monkeypatch.setattr(errors, "ErrorView", Mock(return_value=error_view))
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1, name="moderator"),
        command=None,
        namespace=None,
        response=SimpleNamespace(is_done=Mock(return_value=True)),
        edit_original_response=AsyncMock(),
    )
    exception = RuntimeError("boom")

    asyncio.run(errors.on_command_error(cast(Any, interaction), exception))

    capture_exception.assert_called_once_with(exception)
    interaction.edit_original_response.assert_awaited_once_with(content=None, view=error_view)
