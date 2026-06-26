---
phase: 15
slug: dynamic-overwatch-map-management
status: ready
nyquist_compliant: true
wave_0_complete: true
created: 2026-06-25
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `15-RESEARCH.md` → Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest >=8.3.5 + pytest-asyncio (auto) + pytest-databases[postgres] + pytest-xdist (8 workers) |
| **Config file** | `apps/api/pyproject.toml` (pytest config) |
| **Quick run command** | `uv run pytest apps/api/tests/integration/test_<touched>.py -x` |
| **Full suite command** | `just test-api` |
| **Estimated runtime** | ~30s per touched file; full API suite parallel (8 workers) |

**Test client:** `AsyncTestClient(app)` with headers `x-pytest-enabled: 1`, `X-API-KEY: testing` (superuser, bypasses scope) — `conftest.py:114-127`.

**Bot tests (REQ-09, REQ-10):** the bot has NO test harness — no `apps/bot/tests/` dir, no bot conftest, no pytest config in `apps/bot/pyproject.toml`, and `just test-all` runs only `just test-api`. The two bot unit tests (`test_api_service.py`, `test_map_name_select.py`) are created inline by plan 15-05 and are SELF-CONTAINED (mocks only, pytest-mock from root dev deps). They are run with an explicit `uv run pytest apps/bot/tests/<file>.py` command, NOT via `just test-api`.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest apps/api/tests/integration/test_<touched>.py -x` (< 30s)
- **After every plan wave:** Run `just test-api` (full API suite, parallel)
- **Before `/gsd:verify-work`:** `just ci` (lint + test-all) must be green; for the bot waves also run the explicit bot-test commands above
- **Max feedback latency:** ~30 seconds (per-task quick run)

---

## Per-Task Verification Map

> Every REQ below is bound to a concrete automated proof AND the plan/task that creates that test INLINE (within the executor task, not a separate Wave 0 plan).

| Req | Behavior | Created by (plan/task, inline) | Test Type | Automated Command | Status |
|-----|----------|--------------------------------|-----------|-------------------|--------|
| REQ-01 | submission accepts a name absent from the old Literal | 15-04 Task 3 (`test_map_content_integration.py`) + 15-01 flip | integration | `pytest apps/api/tests/integration/test_map_content_integration.py -k "create_map or appears_everywhere" -x` | ⬜ pending |
| REQ-02 | Unknown map name → 422 with "did you mean" suggestion | 15-03 Task 3 (`test_map_content_service.py`) | unit | `pytest apps/api/tests/services/test_map_content_service.py -k validate_map_name -x` | ⬜ pending |
| REQ-03 | `POST /content/maps` mixed multipart decodes name+banner → 201 | 15-04 Task 3 (`test_map_content_integration.py`) | integration | `pytest -k create_map -x` | ⬜ pending |
| REQ-04 | Re-upload banner for existing map overwrites same key | 15-04 Task 3 (`test_map_content_integration.py`) | integration | `pytest -k replace_banner -x` | ⬜ pending |
| REQ-05 | Empty/blank name → 422 | 15-03 Task 3 (`test_map_content_service.py`) | unit | `pytest -k empty_name -x` | ⬜ pending |
| REQ-06 | Stripped-key collision (King's Row / Kings Row) → 422 | 15-03 Task 3 (`test_map_content_service.py`) | unit | `pytest -k collision -x` | ⬜ pending |
| REQ-07 | `upload_map_banner` writes `assets/map_banners/{stripped}.png` | 15-03 Task 1 (`test_upload_map_banner.py`) | unit | `pytest -k upload_map_banner -x` | ⬜ pending |
| REQ-08 | `GET /utilities/map-names` returns all rows sorted, no search | 15-04 Task 3 (`test_autocomplete_integration.py` extend) | integration | `pytest apps/api/tests/integration/test_autocomplete_integration.py -k map_names -x` | ⬜ pending |
| REQ-09 | `api_service.get_all_map_names()` calls `GET /utilities/map-names` with `response_model=list[str]` | 15-05 Task 1 (`apps/bot/tests/test_api_service.py`) | unit (mocked `_request`) | `cd apps/bot && uv run pytest tests/test_api_service.py -k get_all_map_names -x` | ⬜ pending |
| REQ-10 | `MapNameSelect` pagination math with DB-fed list | 15-05 Task 3 (`apps/bot/tests/test_map_name_select.py`) | unit | `cd apps/bot && uv run pytest tests/test_map_name_select.py -k map_name_select -x` | ⬜ pending |
| REQ-11 | FK orphan pre-flight raises on orphan; FK added clean otherwise | 15-02 Task 3 (`test_map_management_schema.py`) | integration (schema) | `pytest -k map_name_fk -x` | ⬜ pending |
| REQ-12 | Seed replays idempotently (no duplicate-PK error) | 15-02 Task 3 (`test_map_management_schema.py`) | integration (schema) | `pytest -k seed_idempotent -x` | ⬜ pending |
| REQ-13 | All 70 reconciled maps present in `maps.names` after migration | 15-02 Task 3 (`test_map_management_schema.py`) | integration | `pytest -k phantom_maps -x` | ⬜ pending |
| REQ-15 | Added map appears: full-list endpoint + read surface, no redeploy | 15-04 Task 3 (`test_map_content_integration.py`) | integration | `pytest -k appears_everywhere -x` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> REQ-14 (standalone on-demand seed export script, D-10) is a manual, never-request-path utility — no behavioral test sampled here (covered by 15-02's script existence/usage check).

---

## Wave 0 Requirements (created INLINE — no separate Wave 0 plan)

This phase has NO standalone Wave 0 plan. Every test asset the Nyquist rule requires is created INLINE within the executor task that produces the corresponding production code, in the same plan/wave. The bindings:

- [x] **The 9 `get_args(OverwatchMap)` test-fixture sites** (8 files + `conftest.py`) are rewritten to `_SEED_MAP_NAMES` INLINE in **15-01 Task 2**, in the SAME wave as the SDK flip (15-01 Task 1) — `get_args(str)` returns `()` after the flip and would break `fake.random_element`, so the two are co-wave by construction. (RESEARCH §F said "14"; a live grep of the working tree returns exactly 8 files + conftest = 9 — the "14" was an overcount; 15-01 carries a zero-assertion grep + full-suite backstop.)
- [x] Map-create / replace-banner / appears-everywhere integration tests in `test_map_content_integration.py` — created INLINE in **15-04 Task 3** (REQ-01/03/04/15).
- [x] `validate_map_name` + empty-name + stripped-key collision unit tests in `test_map_content_service.py` — created INLINE in **15-03 Task 3** (REQ-02/05/06).
- [x] `upload_map_banner` unit test with mocked S3 client (`test_upload_map_banner.py`) — created INLINE in **15-03 Task 1** (REQ-07).
- [x] `GET /utilities/map-names` test in `test_autocomplete_integration.py` (extend) — created INLINE in **15-04 Task 3** (REQ-08).
- [x] Migration/schema tests (FK orphan guard, seed idempotency, phantom reconciliation) in `test_map_management_schema.py`, mirroring `test_tournaments_schema.py` — created INLINE in **15-02 Task 3** (REQ-11/12/13).
- [x] Bot unit test for `api_service.get_all_map_names()` route + response_model (`apps/bot/tests/test_api_service.py`, self-contained mocks) — created INLINE in **15-05 Task 1** (REQ-09).
- [x] Bot unit test for `MapNameSelect` pagination with a DB-fed list (`apps/bot/tests/test_map_name_select.py`, self-contained) — created INLINE in **15-05 Task 3** (REQ-10).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| discord.py `MapNameSelect` dropdown renders the DB-fed list in the moderator wizard | REQ-10 | No bot test harness for a live discord.py gateway UI; the pagination math is unit-tested (15-05 Task 3) but the live render is not | Run bot, open the map-edit wizard in the moderator cog, confirm the map-name dropdown shows DB rows (including a newly-added map) and paginates (15-05 Task 4 checkpoint) |
| Newly-added map banner resolves on the website surface | REQ-15 | Read path derives the URL via `get_map_banner()`; CDN/R2 round-trip | After `POST /content/maps`, fetch the map and confirm `assets/map_banners/{stripped}.png` resolves to the uploaded image |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or their test is created inline in the same plan/wave (no MISSING references)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covered inline: the 9 `get_args(OverwatchMap)` updates land in 15-01 Task 2, co-wave with the flip; all other test assets are created inline by the listed plan/task
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter
- [x] `wave_0_complete: true` set in frontmatter (Wave 0 work is folded into the execute tasks; no separate Wave 0 plan is outstanding)
- [x] REQ-09 bound to a concrete `pytest -k get_all_map_names` command (15-05 Task 1)

**Approval:** ready
