"""API route/scope integration tests for the GLOBAL tournament config endpoints.

This file covers the config-level (NOT per-category) mutation surface introduced
in Phase 12 Plan 04:

- ``PATCH /api/v3/tournaments/pause``               (tournaments:write)
- ``PATCH /api/v3/tournaments/debug-cycle-length``  (tournaments:write)
- ``PATCH /api/v3/tournaments/config``  (cadence/anchor, tournaments:write)
- ``GET  /api/v3/tournaments/editions/active``      (tournaments:read)

It asserts the threat-register mitigations:

- T-12-09 (Elevation of Privilege): every config MUTATION route rejects an
  unauthenticated caller (401) and a wrong-scope (read-only, non-superuser)
  caller (403); a tournaments:write caller succeeds.
- T-12-07 (debug route in production): the debug-cycle-length route is rejected
  with 403 when ``APP_ENVIRONMENT == 'production'``.
- The edition read surfaces the STORED started_at + ends_at (D-05/D-08).

NOTE: this is the API route/scope test. ``tests/bot/test_config_tournament.py``
is an unrelated BOT TOML config test (channel/role IDs) and is NOT mirrored here.
"""

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pytest_databases.docker.postgres import PostgresService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_tournaments,
]

BASE = "/api/v3/tournaments"


def _dsn(svc: PostgresService) -> str:
    return f"postgresql://{svc.user}:{svc.password}@{svc.host}:{svc.port}/{svc.database}"


@pytest.fixture
async def read_only_client(
    postgres_service: PostgresService,
    asyncpg_pool,
) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Client authenticated as a NON-superuser holding ONLY ``tournaments:read``.

    Used to prove wrong-scope rejection (403) on the config mutation routes: the
    seeded ``testing`` token is a superuser and bypasses scope checks, so a
    dedicated scoped token is required to exercise the guard.
    """
    from app import create_app

    api_key = f"ro-{uuid4().hex[:12]}"
    async with asyncpg_pool.acquire() as conn:
        user_id = await conn.fetchval(
            "INSERT INTO public.auth_users (username, info) VALUES ($1, $2) RETURNING id",
            f"readonly-{uuid4().hex[:8]}",
            "tournaments:read only",
        )
        await conn.execute(
            """
            INSERT INTO public.api_tokens (user_id, api_key, is_superuser, scopes)
            VALUES ($1, $2, FALSE, $3)
            """,
            user_id,
            api_key,
            ["tournaments:read"],
        )

    app = create_app(psql_dsn=_dsn(postgres_service))
    async with AsyncTestClient(app=app) as client:
        client.headers.update({"x-pytest-enabled": "1", "X-API-KEY": api_key})
        yield client


# ---------------------------------------------------------------------------
# Mutation routes — unauthenticated (401) + wrong-scope (403) rejection (T-12-09)
# ---------------------------------------------------------------------------


class TestPauseScopeGuard:
    """PATCH /api/v3/tournaments/pause (tournaments:write)."""

    async def test_unauthenticated_rejected(self, unauthenticated_client):
        """No API key → 401."""
        response = await unauthenticated_client.patch(f"{BASE}/pause", json={"paused": True})
        assert response.status_code == 401

    async def test_wrong_scope_rejected(self, read_only_client):
        """A read-only (non-superuser) caller is rejected (401/403).

        The scope guard raises ``NotAuthorizedException`` (HTTP 401) for a missing
        ``tournaments:write`` scope; the plan accepts 401/403 for the wrong-scope
        rejection (T-12-09). The key assertion is that a scoped read-only token
        canNOT mutate global config.
        """
        response = await read_only_client.patch(f"{BASE}/pause", json={"paused": True})
        assert response.status_code in (401, 403)

    async def test_write_scope_accepted(self, test_client):
        """A tournaments:write (superuser) caller succeeds and toggles the flag."""
        response = await test_client.patch(f"{BASE}/pause", json={"paused": True})
        assert response.status_code == 200
        assert response.json()["transitions_paused"] is True

        # Resume to leave global state clean for sibling tests.
        resume = await test_client.patch(f"{BASE}/pause", json={"paused": False})
        assert resume.status_code == 200
        assert resume.json()["transitions_paused"] is False


class TestDebugCycleLengthScopeGuard:
    """PATCH /api/v3/tournaments/debug-cycle-length (tournaments:write)."""

    async def test_unauthenticated_rejected(self, unauthenticated_client):
        """No API key → 401."""
        response = await unauthenticated_client.patch(f"{BASE}/debug-cycle-length", json={"seconds": 60})
        assert response.status_code == 401

    async def test_wrong_scope_rejected(self, read_only_client):
        """A read-only (non-superuser) caller is rejected (401/403)."""
        response = await read_only_client.patch(f"{BASE}/debug-cycle-length", json={"seconds": 60})
        assert response.status_code in (401, 403)

    async def test_write_scope_accepted(self, test_client):
        """A tournaments:write caller succeeds (non-production); clears afterwards."""
        response = await test_client.patch(f"{BASE}/debug-cycle-length", json={"seconds": 60})
        assert response.status_code == 200
        assert response.json()["debug_cycle_seconds"] == 60

        clear = await test_client.patch(f"{BASE}/debug-cycle-length", json={"seconds": None})
        assert clear.status_code == 200
        assert clear.json()["debug_cycle_seconds"] is None

    async def test_rejected_in_production(self, test_client, monkeypatch):
        """T-12-07: the debug route is rejected with 403 in production (service guard)."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        response = await test_client.patch(f"{BASE}/debug-cycle-length", json={"seconds": 60})
        assert response.status_code == 403


