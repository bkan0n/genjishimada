---
phase: quick-260629-caz
plan: 01
subsystem: store
tags: [store, quests, admin, api, tdd]
requires: []
provides:
  - "SDK QuestPoolResponse struct (admin quest-pool entry)"
  - "StoreRepository.get_all_quests dynamic-WHERE global-only query"
  - "StoreService.get_all_quests -> list[QuestPoolResponse]"
  - "GET /api/v3/store/admin/quests (scope store:admin)"
affects:
  - libs/sdk/src/genjishimada_sdk/store.py
  - apps/api/repository/store_repository.py
  - apps/api/services/store_service.py
  - apps/api/routes/v3/store.py
tech-stack:
  added: []
  patterns:
    - "Dynamic WHERE builder over positional $N bind params (mirrors update_quest)"
    - "Repo dict rows -> msgspec.convert(list[Struct]) in service (mirrors get_user_purchases)"
key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/store.py
    - apps/api/repository/store_repository.py
    - apps/api/services/store_service.py
    - apps/api/routes/v3/store.py
    - apps/api/tests/repository/store/test_store_repository_quests.py
decisions:
  - "Public query param `q` maps to service kwarg `name_query` (ILIKE %q%)."
  - "quest_type = 'global' is a fixed SQL literal, never a bind param (endpoint is global-only)."
metrics:
  duration: ~12m
  completed: 2026-06-29
---

# Quick Task 260629-caz: Add GET /api/v3/store/admin/quests (List All Quests) Summary

Added a `GET /api/v3/store/admin/quests` endpoint (scope `store:admin`) returning a bare JSON array of all global quest-pool entries (>= 19 rows, no pagination) for the admin pool browser, with optional `is_active`, `difficulty`, and `q` (case-insensitive partial name) filters; bounty quests never appear because the query is locked to `quest_type = 'global'`.

## What Was Built

Built TDD (RED -> GREEN), four layers:

1. **SDK** (`libs/sdk/src/genjishimada_sdk/store.py`): new `QuestPoolResponse(Struct)` immediately after `QuestResponse` — fields `id, name, description, quest_type, difficulty, coin_reward, xp_reward, requirements: dict, is_active, created_at: dt.datetime`. Reused the existing `import datetime as dt`; no `__init__.py` edit (the `store` module is re-exported wholesale, and the consumers import structs directly from `genjishimada_sdk.store`).
2. **Repository** (`apps/api/repository/store_repository.py`): `get_all_quests(*, is_active=None, difficulty=None, name_query=None, conn=None) -> list[dict]` added above `provide_store_repository`. Dynamic WHERE starting from the literal `quest_type = 'global'`, appending `is_active = $N` / `difficulty = $N` / `name ILIKE $N` (bound `f"%{name_query}%"`) over a positional counter — mirroring `update_quest`'s `idx`/`values` accumulation. Selects the 10 specified columns, `ORDER BY id`, returns `[dict(row) for row in rows]`.
3. **Service** (`apps/api/services/store_service.py`): `QuestPoolResponse` added to the alphabetical SDK import block; `get_all_quests(*, ...) -> list[QuestPoolResponse]` calls the repo then `msgspec.convert(rows, list[QuestPoolResponse])` (mirrors `get_user_purchases`, no connection acquire).
4. **Route** (`apps/api/routes/v3/store.py`): `QuestPoolResponse` imported; `list_quests` handler `@litestar.get(path="/admin/quests", ..., opt={"required_scopes": {"store:admin"}})` placed among the `/admin/quests/*` handlers. Public params `is_active, difficulty, q`; `q` maps to the service's `name_query`. The static `/admin/quests` path does not conflict with `/admin/quests/config` or `/admin/quests/{quest_id:int}`.

## Commits

| Task | Commit | Description |
| ---- | ------ | ----------- |
| 1 (RED) | `a13035d` | `test(260629-caz)`: failing `TestGetAllQuests` repository tests |
| 2 (GREEN) | `0293341` | `feat(260629-caz)`: `QuestPoolResponse` struct + repo + service |
| 3 | `b0054b3` | `feat(260629-caz)`: `GET /admin/quests` `list_quests` route handler |

## Verification Gate Output

- **RED (Task 1):** `pytest -k GetAllQuests` -> `1 failed` (`AttributeError: 'StoreRepository' object has no attribute 'get_all_quests'. Did you mean: 'get_global_quests'?`) — confirmed RED before any implementation.
- **GREEN (Task 2):** `pytest -k GetAllQuests` -> `4 passed, 11 deselected in 1.25s`.
- **`just lint-sdk`:** `ruff format` 20 files unchanged; `ruff check` All checks passed!; `basedpyright` `0 errors, 0 warnings, 0 notes`.
- **`just lint-api`:** `ruff format` 98 files unchanged; `ruff check` All checks passed!; `basedpyright` `0 errors, 0 warnings, 0 notes`.
- **Route registration (Task 3):** `from app import app` introspection (run from `apps/api`) printed `route registered` — `/api/v3/store/admin/quests` is present.
- **No regressions:** `pytest apps/api/tests -m domain_store --no-testmon` -> `81 passed, 1878 deselected in 15.62s` (includes the 4 new + 11 prior store-quest repository tests).

## Deviations from Plan

None of Rules 1-4 triggered for the implementation itself. One minor lint adjustment:

**[Rule 3 - Blocking] Removed an unused `# noqa: S608` directive**
- **Found during:** Task 2 lint gate.
- **Issue:** I added `# noqa: S608` to the f-string SQL in `get_all_quests`, but `S608` is not in the project's enabled Ruff rule set, so Ruff reported `Remove unused noqa directive` (1 error, blocking the lint gate).
- **Fix:** Removed the directive. The query remains injection-safe by construction — all WHERE clauses are fixed literals except the bound `$N` positional params (T-caz-01 mitigation intact).
- **Files modified:** `apps/api/repository/store_repository.py`
- **Commit:** folded into `0293341` (Task 2; caught before the commit).

## Threat Model Compliance

- **T-caz-01 (Injection):** all filter values are positional `$N` bind params (incl. `name ILIKE $N` with `f"%{name_query}%"` as a bound value); `quest_type = 'global'` is a fixed literal. Mitigated.
- **T-caz-02 (Elevation of Privilege):** route gated by `opt={"required_scopes": {"store:admin"}}`. Mitigated.
- **T-caz-03 (Information Disclosure):** global quest definitions only; scope-gated. Accepted as designed.

## Known Stubs

None.

## Self-Check: PASSED

- `libs/sdk/src/genjishimada_sdk/store.py` — FOUND (contains `class QuestPoolResponse`)
- `apps/api/repository/store_repository.py` — FOUND (contains `async def get_all_quests`)
- `apps/api/services/store_service.py` — FOUND (contains `async def get_all_quests`)
- `apps/api/routes/v3/store.py` — FOUND (contains `/admin/quests` + `list_quests`)
- `apps/api/tests/repository/store/test_store_repository_quests.py` — FOUND (contains `TestGetAllQuests`)
- Commits `a13035d`, `0293341`, `b0054b3` — all FOUND in `git log`.
