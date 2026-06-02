"""Unit tests for the tournament announcement handler (Plan 09-02).

Each test maps to one behavior in the Phase 9 VALIDATION map and is named so the
documented ``-k`` selector picks exactly one group:

- ``-k rollover``          → D-09/D-10: ONE combined card; the three conditional cases
- ``-k champion_role``     → DSC-03 / RWD-03: strip role from all holders then grant to winner
- ``-k champion_vacant``   → DSC-03 / RWD-03: winner_user_id is None → strip-all, leave vacant (D-05)
- ``-k stagger``           → DSC-03 / RWD-03: role ops staggered to respect Discord rate limits
- ``-k idempotency``       → D-09: edition-scoped dedupe; claim released on failure

The handler body is invoked directly with injected fakes (mock ``bot.api``, a fake
announcement channel, the conftest fake guild/role/member trio). The ``@queue_consumer``
wrapper's pytest-header short-circuit covers the live RabbitMQ path; these tests exercise
the underlying handler logic.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from genjishimada_sdk.tournaments import (
    TournamentCompletionCreatedEvent,
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
    TournamentEditionResultsEvent,
    TournamentLeaderboardEntryResponse,
    TournamentRolloverEvent,
    TournamentVerificationChangedEvent,
)

if TYPE_CHECKING:
    from genjishimada_sdk.tournaments import TournamentCategoryResponse


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[4]


def _load_tournaments_module() -> ModuleType:
    """Load apps/bot/extensions/tournaments.py with the REAL bot ``utilities`` graph.

    Plan 10-03 added command cogs to tournaments.py that import
    ``utilities.transformers`` / ``utilities.paginator`` / ``utilities.errors`` (and
    ``discord.ext.commands``). Those import cleanly from the apps/bot tree, so we load the
    real ``utilities`` package rather than stubbing it. The only piece we still stub is
    ``extensions._queue_registry.queue_consumer`` — its real wrapper expects a raw
    ``message`` to decode, whereas these tests invoke the handler body with an
    already-decoded event, so the stub returns the raw handler unwrapped.

    To avoid polluting sibling tests (apps/api has its own ``utilities`` package), the
    ``utilities``/``extensions`` package trees are snapshotted, evicted while apps/bot is
    on ``sys.path``, then restored in ``finally``.
    """
    module_name = "bot_extensions_tournaments"
    if module_name in sys.modules:
        return sys.modules[module_name]

    bot_root = _repo_root() / "apps" / "bot"
    snapshot = {
        k: v
        for k, v in sys.modules.items()
        if k in ("utilities", "extensions") or k.startswith(("utilities.", "extensions."))
    }
    try:
        for key in snapshot:
            del sys.modules[key]
        if str(bot_root) not in sys.path:
            sys.path.insert(0, str(bot_root))

        # Stub only the queue registry so the handler bodies are invokable directly.
        _install_queue_registry_stub()

        module_path = bot_root / "extensions" / "tournaments.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key in list(sys.modules):
            if key in ("utilities", "extensions") or key.startswith(("utilities.", "extensions.")):
                del sys.modules[key]
        sys.modules.update(snapshot)


def _install_queue_registry_stub() -> None:
    """Stub ``extensions._queue_registry.queue_consumer`` as a no-op pass-through.

    The real wrapper expects a raw RabbitMQ ``message`` it decodes into the struct; these
    tests invoke the handler body with an already-decoded event, so the stub decorator
    returns the original handler unwrapped (attaching the metadata RabbitHandler reads).
    A minimal ``extensions`` package shell is registered so the ``from
    extensions._queue_registry import queue_consumer`` import resolves to the stub rather
    than the real (aio_pika-importing) module.
    """
    extensions_pkg = ModuleType("extensions")
    extensions_pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules["extensions"] = extensions_pkg

    qr_mod = ModuleType("extensions._queue_registry")

    def _queue_consumer(queue_name: str, *, struct_type: Any, idempotent: bool = False, **_: Any):  # noqa: ANN202
        def decorator(fn):  # noqa: ANN001, ANN202
            fn._queue_name = queue_name
            fn._struct_type = struct_type
            fn._idempotent = idempotent
            return fn

        return decorator

    qr_mod.queue_consumer = _queue_consumer  # type: ignore[attr-defined]
    sys.modules["extensions._queue_registry"] = qr_mod


def _load_bot_conftest() -> ModuleType:
    """Load the bot test conftest by path to reuse its Fake guild/role/member trio.

    A bare ``import conftest`` resolves to the top-level ``apps/api/conftest.py`` under
    pytest's rootdir, not this package's conftest, so we load the fakes explicitly.
    """
    module_name = "bot_test_conftest"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = pathlib.Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_tournaments = _load_tournaments_module()
TournamentHandler = _tournaments.TournamentHandler

_bot_conftest = _load_bot_conftest()
FakeGuild = _bot_conftest.FakeGuild
FakeMember = _bot_conftest.FakeMember
FakeRole = _bot_conftest.FakeRole


def _make_handler(bot_api: AsyncMock, channel: Any, guild: Any | None = None) -> Any:
    """Build a TournamentHandler bypassing BaseHandler async init.

    BaseHandler.__init__ spawns an asyncio task to resolve the guild/channel after the
    bot is ready; we side-step that and inject the resolved attributes directly.
    """
    handler = object.__new__(TournamentHandler)
    handler.bot = SimpleNamespace(api=bot_api)
    handler.announcement_channel = channel
    if guild is not None:
        handler.guild = guild
    return handler


class FakeChannel:
    """A fake TextChannel recording send() calls."""

    def __init__(self) -> None:
        self.send_calls: list[dict[str, Any]] = []

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.send_calls.append({"args": args, "kwargs": kwargs})


def _started_event() -> TournamentCycleStartedEvent:
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    return TournamentCycleStartedEvent(
        cycle_id=42,
        category_id=1,
        map_id=7,
        map_code="ABCD1",
        map_name="Hanamura",
        started_at=now,
        ends_at=now + dt.timedelta(days=7),
    )


def _standings() -> list[TournamentLeaderboardEntryResponse]:
    return [
        TournamentLeaderboardEntryResponse(rank=1, user_id=111, name="alice", time=10.5, verified=True, completion=True),
        TournamentLeaderboardEntryResponse(rank=2, user_id=222, name="bob", time=12.0, verified=True, completion=True),
        TournamentLeaderboardEntryResponse(rank=3, user_id=333, name="cara", time=13.5, verified=True, completion=True),
        TournamentLeaderboardEntryResponse(rank=4, user_id=444, name="dan", time=20.0, verified=True, completion=True),
    ]


def _completed_event(winner_user_id: int | None = 111) -> TournamentCycleCompletedEvent:
    return TournamentCycleCompletedEvent(
        cycle_id=42, category_id=1, standings=_standings(), winner_user_id=winner_user_id
    )


def _view_text(view: Any) -> str:
    """Flatten every ui.TextDisplay in a CV2 LayoutView into one searchable string.

    The migrated handler/commands render ``ui.LayoutView`` (Container + TextDisplay
    sections) instead of an embed. ``walk_children()`` recurses into the container, so
    collecting every item exposing a string ``content`` reconstructs the visible card text.
    """
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(getattr(item, "content", None), str)
    )


# ---------------------------------------------------------------------------
# D-09 / D-10: edition rollover — ONE combined card, three conditional cases
# ---------------------------------------------------------------------------


def _rollover_handler(mock_api: AsyncMock, sample_category: TournamentCategoryResponse) -> tuple[Any, FakeChannel]:
    """Build a rollover handler with a champion role wired so transfers can run."""
    winner = FakeMember(member_id=111)
    role = FakeRole(role_id=sample_category.champion_role_id)
    guild = FakeGuild(roles={role.id: role}, members={111: winner})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)
    return handler, channel


@pytest.mark.asyncio
async def test_rollover_normal_renders_both_sections_and_transfers_champion(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-10 normal: results+started → both sections, champion transfer called, one send."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    started = _started_event()
    event = TournamentRolloverEvent(edition_id=7, results=[_completed_event()], started=[started])

    await handler._on_edition_rollover(event, None)

    assert len(channel.send_calls) == 1
    call = channel.send_calls[0]
    rendered = _view_text(call["kwargs"]["view"])
    # results section: top-3 podium + crowned winner, rank-4 absent, no XP line
    assert "<@111>" in rendered and "<@222>" in rendered and "<@333>" in rendered
    assert "<@444>" not in rendered
    assert "👑 <@111>" in rendered
    assert "XP" not in rendered.upper().replace("EXPERIENCE", "")
    # starting section: map link + difficulty
    assert "Hanamura" in rendered
    assert started.map_code in rendered
    assert "genji.pk/search" in rendered
    # champion transfer ran (category fetched for the results entry)
    mock_api.get_tournament_category.assert_any_await(1)
    # winner ping lives INSIDE the card (no content kwarg) gated by an allow-list
    assert "Congratulations <@111>!" in rendered
    assert "content" not in call["kwargs"]
    allowed = call["kwargs"]["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False


@pytest.mark.asyncio
async def test_rollover_into_hiatus_results_only_no_starting_section(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-10 into-hiatus: results only → results section, champion transfer runs, no starting section."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    event = TournamentRolloverEvent(edition_id=7, results=[_completed_event()], started=[])

    await handler._on_edition_rollover(event, None)

    assert len(channel.send_calls) == 1
    rendered = _view_text(channel.send_calls[0]["kwargs"]["view"])
    assert "👑 <@111>" in rendered  # results rendered
    assert "New Cycle" not in rendered  # no starting section
    # no map lookup happened (no started entries)
    mock_api.get_map.assert_not_awaited()
    # champion transfer still ran (category fetched once for the single results entry)
    mock_api.get_tournament_category.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_rollover_out_of_hiatus_started_only_no_transfer(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-10 out-of-hiatus: started only → starting section, NO champion transfer call."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    started = _started_event()
    event = TournamentRolloverEvent(edition_id=7, results=[], started=[started])

    await handler._on_edition_rollover(event, None)

    assert len(channel.send_calls) == 1
    rendered = _view_text(channel.send_calls[0]["kwargs"]["view"])
    assert "Hanamura" in rendered  # starting section rendered
    assert "Results" not in rendered  # no results section
    assert "Congratulations" not in rendered  # no winner ping
    # category fetched only for the started entry (results was empty → no transfer)
    mock_api.get_tournament_category.assert_awaited_once_with(started.category_id)
    mock_api.get_map.assert_awaited_once_with(code=started.map_code)


@pytest.mark.asyncio
async def test_rollover_empty_event_posts_nothing(mock_api: AsyncMock) -> None:
    """Defensive: a rollover with neither results nor started cycles does not post a card."""
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel)

    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[], started=[]), None)

    assert channel.send_calls == []


@pytest.mark.asyncio
async def test_rollover_results_empty_standings_renders_no_submissions(mock_api: AsyncMock) -> None:
    """D-10: a results entry with empty standings renders a 'No submissions' section, no crash."""
    role = FakeRole(role_id=999000111)
    guild = FakeGuild(roles={role.id: role}, members={})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    completed = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=[], winner_user_id=None)
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[completed], started=[]), None)

    assert len(channel.send_calls) == 1
    rendered = _view_text(channel.send_calls[0]["kwargs"]["view"])
    assert "No submissions" in rendered


# ---------------------------------------------------------------------------
# D-01 / D-04 / D-05: deferred results + held champion + results-pending placeholder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollover_results_pending_renders_placeholder_and_holds_champion(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-01/D-05: results_pending=True renders the 'pending' placeholder, start section, NO transfer.

    The poller emits this start-only rollover with EMPTY ``results`` so the transfer loop
    skips and the previous champion KEEPS the role (held). The real transfer happens later
    in ``_on_edition_results`` when the queue drains.
    """
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    started = _started_event()
    event = TournamentRolloverEvent(edition_id=7, results=[], started=[started], results_pending=True)

    await handler._on_edition_rollover(event, None)

    assert len(channel.send_calls) == 1
    rendered = _view_text(channel.send_calls[0]["kwargs"]["view"])
    # the placeholder renders in place of the results section
    assert "Results pending verification…" in rendered
    # the start section still renders on time (D-01)
    assert "Hanamura" in rendered
    assert started.map_code in rendered
    # champion held: NO transfer (empty results → no per-entry category fetch for transfer);
    # the only category fetch is for the started entry's render.
    mock_api.get_tournament_category.assert_awaited_once_with(started.category_id)
    # no winner ping (no results)
    assert "Congratulations" not in rendered


