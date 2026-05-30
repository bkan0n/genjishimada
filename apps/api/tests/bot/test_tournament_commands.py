"""Unit tests for the Plan 10-03 tournament slash commands.

Each test maps to one bot-side behavior the Phase-10 VALIDATION map flags as
unit-coverable (the live Discord paths are Manual-Only):

- ``-k reroll_gate``           → D-07 / T-10-07: a non-Mod/non-Sensei invoker is rejected
  with ``UserFacingError`` and NO API write happens.
- ``-k reroll_dispatch``       → D-14 / D-15: code=None → ``reroll_next_cycle``; a code →
  ``choose_next_cycle`` with the ``TournamentChooseMapRequest``.
- ``-k streak_zero``           → D-04: a 404 ``APIHTTPError`` from the streak endpoint maps
  to current 0 / max 0 + the encouraging copy; a non-404 ``APIHTTPError`` propagates.
- ``-k leaderboard_empty``     → D-16 / Pitfall 1: an empty leaderboard short-circuits the
  friendly message and never constructs the paginator (no zero-page modulo).
- ``-k leaderboard_pagination``→ D-13: the paginator chunks pages of 10 (boundary correct).
- ``-k info_no_active_cycle``  → D-16: no active cycle → the "No active cycle…" message and
  ``get_map`` is NOT called.

The command callbacks are invoked directly with an injected fake ``itx`` (mock
``itx.client.api`` wrappers, ``itx.user.get_role`` + ``itx.client.config.roles.admin``);
no live Discord runtime is required. The bot's real ``utilities``/``extensions`` modules
are loaded from the apps/bot tree (they import cleanly without aio_pika/core).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from genjishimada_sdk.tournaments import (
    TournamentCategoryResponse,
    TournamentChooseMapRequest,
    TournamentCycleWithWinnerResponse,
    TournamentLeaderboardEntryResponse,
    TournamentNextCycleResponse,
    TournamentStreakResponse,
)


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[4]


def _load_tournaments_module() -> tuple[ModuleType, type, type]:
    """Load apps/bot/extensions/tournaments.py with the REAL bot utilities, then restore.

    Two collisions must be resolved before loading tournaments.py:

    1. ``test_tournaments_handler.py`` may register EMPTY ``utilities``/``extensions``
       stubs in ``sys.modules`` (path-less), and relies on its own stub
       ``extensions._queue_registry`` returning the raw handler fn.
    2. apps/api has its OWN ``utilities`` package which pytest may already have imported,
       shadowing the bot's ``utilities.transformers`` / ``utilities.paginator``.

    To avoid cross-test pollution we snapshot the ``utilities``/``extensions`` package
    trees, evict them, prepend apps/bot to ``sys.path`` so the bot modules resolve (they
    import cleanly without aio_pika/core), load tournaments.py, capture the symbols we
    need (including the REAL ``APIHTTPError``/``UserFacingError`` so the streak ``except``
    actually catches), then RESTORE the snapshot so sibling tests see a clean slate.
    """
    module_name = "bot_ext_tournament_commands"
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        return mod, mod._errors_APIHTTPError, mod._errors_UserFacingError  # type: ignore[attr-defined]

    bot_root = _repo_root() / "apps" / "bot"
    snapshot = {k: v for k, v in sys.modules.items() if k in ("utilities", "extensions") or k.startswith(("utilities.", "extensions."))}
    try:
        for key in snapshot:
            del sys.modules[key]
        if sys.path[0] != str(bot_root):
            sys.path.insert(0, str(bot_root))

        module_path = bot_root / "extensions" / "tournaments.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        import utilities.errors as _errs  # the real bot errors module, now resolvable

        module._errors_APIHTTPError = _errs.APIHTTPError  # type: ignore[attr-defined]
        module._errors_UserFacingError = _errs.UserFacingError  # type: ignore[attr-defined]
        return module, _errs.APIHTTPError, _errs.UserFacingError
    finally:
        # Restore the package trees the sibling handler test depends on.
        for key in list(sys.modules):
            if key in ("utilities", "extensions") or key.startswith(("utilities.", "extensions.")):
                del sys.modules[key]
        sys.modules.update(snapshot)
        with __import__("contextlib").suppress(ValueError):
            sys.path.remove(str(bot_root))


_tournaments, APIHTTPError, UserFacingError = _load_tournaments_module()
TournamentCommandCog = _tournaments.TournamentCommandCog
TournamentRerollCog = _tournaments.TournamentRerollCog
TournamentLeaderboardPaginator = _tournaments.TournamentLeaderboardPaginator

_NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
_MOD_ROLE = 111
_SENSEI_ROLE = 222


def _sample_category() -> TournamentCategoryResponse:
    return TournamentCategoryResponse(
        id=1,
        name="Hard",
        difficulties=["Hard"],
        cycle_frequency="weekly",
        participation_xp=100,
        placement_xp=[],
        streak_xp=[],
        champion_role_id=999,
        is_active=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _active_cycle() -> TournamentCycleWithWinnerResponse:
    return TournamentCycleWithWinnerResponse(
        id=42,
        category_id=1,
        map_id=7,
        map_code="ABCD1",
        map_name="Hanamura",
        map_difficulty="Hard",
        status="active",
        started_at=_NOW,
        ended_at=None,
        created_at=_NOW,
        winner_name=None,
        winner_user_id=None,
    )


def _next_cycle() -> TournamentNextCycleResponse:
    return TournamentNextCycleResponse(
        id=99,
        category_id=1,
        map_id=8,
        map_code="WXYZ9",
        map_name="Nepal",
        map_difficulty="Medium",
        status="pending",
        created_at=_NOW,
    )


def _cycle_list(cycles: list[TournamentCycleWithWinnerResponse]) -> SimpleNamespace:
    return SimpleNamespace(total=len(cycles), cycles=cycles)


def _make_itx(*, user_id: int = 500, roles: set[int] | None = None) -> SimpleNamespace:
    """Build a fake interaction recording defer / edit_original_response calls."""
    roles = roles or set()
    api = AsyncMock()
    config = SimpleNamespace(roles=SimpleNamespace(admin=SimpleNamespace(mod=_MOD_ROLE, sensei=_SENSEI_ROLE)))

    response = SimpleNamespace(defer=AsyncMock())
    edit = AsyncMock()

    # spec=discord.Member so the reroll command's `isinstance(itx.user, discord.Member)`
    # guard passes for the gated admin command.
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.get_role = MagicMock(side_effect=lambda rid: object() if rid in roles else None)

    client = SimpleNamespace(api=api, config=config)
    itx = SimpleNamespace(
        response=response,
        edit_original_response=edit,
        user=user,
        client=client,
        guild=object(),
    )
    return itx


# ---------------------------------------------------------------------------
# reroll gate (D-07 / T-10-07)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reroll_gate_rejects_non_admin_without_api_write() -> None:
    """A non-Mod/non-Sensei invoker is rejected and NO API write occurs."""
    cog = object.__new__(TournamentRerollCog)
    itx = _make_itx(roles=set())  # no admin roles

    with pytest.raises(UserFacingError):
        await TournamentRerollCog.tournament_reroll.callback(cog, itx, 1, None)

    itx.client.api.reroll_next_cycle.assert_not_called()
    itx.client.api.choose_next_cycle.assert_not_called()


# ---------------------------------------------------------------------------
# reroll dispatch (D-14 / D-15)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reroll_dispatch_random_when_no_code() -> None:
    """A Mod with code=None calls reroll_next_cycle(category) — random reroll (D-14)."""
    cog = object.__new__(TournamentRerollCog)
    itx = _make_itx(roles={_MOD_ROLE})
    itx.client.api.reroll_next_cycle.return_value = _next_cycle()

    await TournamentRerollCog.tournament_reroll.callback(cog, itx, 1, None)

    itx.client.api.reroll_next_cycle.assert_awaited_once_with(1)
    itx.client.api.choose_next_cycle.assert_not_called()


@pytest.mark.asyncio
async def test_reroll_dispatch_explicit_code_calls_choose() -> None:
    """A Sensei with a code calls choose_next_cycle with the request payload (D-15)."""
    cog = object.__new__(TournamentRerollCog)
    itx = _make_itx(roles={_SENSEI_ROLE})
    itx.client.api.choose_next_cycle.return_value = _next_cycle()

    await TournamentRerollCog.tournament_reroll.callback(cog, itx, 1, "WXYZ9")

    itx.client.api.reroll_next_cycle.assert_not_called()
    itx.client.api.choose_next_cycle.assert_awaited_once()
    args = itx.client.api.choose_next_cycle.await_args
    assert args.args[0] == 1
    payload = args.args[1]
    assert isinstance(payload, TournamentChooseMapRequest)
    assert payload.map_code == "WXYZ9"


# ---------------------------------------------------------------------------
# streak zero-state (D-04 via APIHTTPError 404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streak_zero_maps_404_to_zero_state() -> None:
    """A 404 APIHTTPError maps to current 0 / max 0 + encouraging copy."""
    from http import HTTPStatus

    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx(user_id=777)
    itx.client.api.get_tournament_streak.side_effect = APIHTTPError(
        HTTPStatus.NOT_FOUND, "Not Found", "StreakNotFound", None
    )

    await TournamentCommandCog.streak.callback(cog, itx)

    embed = itx.edit_original_response.await_args.kwargs["embed"]
    rendered = (embed.title or "") + (embed.description or "")
    rendered += "".join(f"{f.name}{f.value}" for f in embed.fields)
    assert "Current Streak0" in rendered
    assert "Max Streak0" in rendered
    assert "Submit in a cycle to start your streak!" in (embed.description or "")


@pytest.mark.asyncio
async def test_streak_zero_does_not_swallow_non_404() -> None:
    """A non-404 APIHTTPError is NOT swallowed by the zero-state mapping."""
    from http import HTTPStatus

    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx(user_id=777)
    itx.client.api.get_tournament_streak.side_effect = APIHTTPError(
        HTTPStatus.INTERNAL_SERVER_ERROR, "Boom", "ServerError", None
    )

    with pytest.raises(APIHTTPError):
        await TournamentCommandCog.streak.callback(cog, itx)


@pytest.mark.asyncio
async def test_streak_renders_real_record() -> None:
    """A present streak record renders its current/max values (no zero-state copy)."""
    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx(user_id=777)
    itx.client.api.get_tournament_streak.return_value = TournamentStreakResponse(
        user_id=777, current_streak=3, max_streak=5, last_cycle_id=42, updated_at=_NOW
    )

    await TournamentCommandCog.streak.callback(cog, itx)

    embed = itx.edit_original_response.await_args.kwargs["embed"]
    rendered = "".join(f"{f.name}{f.value}" for f in embed.fields)
    assert "Current Streak3" in rendered
    assert "Max Streak5" in rendered
    assert "Submit in a cycle" not in (embed.description or "")


# ---------------------------------------------------------------------------
# leaderboard empty short-circuit (D-16 / Pitfall 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaderboard_empty_short_circuits_without_paginator(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty leaderboard sends the friendly message and never builds the paginator."""
    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx()
    itx.client.api.get_tournament_category.return_value = _sample_category()
    itx.client.api.list_tournament_cycles.return_value = _cycle_list([_active_cycle()])
    itx.client.api.get_tournament_leaderboard.return_value = []

    built: list[Any] = []
    real_init = TournamentLeaderboardPaginator.__init__

    def _spy_init(self: Any, *a: Any, **k: Any) -> None:
        built.append(self)
        real_init(self, *a, **k)

    monkeypatch.setattr(TournamentLeaderboardPaginator, "__init__", _spy_init)

    await TournamentCommandCog.leaderboard.callback(cog, itx, 1)

    assert built == []  # paginator never constructed
    content = itx.edit_original_response.await_args.kwargs["content"]
    assert "No submissions yet" in content


