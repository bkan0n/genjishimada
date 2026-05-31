"""Unit tests for the tournament announcement handler (Plan 09-02).

Each test maps to one behavior in the Phase 9 VALIDATION map and is named so the
documented ``-k`` selector picks exactly one group:

- ``-k cycle_started``     → DSC-01: new-cycle embed posted after fetching category + map
- ``-k results_embed``     → DSC-02: Top-3 results embed (no XP line, D-03)
- ``-k champion_role``     → DSC-03 / RWD-03: strip role from all holders then grant to winner
- ``-k champion_vacant``   → DSC-03 / RWD-03: winner_user_id is None → strip-all, leave vacant (D-05)
- ``-k stagger``           → DSC-03 / RWD-03: role ops staggered to respect Discord rate limits
- ``-k idempotency``       → DSC-01/02: cycle-scoped dedupe; claim released on failure

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
    TournamentLeaderboardEntryResponse,
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


# ---------------------------------------------------------------------------
# DSC-01: cycle_started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_started_posts_new_cycle_embed(mock_api: AsyncMock, sample_map: SimpleNamespace) -> None:
    """DSC-01: cycle_started consumer fetches category + map and posts the new-cycle embed."""
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel)
    event = _started_event()

    await handler._on_cycle_started(event, None)

    mock_api.get_tournament_category.assert_awaited_once_with(event.category_id)
    mock_api.get_map.assert_awaited_once_with(code=event.map_code)
    assert len(channel.send_calls) == 1
    embed = channel.send_calls[0]["kwargs"]["embed"]
    rendered = (embed.title or "") + (embed.description or "")
    rendered += "".join(f"{f.name}{f.value}" for f in embed.fields)
    assert "Hanamura" in rendered
    assert "Hard" in rendered  # difficulty + category name
    assert event.map_code in rendered  # workshop code surfaced
    assert "workshop.codes" in rendered  # clickable link
    # thumbnail set from the (non-null) banner
    assert embed.thumbnail.url == sample_map.map_banner


@pytest.mark.asyncio
async def test_cycle_started_no_thumbnail_when_banner_none(mock_api: AsyncMock) -> None:
    """DSC-01: a null map_banner does not crash; embed still posts with no thumbnail."""
    mock_api.get_map.return_value = SimpleNamespace(difficulty="Hard", map_name="Hanamura", map_banner=None)
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel)

    await handler._on_cycle_started(_started_event(), None)

    assert len(channel.send_calls) == 1
    embed = channel.send_calls[0]["kwargs"]["embed"]
    assert embed.thumbnail.url is None


# ---------------------------------------------------------------------------
# DSC-02 / D-03 / D-06: results_embed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_completed_posts_results_embed(
    mock_api: AsyncMock, sample_category: TournamentCategoryResponse
) -> None:
    """DSC-02: cycle_completed posts ONE Top-3 results embed with a winner ping and NO XP line."""

    winner = FakeMember(member_id=111)
    role = FakeRole(role_id=sample_category.champion_role_id)
    guild = FakeGuild(roles={role.id: role}, members={111: winner})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=_standings(), winner_user_id=111)
    await handler._on_cycle_completed(event, None)

    assert len(channel.send_calls) == 1
    call = channel.send_calls[0]
    embed = call["kwargs"]["embed"]
    rendered = (embed.title or "") + (embed.description or "")
    rendered += "".join(f"{f.name}{f.value}" for f in embed.fields)
    # Top-3 standings present, rank-4 absent
    assert "<@111>" in rendered and "<@222>" in rendered and "<@333>" in rendered
    assert "<@444>" not in rendered
    # crowned Champion line folded in
    assert "Champion" in rendered
    # NO XP line anywhere
    assert "XP" not in rendered.upper().replace("EXPERIENCE", "")
    # winner pinged via content; allowed_mentions restricts to the winner only
    assert call["kwargs"]["content"] == "<@111>"
    allowed = call["kwargs"]["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False


@pytest.mark.asyncio
async def test_cycle_completed_results_embed_empty_standings(mock_api: AsyncMock) -> None:
    """DSC-02: empty standings render a 'No submissions' podium and do not crash."""

    role = FakeRole(role_id=999000111)
    guild = FakeGuild(roles={role.id: role}, members={})
    channel = FakeChannel()
    handler = _make_handler(mock_api, channel, guild=guild)

    event = TournamentCycleCompletedEvent(cycle_id=42, category_id=1, standings=[], winner_user_id=None)
    await handler._on_cycle_completed(event, None)

    assert len(channel.send_calls) == 1
    embed = channel.send_calls[0]["kwargs"]["embed"]
    rendered = "".join(f"{f.name}{f.value}" for f in embed.fields)
    assert "No submissions" in rendered


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
    await handler._on_cycle_completed(event, None)

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
    await handler._on_cycle_completed(event, None)

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
    await handler._on_cycle_completed(event, None)

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
    await handler._on_cycle_completed(event, None)

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
    await handler._on_cycle_completed(event, None)

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
async def test_verification_changed_surfaces_verdict() -> None:
    """The verification-changed consumer posts the verdict with mention mitigation."""
    api = AsyncMock()
    channel = FakeChannel()
    handler = _make_verification_handler(api, channel)

    event = TournamentVerificationChangedEvent(
        tournament_completion_id=77, cycle_id=42, user_id=111, verified=True, time=12.34
    )
    await handler._on_verification_changed(event, None)

    assert len(channel.send_calls) == 1
    kwargs = channel.send_calls[0]["kwargs"]
    assert "verified" in kwargs["content"]
    assert "<@111>" in kwargs["content"]
    allowed = kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False
