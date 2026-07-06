---
phase: quick-260629-caz
plan: 01
type: tdd
wave: 1
depends_on: []
files_modified:
  - apps/api/tests/repository/store/test_store_repository_quests.py
  - libs/sdk/src/genjishimada_sdk/store.py
  - apps/api/repository/store_repository.py
  - apps/api/services/store_service.py
  - apps/api/routes/v3/store.py
autonomous: true
requirements: [QUICK-260629-caz]

must_haves:
  truths:
    - "GET /api/v3/store/admin/quests returns a bare JSON array of all 19 global quest-pool entries (no pagination)."
    - "The endpoint filters quest_type='global' — bounty quests never appear."
    - "Filters is_active, difficulty, and q (name search, case-insensitive partial) narrow the result set."
    - "The endpoint requires scope store:admin."
  artifacts:
    - path: "libs/sdk/src/genjishimada_sdk/store.py"
      provides: "QuestPoolResponse struct (admin pool entry)"
      contains: "class QuestPoolResponse"
    - path: "apps/api/repository/store_repository.py"
      provides: "get_all_quests dynamic-WHERE query method"
      contains: "async def get_all_quests"
    - path: "apps/api/services/store_service.py"
      provides: "get_all_quests service method returning list[QuestPoolResponse]"
      contains: "async def get_all_quests"
    - path: "apps/api/routes/v3/store.py"
      provides: "GET /admin/quests list_quests handler"
      contains: "/admin/quests"
    - path: "apps/api/tests/repository/store/test_store_repository_quests.py"
      provides: "get_all_quests coverage (count, global-only, filters)"
      contains: "get_all_quests"
  key_links:
    - from: "apps/api/routes/v3/store.py"
      to: "store_service.get_all_quests"
      via: "handler delegation"
      pattern: "get_all_quests"
    - from: "apps/api/services/store_service.py"
      to: "self._store_repo.get_all_quests"
      via: "repository call + msgspec.convert"
      pattern: "self\\._store_repo\\.get_all_quests"
    - from: "apps/api/repository/store_repository.py"
      to: "store.quests"
      via: "SELECT ... WHERE quest_type = 'global'"
      pattern: "quest_type = 'global'"
---

<objective>
Add a `GET /api/v3/store/admin/quests` endpoint (scope `store:admin`) that lists ALL global quest-pool entries for the admin pool browser. Returns a bare JSON array, no pagination (pool is ~19 rows). Supports optional filters: `is_active`, `difficulty`, and `q` (case-insensitive partial name search). Scoped to `quest_type='global'` only.

Purpose: The admin pool browser needs to see every global quest definition (not just the active rotation), with light client-side filtering.
Output: New `QuestPoolResponse` SDK struct, `get_all_quests` repo + service methods, a `list_quests` route handler, and repository tests.

Built TDD: failing test FIRST, then SDK -> repository -> service -> route.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Confirmed by investigation + file reads. Use directly — no codebase exploration needed. -->

store.quests table (migration 0014_quests_system.sql, lines 10-21):
  id int identity PK, name text, description text,
  quest_type text CHECK in ('global','bounty'), difficulty text CHECK in ('easy','medium','hard'),
  coin_reward int, xp_reward int, requirements jsonb,
  is_active boolean DEFAULT true, created_at timestamptz DEFAULT now().
  All 19 seeded rows are quest_type='global'. Existing selection SQL consistently filters WHERE quest_type='global'.

jsonb codec (apps/api/app.py _async_pg_init): decodes jsonb -> Python dict, so `requirements` is already a dict after dict(row).

libs/sdk/src/genjishimada_sdk/store.py:
  - `import datetime as dt` already present at line 5; `from msgspec import UNSET, Struct, UnsetType` at line 9.
  - `QuestResponse` struct ends at line 636. Add QuestPoolResponse immediately after it.

libs/sdk/src/genjishimada_sdk/__init__.py:
  - The `store` MODULE is re-exported (line 18 imports `store`, line 37 lists `"store"` in __all__) — there is NO per-struct re-export list.
  - The route and service import store structs DIRECTLY from `genjishimada_sdk.store`, so QuestPoolResponse resolves with NO __init__.py edit. Do NOT touch __init__.py.

apps/api/repository/store_repository.py:
  - `StoreRepository.update_quest` (~line 1038) targets store.quests, shows the `requirements = $N::jsonb` handling and the `self._get_connection(conn)` + `idx`/`values` positional accumulation pattern to mirror.
  - `provide_store_repository` at ~line 1064 — add the new method ABOVE it.

apps/api/services/store_service.py:
  - Imports store structs from `genjishimada_sdk.store` (import block lines 15-37, alphabetical). Add QuestPoolResponse there.
  - `msgspec` imported (line 11). Repo attribute is `self._store_repo`.
  - `get_user_purchases` (~line 420) is the cleanest neighboring read pattern:
        rows = await self._store_repo.fetch_user_purchases(...)
        return msgspec.convert({...}, PurchaseHistoryResponse)
    Mirror its shape (repo call -> msgspec.convert). No connection acquire — the repo method owns its connection via _get_connection.