class TestCadenceAnchorScopeGuard:
    """PATCH /api/v3/tournaments/config (cadence/anchor, tournaments:write)."""

    async def test_cadence_unauthenticated_rejected(self, unauthenticated_client):
        """No API key → 401 on the cadence mutation."""
        response = await unauthenticated_client.patch(f"{BASE}/config", json={"cadence": "biweekly"})
        assert response.status_code == 401

    async def test_cadence_wrong_scope_rejected(self, read_only_client):
        """A read-only (non-superuser) caller is rejected (401/403) on the cadence mutation."""
        response = await read_only_client.patch(f"{BASE}/config", json={"cadence": "biweekly"})
        assert response.status_code in (401, 403)

    async def test_cadence_write_scope_accepted(self, test_client):
        """A tournaments:write caller can set the global cadence (D-02)."""
        response = await test_client.patch(f"{BASE}/config", json={"cadence": "biweekly"})
        assert response.status_code == 200
        assert response.json()["cadence"] == "biweekly"
        # Restore the default cadence.
        await test_client.patch(f"{BASE}/config", json={"cadence": "weekly"})

    async def test_anchor_wrong_scope_rejected(self, read_only_client):
        """A read-only caller is rejected (401/403) on the anchor mutation."""
        response = await read_only_client.patch(
            f"{BASE}/config",
            json={"anchor_weekday": 1, "anchor_time": "12:00:00", "anchor_tz": "UTC"},
        )
        assert response.status_code in (401, 403)

    async def test_anchor_write_scope_accepted(self, test_client):
        """A tournaments:write caller can set the grid anchor (D-07)."""
        response = await test_client.patch(
            f"{BASE}/config",
            json={"anchor_weekday": 1, "anchor_time": "12:00:00", "anchor_tz": "America/New_York"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["anchor_weekday"] == 1
        assert data["anchor_tz"] == "America/New_York"

    async def test_invalid_anchor_tz_rejected(self, test_client):
        """T-12-10: an unknown anchor_tz is rejected (422) before persisting."""
        response = await test_client.patch(
            f"{BASE}/config",
            json={"anchor_tz": "Not/AReal_Zone"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Edition read surface (D-05/D-08) — stored started_at + ends_at
# ---------------------------------------------------------------------------


class TestActiveEditionRead:
    """GET /api/v3/tournaments/editions/active (tournaments:read)."""

    async def test_unauthenticated_rejected(self, unauthenticated_client):
        """No API key → 401."""
        response = await unauthenticated_client.get(f"{BASE}/editions/active")
        assert response.status_code == 401

    async def test_returns_stored_timing(self, test_client, asyncpg_pool):
        """An active edition's STORED started_at + ends_at are returned verbatim (D-08)."""
        async with asyncpg_pool.acquire() as conn:
            # Clear any active edition so this seed is unambiguously the active one.
            await conn.execute("UPDATE tournaments.editions SET status = 'completed' WHERE status = 'active'")
            edition_id = await conn.fetchval(
                """
                INSERT INTO tournaments.editions (started_at, ends_at, status)
                VALUES ('2030-01-07 00:00:00+00', '2030-01-14 00:00:00+00', 'active')
                RETURNING id
                """,
            )

        response = await test_client.get(f"{BASE}/editions/active")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == edition_id
        assert data["status"] == "active"
        assert "started_at" in data
        assert "ends_at" in data
        # ends_at is STORED, not derived: it matches the seeded value, not now()+period.
        assert data["started_at"].startswith("2030-01-07")
        assert data["ends_at"].startswith("2030-01-14")

        # Reset so the seeded future edition does not leak into sibling tests.
        async with asyncpg_pool.acquire() as conn:
            await conn.execute("UPDATE tournaments.editions SET status = 'completed' WHERE id = $1", edition_id)

    async def test_no_active_edition_returns_404(self, test_client, asyncpg_pool):
        """With no active edition the read returns 404 (NoActiveEditionError)."""
        async with asyncpg_pool.acquire() as conn:
            await conn.execute("UPDATE tournaments.editions SET status = 'completed' WHERE status = 'active'")

        response = await test_client.get(f"{BASE}/editions/active")
        assert response.status_code == 404