# ---------------------------------------------------------------------------
# leaderboard pagination boundary (D-13)
# ---------------------------------------------------------------------------


def test_leaderboard_pagination_chunks_pages_of_ten() -> None:
    """>10 entries chunk into pages of exactly 10 (boundary correct)."""
    entries = [
        TournamentLeaderboardEntryResponse(
            rank=i, user_id=1000 + i, name=f"p{i}", time=float(i), verified=True, completion=True
        )
        for i in range(1, 26)  # 25 entries
    ]
    view = TournamentLeaderboardPaginator("Hard — Leaderboard", entries)
    assert view.get_total_pages() == 3
    assert len(view.pages[0]) == 10
    assert len(view.pages[1]) == 10
    assert len(view.pages[2]) == 5


def test_leaderboard_rows_render_numeric_mentions_not_names() -> None:
    """Rows use <@user_id> mentions only — never interpolate the free-text name (OQ2)."""
    entries = [
        TournamentLeaderboardEntryResponse(
            rank=1, user_id=424242, name="@everyone", time=9.5, verified=True, completion=True
        )
    ]
    view = TournamentLeaderboardPaginator("Hard — Leaderboard", entries)
    body = view.build_page_body()
    text = body[0].content
    assert "<@424242>" in text
    assert "@everyone" not in text