apps/api/routes/v3/store.py:
  - `StoreController` has `path = "/store"` (line 66).
  - Imports store structs alphabetically from `genjishimada_sdk.store` (lines 9-32). Add QuestPoolResponse.
  - `Annotated` already imported (line 5); `litestar` imported; existing admin handlers use `opt={"required_scopes": {"store:admin"}}`.
  - Sibling admin paths: `/admin/quests/config` (GET/PUT), `/admin/quests/rotation/generate` (POST), `/admin/quests/{quest_id:int}` (PATCH). New static `/admin/quests` (GET) is a DISTINCT path — no routing conflict.
  - Handler shape to mirror (get_quest_history, ~line 286):
        async def get_quest_history(self, store_service: StoreService, user_id: int, limit: int = 20, offset: int = 0) -> QuestHistoryResponse:
            return await store_service.get_user_quest_history(user_id, limit, offset)

apps/api/tests/repository/store/test_store_repository_quests.py:
  - Test layer is REPOSITORY (matches existing store quest tests). Fixtures: `repository` (StoreRepository(asyncpg_conn)) and `asyncpg_conn`.
  - `pytestmark = [pytest.mark.domain_store]` at module top.
  - The 19 global quests are seeded by migrations into the test DB (migrations applied at session start).
  - Insert style used in-file:
        INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements)
        VALUES ('Test Quest', 'Test', 'global', 'easy', 1, 1, '{}'::jsonb)
  - Test files are exempt from lint per CLAUDE.md.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Write failing repository tests for get_all_quests (RED)</name>
  <files>apps/api/tests/repository/store/test_store_repository_quests.py</files>
  <behavior>
    Add a `TestGetAllQuests` class to the existing repository test file. Use the existing `repository` and `asyncpg_conn` fixtures; module already has `pytestmark = [pytest.mark.domain_store]`.
    - Test A (count + global-only): `await repository.get_all_quests()` returns >= 19 rows; every row has `quest_type == "global"`.
    - Test B (difficulty filter): `await repository.get_all_quests(difficulty="easy")` — every returned row has `difficulty == "easy"`, and the count is strictly fewer than the unfiltered total (the pool has mixed difficulties).
    - Test C (is_active filter): insert one inactive global quest (`is_active=false`) via `asyncpg_conn`, then assert it appears in `get_all_quests(is_active=False)` and in unfiltered `get_all_quests()`, but NOT in `get_all_quests(is_active=True)`.
    - Test D (name_query case-insensitive partial): fetch one seeded quest name via `asyncpg_conn` (avoid hardcoding), take a lowercased substring of it, and assert `get_all_quests(name_query=<lower-substr>)` returns at least that row and every returned row's `name` contains the substring case-insensitively.
  </behavior>
  <action>Add the `TestGetAllQuests` class. These tests MUST fail initially because `get_all_quests` does not yet exist (AttributeError / collection-time call error) — that is the RED state. Do NOT implement the method in this task. Reuse the file's existing `StoreRepository` import and the module fixtures. Insert any test-only inactive quest mirroring the in-file insert style, adding the `is_active` column: `INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements, is_active) VALUES (..., 'global', 'easy', 1, 1, '{}'::jsonb, false)`. Tests are lint-exempt.</action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --project apps/api pytest apps/api/tests/repository/store/test_store_repository_quests.py -k GetAllQuests -x 2>&1 | tail -20</automated>
  </verify>
  <done>The four new tests exist and FAIL (AttributeError on `get_all_quests`), confirming RED.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement SDK struct + repository + service (GREEN)</name>
  <files>libs/sdk/src/genjishimada_sdk/store.py, apps/api/repository/store_repository.py, apps/api/services/store_service.py</files>
  <behavior>
    After implementation, the Task 1 tests pass. `get_all_quests()` returns all global rows; filters narrow correctly; rows convert cleanly to `QuestPoolResponse`.
  </behavior>
  <action>
Three changes:

1. SDK struct — in `libs/sdk/src/genjishimada_sdk/store.py`, add immediately after `QuestResponse` (~line 636):
   `class QuestPoolResponse(Struct):` with a one-line Google-style docstring ("A global quest pool entry (admin pool browser)."), fields in this exact order and type: `id: int`, `name: str`, `description: str`, `quest_type: str`, `difficulty: str`, `coin_reward: int`, `xp_reward: int`, `requirements: dict`, `is_active: bool`, `created_at: dt.datetime`. Reuse the existing `import datetime as dt` (line 5) — do not add a new import. Do NOT edit `__init__.py`.

2. Repository — in `apps/api/repository/store_repository.py`, add `get_all_quests` ABOVE `provide_store_repository`:
   signature `async def get_all_quests(self, *, is_active: bool | None = None, difficulty: str | None = None, name_query: str | None = None, conn: Connection | None = None) -> list[dict]:` with a Google-style docstring.
   Use `_conn = self._get_connection(conn)`. Build a dynamic WHERE: always start with the literal `quest_type = 'global'` in the SQL (NOT a bind param — endpoint is global-only). Append `is_active = $N` when `is_active is not None`; `difficulty = $N` when `difficulty is not None`; `name ILIKE $N` with bound value `f"%{name_query}%"` when `name_query` is truthy. Use a positional counter starting at 1 over an accumulating `values: list[object]` list, mirroring `update_quest`'s `idx`/`values` style. SELECT exactly the 10 columns `id, name, description, quest_type, difficulty, coin_reward, xp_reward, requirements, is_active, created_at` and `ORDER BY id`. Execute `rows = await _conn.fetch(query, *values)` and `return [dict(row) for row in rows]`. (The jsonb codec makes `requirements` already a dict.)