@pytest.mark.asyncio
async def test_on_edition_results_posts_card_and_transfers_champion(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-04/D-05: _on_edition_results posts a NEW results card and performs the held transfer."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    event = TournamentEditionResultsEvent(edition_id=7, results=[_completed_event()])

    await handler._on_edition_results(event, None)

    # one new card posted (D-04: separate announcement)
    assert len(channel.send_calls) == 1
    call = channel.send_calls[0]
    rendered = _view_text(call["kwargs"]["view"])
    # results section: top-3 podium + crowned winner, rank-4 absent
    assert "<@111>" in rendered and "<@222>" in rendered and "<@333>" in rendered
    assert "<@444>" not in rendered
    assert "👑 <@111>" in rendered
    # held champion transfer ran (category fetched for the results entry)
    mock_api.get_tournament_category.assert_any_await(1)
    # winner ping lives INSIDE the card (no content kwarg) gated by an allow-list (T-12.1-15)
    assert "Congratulations <@111>!" in rendered
    assert "content" not in call["kwargs"]
    allowed = call["kwargs"]["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False


@pytest.mark.asyncio
async def test_on_edition_results_calls_transfer_once_per_entry(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-05: _transfer_champion_role is called once per result entry (the held transfer)."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)

    transfer_calls: list[int] = []

    async def _spy_transfer(entry: Any, category: Any) -> None:
        transfer_calls.append(entry.cycle_id)

    monkeypatch.setattr(handler, "_transfer_champion_role", _spy_transfer)

    entry_a = TournamentCycleCompletedEvent(
        cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111
    )
    entry_b = TournamentCycleCompletedEvent(
        cycle_id=43, category_id=1, standings=_standings(), winner_user_id=222
    )
    event = TournamentEditionResultsEvent(edition_id=7, results=[entry_a, entry_b])

    await handler._on_edition_results(event, None)

    # transfer ran once per entry (the held transfer)
    assert transfer_calls == [42, 43]
    assert len(channel.send_calls) == 1


@pytest.mark.asyncio
async def test_on_edition_results_empty_standings_posts_no_winner_card_no_transfer(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pitfall 6: an empty/all-rejected edition posts a no-winner card and transfers nothing."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    stale = FakeMember(member_id=901)
    role = FakeRole(role_id=sample_category.champion_role_id, members=[stale])
    guild = FakeGuild(roles={role.id: role}, members={})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    completed = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=[], winner_user_id=None)
    event = TournamentEditionResultsEvent(edition_id=7, results=[completed])

    await handler._on_edition_results(event, None)

    # a no-winner card still posts
    assert len(channel.send_calls) == 1
    rendered = _view_text(channel.send_calls[0]["kwargs"]["view"])
    assert "No submissions" in rendered
    # No winner ping: the winner line is "Congratulations <@id>!" and is gated on having
    # winners. The unconditional "...Congratulations to this rotation's champions!" header
    # is always present, so assert the absence of the ping form, not the bare word.
    assert "Congratulations <@" not in rendered
    # nobody granted the role (vacant on None winner); the stale holder is stripped
    assert stale.add_roles_calls == []


@pytest.mark.asyncio
async def test_on_edition_results_mentions_winners_by_numeric_id_with_allow_list(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-12.1-15: winners are pinged ONLY by numeric <@id> with an AllowedMentions allow-list."""
    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())
    handler, channel = _rollover_handler(mock_api, sample_category)
    # a malicious free-text name must never reach a mention
    standings = [
        TournamentLeaderboardEntryResponse(
            rank=1, user_id=111, name="@everyone", time=9.5, verified=True, completion=True
        )
    ]
    completed = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=standings, winner_user_id=111)
    event = TournamentEditionResultsEvent(edition_id=7, results=[completed])

    await handler._on_edition_results(event, None)

    call = channel.send_calls[0]
    rendered = _view_text(call["kwargs"]["view"])
    assert "<@111>" in rendered
    assert "@everyone" not in rendered  # free-text name never interpolated into a mention
    allowed = call["kwargs"]["allowed_mentions"]
    assert [obj.id for obj in allowed.users] == [111]
    assert allowed.everyone is False
    assert allowed.roles is False


# ---------------------------------------------------------------------------
# DSC-03 / RWD-03: champion_role + champion_vacant + stagger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_champion_role_transfer_strips_all_then_grants(
    mock_api: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DSC-03 / RWD-03: strip champion role from ALL holders, then grant it to the winner."""

    stale1 = FakeMember(member_id=901)
    stale2 = FakeMember(member_id=902)
    winner = FakeMember(member_id=111)
    role = FakeRole(role_id=999000111, members=[stale1, stale2])
    guild = FakeGuild(roles={role.id: role}, members={111: winner})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111)
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[event], started=[]), None)

    # both stale holders stripped, each with a reason
    assert len(stale1.remove_roles_calls) == 1
    assert stale1.remove_roles_calls[0]["reason"]
    assert len(stale2.remove_roles_calls) == 1
    # winner granted, with a reason
    assert len(winner.add_roles_calls) == 1
    assert winner.add_roles_calls[0]["reason"]


@pytest.mark.asyncio
async def test_champion_vacant_when_no_winner(mock_api: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """DSC-03 / RWD-03: winner_user_id None strips all holders and grants to no one (D-05)."""

    stale1 = FakeMember(member_id=901)
    stale2 = FakeMember(member_id=902)
    role = FakeRole(role_id=999000111, members=[stale1, stale2])
    guild = FakeGuild(roles={role.id: role}, members={})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=[], winner_user_id=None)
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[event], started=[]), None)

    assert len(stale1.remove_roles_calls) == 1
    assert len(stale2.remove_roles_calls) == 1
    # nobody granted the role
    assert stale1.add_roles_calls == []
    assert stale2.add_roles_calls == []