# ---------------------------------------------------------------------------
# info no active cycle (D-16)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_info_no_active_cycle_skips_get_map() -> None:
    """No active cycle → the 'No active cycle…' message and get_map is NOT called."""
    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx()
    itx.client.api.get_tournament_category.return_value = _sample_category()
    itx.client.api.list_tournament_cycles.return_value = _cycle_list([])

    await TournamentCommandCog.info.callback(cog, itx, 1)

    itx.client.api.get_map.assert_not_called()
    content = itx.edit_original_response.await_args.kwargs["content"]
    assert "No active cycle" in content


@pytest.mark.asyncio
async def test_info_renders_card_for_active_cycle() -> None:
    """An active cycle renders the rich card with map link, end time, thumbnail."""
    cog = object.__new__(TournamentCommandCog)
    itx = _make_itx()
    itx.client.api.get_tournament_category.return_value = _sample_category()
    itx.client.api.list_tournament_cycles.return_value = _cycle_list([_active_cycle()])
    itx.client.api.get_map.return_value = SimpleNamespace(
        difficulty="Hard", map_name="Hanamura", map_banner="https://cdn.genji.pk/b.png"
    )

    await TournamentCommandCog.info.callback(cog, itx, 1)

    itx.client.api.get_map.assert_awaited_once_with(code="ABCD1")
    embed = itx.edit_original_response.await_args.kwargs["embed"]
    rendered = (embed.title or "") + (embed.description or "")
    rendered += "".join(f"{f.name}{f.value}" for f in embed.fields)
    assert "Hanamura" in rendered
    assert "ABCD1" in rendered
    assert "workshop.codes" in rendered
    assert embed.thumbnail.url == "https://cdn.genji.pk/b.png"
