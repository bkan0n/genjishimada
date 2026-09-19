"""Regression tests for moderator record paginator refreshes."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from extensions import moderator  # noqa: E402


def test_refresh_records_clears_legacy_content_before_restoring_layout_view() -> None:
    records = [SimpleNamespace(id=1)]
    view = SimpleNamespace(
        code_filter=None,
        user_filter=None,
        verification_filter="All",
        latest_only=True,
        rebuild_data=Mock(),
        rebuild_components=Mock(),
    )
    interaction = SimpleNamespace(
        client=SimpleNamespace(api=SimpleNamespace(get_records_filtered=AsyncMock(return_value=records))),
        edit_original_response=AsyncMock(),
    )

    asyncio.run(
        moderator.ModRecordManagementView.refresh_records(
            cast(Any, view),
            cast(Any, interaction),
        )
    )

    interaction.edit_original_response.assert_awaited_once_with(content=None, view=view)