@pytest.mark.asyncio
async def test_champion_no_role_configured_skips_transfer(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01: champion_role_id None (no role configured) → skip transfer, still post results."""
    import msgspec

    mock_api.get_tournament_category.return_value = msgspec.structs.replace(sample_category, champion_role_id=None)
    role = FakeRole(role_id=999000111, members=[FakeMember(member_id=901)])
    guild = FakeGuild(roles={role.id: role}, members={111: FakeMember(member_id=111)})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111)
    # No champion role configured: must not raise, must not touch any role, still posts results.
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[event], started=[]), None)

    assert role.members[0].remove_roles_calls == []  # no strip attempted
    assert len(channel.send_calls) == 1  # results embed still posts


@pytest.mark.asyncio
async def test_champion_member_left_guild_does_not_crash(
    mock_api: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DSC-03 / RWD-03: winner set but get_member None → log + continue, no crash, no grant."""

    stale1 = FakeMember(member_id=901)
    role = FakeRole(role_id=999000111, members=[stale1])
    guild = FakeGuild(roles={role.id: role}, members={})  # winner 111 not in cache
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    monkeypatch.setattr(_tournaments.asyncio, "sleep", AsyncMock())

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111)
    # must not raise (would DLQ a valid event)
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[event], started=[]), None)

    assert len(stale1.remove_roles_calls) == 1
    assert len(channel.send_calls) == 1  # results embed still posts


