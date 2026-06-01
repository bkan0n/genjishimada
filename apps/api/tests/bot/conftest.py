"""Shared fixtures for bot unit tests.

Provides:
- ``bot_repo_root`` / ``load_bot_config``: load the bot's msgspec ``Config`` struct by
  file path (avoids the ``utilities`` package-name collision between apps/api and apps/bot).
- A fake guild/role/member trio that records ``add_roles``/``remove_roles`` calls so the
  champion-transfer handler tests (Plan 09-02) can assert role operations without a live guild.
- A mock ``APIService`` whose ``get_tournament_category`` returns a ``TournamentCategoryResponse``
  and whose ``get_map`` returns a MapModel-shaped object exposing ``.difficulty``,
  ``.map_name`` and ``.map_banner``.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from genjishimada_sdk.tournaments import TournamentCategoryResponse


def _repo_root() -> pathlib.Path:
    """Return the monorepo root (the directory containing ``apps/``)."""
    # this file: <root>/apps/api/tests/bot/conftest.py
    return pathlib.Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def bot_repo_root() -> pathlib.Path:
    """Return the monorepo root directory."""
    return _repo_root()


@pytest.fixture(scope="session")
def bot_config_module() -> ModuleType:
    """Load apps/bot/utilities/config.py by file path as an isolated module.

    Loading by path avoids importing apps/api's ``utilities`` package, which would
    shadow the bot's ``utilities.config`` when both source trees are importable.
    """
    config_path = _repo_root() / "apps" / "bot" / "utilities" / "config.py"
    module_name = "bot_utilities_config"
    spec = importlib.util.spec_from_file_location(module_name, config_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so msgspec can resolve forward-ref annotations
    # (the module uses ``from __future__ import annotations``) against the
    # module globals via sys.modules[cls.__module__] at convert time.
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fake guild / role / member trio
# ---------------------------------------------------------------------------


class FakeMember:
    """A fake discord.Member recording add_roles / remove_roles calls."""

    def __init__(self, member_id: int, roles: list[FakeRole] | None = None) -> None:
        self.id = member_id
        self.roles: list[FakeRole] = roles or []
        self.add_roles_calls: list[dict[str, Any]] = []
        self.remove_roles_calls: list[dict[str, Any]] = []

    async def add_roles(self, *roles: FakeRole, reason: str | None = None) -> None:
        self.add_roles_calls.append({"roles": roles, "reason": reason})
        for role in roles:
            if role not in self.roles:
                self.roles.append(role)
            if self not in role.members:
                role.members.append(self)

    async def remove_roles(self, *roles: FakeRole, reason: str | None = None) -> None:
        self.remove_roles_calls.append({"roles": roles, "reason": reason})
        for role in roles:
            if role in self.roles:
                self.roles.remove(role)
            if self in role.members:
                role.members.remove(self)


class FakeRole:
    """A fake discord.Role exposing a mutable members list and identity."""

    def __init__(self, role_id: int, members: list[FakeMember] | None = None) -> None:
        self.id = role_id
        self.members: list[FakeMember] = members or []


class FakeGuild:
    """A fake discord.Guild exposing get_role(id) and get_member(id)."""

    def __init__(
        self,
        roles: dict[int, FakeRole] | None = None,
        members: dict[int, FakeMember] | None = None,
    ) -> None:
        self._roles: dict[int, FakeRole] = roles or {}
        self._members: dict[int, FakeMember] = members or {}

    def get_role(self, role_id: int) -> FakeRole | None:
        return self._roles.get(role_id)

    def get_member(self, member_id: int) -> FakeMember | None:
        return self._members.get(member_id)


@pytest.fixture
def fake_role() -> FakeRole:
    """Return a fake champion role with no holders by default."""
    return FakeRole(role_id=999000111)


@pytest.fixture
def fake_member() -> FakeMember:
    """Return a fake member recording add_roles / remove_roles calls."""
    return FakeMember(member_id=555000222)


@pytest.fixture
def fake_guild(fake_role: FakeRole, fake_member: FakeMember) -> FakeGuild:
    """Return a fake guild wiring the fake role + member together."""
    return FakeGuild(
        roles={fake_role.id: fake_role},
        members={fake_member.id: fake_member},
    )


# ---------------------------------------------------------------------------
# Sample API payloads + mock APIService
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_category() -> TournamentCategoryResponse:
    """Return a sample TournamentCategoryResponse with a champion role id."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    # Cadence is GLOBAL since migration 0024 — no per-category cycle_frequency (D-02).
    return TournamentCategoryResponse(
        id=1,
        name="Hard",
        difficulties=["Hard"],
        participation_xp=100,
        placement_xp=[],
        streak_xp=[],
        champion_role_id=999000111,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_map() -> SimpleNamespace:
    """Return a MapModel-shaped object exposing difficulty / map_name / map_banner."""
    return SimpleNamespace(
        difficulty="Hard",
        map_name="Hanamura",
        map_banner="https://cdn.genji.pk/banners/hanamura.png",
    )


@pytest.fixture
def mock_api(sample_category: TournamentCategoryResponse, sample_map: SimpleNamespace) -> AsyncMock:
    """Return a mock APIService returning the sample category + map.

    ``get_tournament_category`` resolves to ``sample_category`` and ``get_map`` resolves
    to ``sample_map`` (MapModel-shaped). Plan 09-02 can override these per-test.
    """
    api = AsyncMock()
    api.get_tournament_category.return_value = sample_category
    api.get_map.return_value = sample_map
    return api