3. Service — in `apps/api/services/store_service.py`, add `QuestPoolResponse` to the alphabetical `from genjishimada_sdk.store import (...)` block (lines 15-37), and add:
   `async def get_all_quests(self, *, is_active: bool | None = None, difficulty: str | None = None, name_query: str | None = None) -> list[QuestPoolResponse]:` with a Google-style docstring.
   Body: `rows = await self._store_repo.get_all_quests(is_active=is_active, difficulty=difficulty, name_query=name_query)` then `return msgspec.convert(rows, list[QuestPoolResponse])`. Mirror `get_user_purchases` — no connection acquire.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --project apps/api pytest apps/api/tests/repository/store/test_store_repository_quests.py -k GetAllQuests -x 2>&1 | tail -20 && just lint-sdk 2>&1 | tail -5 && just lint-api 2>&1 | tail -5</automated>
  </verify>
  <done>All four Task-1 tests pass (GREEN). `just lint-sdk` and `just lint-api` clean (0 ruff + 0 basedpyright errors).</done>
</task>

<task type="auto">
  <name>Task 3: Add the GET /admin/quests route handler</name>
  <files>apps/api/routes/v3/store.py</files>
  <action>
In `apps/api/routes/v3/store.py`:
- Add `QuestPoolResponse` to the alphabetical `from genjishimada_sdk.store import (...)` block (lines 9-32).
- Add a new `@litestar.get` handler on `StoreController` (controller `path = "/store"`, so handler path `/admin/quests` resolves to `GET /api/v3/store/admin/quests`):
    decorator: `@litestar.get(path="/admin/quests", summary="List All Quests (Admin)", description="List all global quest-pool entries for the admin pool browser.", opt={"required_scopes": {"store:admin"}})`
    signature: `async def list_quests(self, store_service: StoreService, is_active: bool | None = None, difficulty: str | None = None, q: str | None = None) -> list[QuestPoolResponse]:`
    one-line Google-style docstring.
    body: `return await store_service.get_all_quests(is_active=is_active, difficulty=difficulty, name_query=q)`.
  Mirror the `get_quest_history` handler shape (~line 286). The public query param is `q` but maps to the service's `name_query` kwarg. Place the handler among the other `/admin/quests/*` handlers; the static `/admin/quests` path does not conflict with `/admin/quests/{quest_id:int}` or `/admin/quests/config`.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just lint-api 2>&1 | tail -5 && uv run --project apps/api python -c "from app import app; paths=[r.path for r in app.routes]; assert '/api/v3/store/admin/quests' in paths, [p for p in paths if 'admin/quests' in p]; print('route registered')"</automated>
  </verify>
  <done>`just lint-api` clean; route introspection confirms `GET /api/v3/store/admin/quests` is registered.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client -> API (query params) | `is_active`, `difficulty`, `q` cross from untrusted client into the SQL builder. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-caz-01 | Injection (Tampering) | `get_all_quests` dynamic WHERE | mitigate | All filter values are passed as positional `$N` bind params (incl. `name ILIKE $N` with `f"%{name_query}%"` as a bound value, never string-interpolated into SQL). `quest_type = 'global'` is a fixed literal. |
| T-caz-02 | Elevation of Privilege | `/admin/quests` route | mitigate | Gated by `opt={"required_scopes": {"store:admin"}}` via the global scope_guard; superuser bypass is the existing intended behavior. |
| T-caz-03 | Information Disclosure | global pool listing | accept | Returns only global quest definitions (non-sensitive content config); no PII, scope-gated to admins. |
</threat_model>

<verification>
- `uv run --project apps/api pytest apps/api/tests/repository/store/test_store_repository_quests.py -k GetAllQuests` — 4 passed.
- `just lint-sdk` clean; `just lint-api` clean.
- Route registered at `/api/v3/store/admin/quests` (introspection assert in Task 3).
- Optionally run the broader store suite: `uv run --project apps/api pytest apps/api/tests -m domain_store` — no regressions.
</verification>

<success_criteria>
- `GET /api/v3/store/admin/quests` returns a bare JSON array of all global quest-pool entries (>= 19), scope `store:admin`.
- `quest_type='global'` is always enforced (no bounty rows).
- `is_active`, `difficulty`, and `q` filters narrow results correctly; `q` is case-insensitive partial match via `ILIKE`.
- No pagination. `requirements` serialized as a JSON object.
- All lints clean; new tests pass; no store-domain regressions.
</success_criteria>

<output>
Create `.planning/quick/260629-caz-add-get-store-admin-quests-list-all-endp/260629-caz-SUMMARY.md` when done.
</output>