@pytest.mark.asyncio
async def test_role_ops_stagger_to_respect_rate_limits(
    mock_api: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DSC-03 / RWD-03: an inter-op delay (asyncio.sleep) occurs between member role edits."""

    stale1 = FakeMember(member_id=901)
    stale2 = FakeMember(member_id=902)
    winner = FakeMember(member_id=111)
    role = FakeRole(role_id=999000111, members=[stale1, stale2])
    guild = FakeGuild(roles={role.id: role}, members={111: winner})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    sleep_mock = AsyncMock()
    monkeypatch.setattr(_tournaments.asyncio, "sleep", sleep_mock)

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111)
    await handler._on_edition_rollover(TournamentRolloverEvent(edition_id=7, results=[event], started=[]), None)

    # at least one stagger sleep per stale-holder strip
    assert sleep_mock.await_count >= 2
    sleep_mock.assert_awaited_with(_tournaments._ROLE_OP_DELAY)


# ---------------------------------------------------------------------------
# Idempotency (via the real @queue_consumer wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_skips_duplicate_and_releases_claim_on_failure() -> None:
    """DSC-01/02: duplicate message_id skips the body; a handler exception releases the claim."""
    # Exercise the REAL queue_consumer wrapper (not the stub) so the idempotency
    # claim/skip/release path is what is under test.
    bot_root = _repo_root() / "apps" / "bot"
    if str(bot_root) not in sys.path:
        sys.path.insert(0, str(bot_root))
    qr_path = bot_root / "extensions" / "_queue_registry.py"
    spec = importlib.util.spec_from_file_location("real_queue_registry", qr_path)
    assert spec is not None and spec.loader is not None
    qr = importlib.util.module_from_spec(spec)
    sys.modules["real_queue_registry"] = qr
    spec.loader.exec_module(qr)

    body = TournamentCycleCompletedEvent(cycle_id=1, category_id=1, standings=[], winner_user_id=None)
    import msgspec  # noqa: PLC0415

    encoded = msgspec.json.encode(body)

    class FakeMessage:
        def __init__(self) -> None:
            self.headers: dict[str, Any] = {}
            self.body = encoded
            self.message_id = "tournament:cycle_completed:1"

    # --- duplicate skip ---
    body_called: list[int] = []

    @qr.queue_consumer("api.tournament.cycle_completed", struct_type=TournamentCycleCompletedEvent, idempotent=True)
    async def _h_skip(self: Any, event: Any, message: Any) -> None:  # noqa: ANN401
        body_called.append(1)

    api_dup = AsyncMock()
    api_dup.claim_idempotency.return_value = SimpleNamespace(claimed=False)
    svc_dup = SimpleNamespace(bot=SimpleNamespace(api=api_dup))
    await _h_skip(svc_dup, FakeMessage())
    assert body_called == []  # body never ran for a duplicate

    # --- release on failure ---
    @qr.queue_consumer("api.tournament.cycle_completed", struct_type=TournamentCycleCompletedEvent, idempotent=True)
    async def _h_fail(self: Any, event: Any, message: Any) -> None:  # noqa: ANN401
        raise RuntimeError("boom")

    api_fail = AsyncMock()
    api_fail.claim_idempotency.return_value = SimpleNamespace(claimed=True)
    svc_fail = SimpleNamespace(bot=SimpleNamespace(api=api_fail))
    with pytest.raises(RuntimeError):
        await _h_fail(svc_fail, FakeMessage())
    api_fail.delete_claimed_idempotency.assert_awaited_once()


# ---------------------------------------------------------------------------
# SUB-01 / D-04: non-PB tournament mod-review surface (Plan 11-05)
# ---------------------------------------------------------------------------

TournamentVerificationView = _tournaments.TournamentVerificationView
TournamentVerificationAcceptButton = _tournaments.TournamentVerificationAcceptButton
TournamentVerificationRejectButton = _tournaments.TournamentVerificationRejectButton


def _make_verification_handler(bot_api: AsyncMock, verification_channel: Any) -> Any:
    """Build a TournamentHandler with the verification channel injected."""
    handler = object.__new__(TournamentHandler)
    handler.bot = SimpleNamespace(api=bot_api)
    handler.verification_channel = verification_channel
    return handler


def _created_event() -> TournamentCompletionCreatedEvent:
    return TournamentCompletionCreatedEvent(
        completion_id=77,
        cycle_id=42,
        user_id=111,
        time=12.34,
        video="https://example.com/run.mp4",
        screenshot="https://example.com/proof.png",
    )


class _FakeInteractionResponse:
    """Records defer()/send_modal() interaction-response calls."""

    def __init__(self) -> None:
        self.deferred: list[dict[str, Any]] = []
        self.sent_modals: list[Any] = []

    async def defer(self, *args: Any, **kwargs: Any) -> None:
        self.deferred.append({"args": args, "kwargs": kwargs})

    async def send_modal(self, modal: Any) -> None:
        self.sent_modals.append(modal)


class _FakeMessage:
    """A fake message recording edit() calls."""

    def __init__(self) -> None:
        self.edit_calls: list[dict[str, Any]] = []

    async def edit(self, *args: Any, **kwargs: Any) -> None:
        self.edit_calls.append({"args": args, "kwargs": kwargs})


class _FakeFollowup:
    def __init__(self) -> None:
        self.sends: list[dict[str, Any]] = []

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.sends.append({"args": args, "kwargs": kwargs})


class _FakeButtonInteraction:
    """A fake interaction sufficient for the Accept/Reject button callbacks."""

    def __init__(self, api: AsyncMock) -> None:
        self.response = _FakeInteractionResponse()
        self.message = _FakeMessage()
        self.followup = _FakeFollowup()
        self.edit_original_calls: list[dict[str, Any]] = []
        self.user = SimpleNamespace(id=111)
        self.client = SimpleNamespace(api=api)

    async def edit_original_response(self, *args: Any, **kwargs: Any) -> None:
        self.edit_original_calls.append({"args": args, "kwargs": kwargs})


@pytest.mark.asyncio
async def test_completion_created_posts_accept_reject_view() -> None:
    """SUB-01: the completion-created consumer posts an Accept/Reject view to the queue."""
    api = AsyncMock()
    channel = FakeChannel()
    handler = _make_verification_handler(api, channel)

    await handler._on_completion_created(_created_event(), None)

    assert len(channel.send_calls) == 1
    kwargs = channel.send_calls[0]["kwargs"]
    view = kwargs["view"]
    assert isinstance(view, TournamentVerificationView)
    assert view.completion_id == 77
    # mention-injection mitigation on the posted card
    allowed = kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False


@pytest.mark.asyncio
async def test_accept_button_calls_verify_tournament_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUB-01 / D-04: clicking Accept routes the verdict to verify_tournament_completion."""
    api = AsyncMock()
    api.verify_tournament_completion.return_value = SimpleNamespace(id="job-1")
    monkeypatch.setattr(
        _tournaments, "poll_job_until_complete", AsyncMock(return_value=SimpleNamespace(status="succeeded"))
    )

    bot = SimpleNamespace(api=api)
    view = TournamentVerificationView(_created_event(), bot)  # type: ignore[arg-type]
    button = next(c for c in view.walk_children() if isinstance(c, TournamentVerificationAcceptButton))
    itx = _FakeButtonInteraction(api)

    await button.callback(itx)  # type: ignore[arg-type]

    api.verify_tournament_completion.assert_awaited_once_with(77)
    api.reject_tournament_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_button_calls_reject_tournament_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUB-01 / D-04: clicking Reject (with a reason) routes to reject_tournament_completion."""
    api = AsyncMock()
    bot = SimpleNamespace(api=api)
    view = TournamentVerificationView(_created_event(), bot)  # type: ignore[arg-type]
    button = next(c for c in view.walk_children() if isinstance(c, TournamentVerificationRejectButton))
    itx = _FakeButtonInteraction(api)

    # Stub the modal so wait() returns immediately with a non-empty reason.
    class _StubModal:
        def __init__(self) -> None:
            self.reason = SimpleNamespace(value="not a valid run")

        async def wait(self) -> None:
            return None

    monkeypatch.setattr(_tournaments, "TournamentRejectionReasonModal", _StubModal)

    await button.callback(itx)  # type: ignore[arg-type]

    api.reject_tournament_completion.assert_awaited_once_with(77)
    api.verify_tournament_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_reject_button_empty_reason_cancels(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty reject reason cancels the reject — no API call is made."""
    api = AsyncMock()
    bot = SimpleNamespace(api=api)
    view = TournamentVerificationView(_created_event(), bot)  # type: ignore[arg-type]
    button = next(c for c in view.walk_children() if isinstance(c, TournamentVerificationRejectButton))
    itx = _FakeButtonInteraction(api)

    class _EmptyModal:
        def __init__(self) -> None:
            self.reason = SimpleNamespace(value="")

        async def wait(self) -> None:
            return None

    monkeypatch.setattr(_tournaments, "TournamentRejectionReasonModal", _EmptyModal)

    await button.callback(itx)  # type: ignore[arg-type]

    api.reject_tournament_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_verification_changed_posts_no_per_run_message() -> None:
    """The per-run verdict message was dropped (commit d2554d6): the consumer is now a no-op.

    `_on_verification_changed` only logs the verdict for observability and posts nothing to
    the verification channel.
    """
    api = AsyncMock()
    channel = FakeChannel()
    handler = _make_verification_handler(api, channel)

    event = TournamentVerificationChangedEvent(
        tournament_completion_id=77, cycle_id=42, user_id=111, verified=True, time=12.34
    )
    await handler._on_verification_changed(event, None)

    assert channel.send_calls == []
