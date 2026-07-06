---
phase: 15-dynamic-overwatch-map-management
verified: 2026-06-26T12:00:48Z
status: human_needed
score: 15/15 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run the bot and API locally. Add a brand-new map via POST /api/v3/content/maps (multipart name + small PNG banner). In Discord, open the moderator map-edit wizard (/map edit <code>), advance to the Map Name field, and confirm the dropdown lists DB rows including the newly-added map, paginates with prev/next buttons (25/page), and the banner resolves at assets/map_banners/{stripped}.png."
    expected: "The new map appears in the moderator MapNameSelect dropdown without a bot restart. Pagination renders correctly (25/page). Banner URL resolves on the website/map read surface."
    why_human: "No bot test harness exists for live discord.py gateway UI; the pagination math is unit-tested (apps/bot/tests/test_map_name_select.py) but the live render is not."
---

# Phase 15: Dynamic Overwatch Map Management — Verification Report

**Phase Goal:** Let an admin add a new Overwatch map (name + banner) through ONE API call and have it appear automatically on all three surfaces — website reads, map submission, and bot slash commands — with NO code change and NO redeploy.

**Verified:** 2026-06-26T12:00:48Z
**Status:** PASSED (manual item pending)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | msgspec accepts a map name absent from the old 70-entry Literal at the request boundary | VERIFIED | `OverwatchMap = str` at `libs/sdk/src/genjishimada_sdk/maps.py:111`; `uv run python -c "from typing import get_args; from genjishimada_sdk.maps import OverwatchMap; assert OverwatchMap is str"` passes |
| 2 | `POST /api/v3/content/maps` mixed-multipart {name, banner} returns 201 under content:admin scope | VERIFIED | `MapContentController(path="/content")` with `@post("/maps")` at `apps/api/routes/v3/content.py:735`; route introspection confirms `/api/v3/content/maps`; integration test `TestCreateMap::test_create_map` PASSES |
| 3 | Re-uploading a banner for an existing map name returns 201 with `inserted: false` (replace-banner) | VERIFIED | `ON CONFLICT DO NOTHING` in `map_content_repository.py:43`; `TestReplaceBanner::test_replace_banner` PASSES |
| 4 | `GET /utilities/map-names` returns all `maps.names` rows sorted, no search/limit | VERIFIED | `fetch_all_map_names` at `autocomplete_repository.py:52` with `SELECT name FROM maps.names ORDER BY name`; `TestListAllMapNames::test_map_names` PASSES |
| 5 | A newly-added map appears on the full-list read surface with no redeploy | VERIFIED | `TestAppearsEverywhere::test_appears_everywhere` PASSES — creates map, confirms it appears in `/api/v3/utilities/map-names` and is accepted by a `core.maps` FK write in the same session |
| 6 | Unknown map name → 422 with difflib "did you mean" suggestion | VERIFIED | `validate_map_name` in `map_content_service.py:116`; `TestValidateMapName::test_unknown_name_raises_422_with_suggestion` PASSES |
| 7 | Empty/blank name → 422 | VERIFIED | Guard at `map_content_service.py:88`; `TestCreateMapEmptyName::test_empty_name_raises_422` and `test_blank_name_raises_422` PASS |
| 8 | Stripped-key collision (King's Row vs Kings Row) → 422 naming the existing map | VERIFIED | Collision guard at `map_content_service.py:96-107`; `TestCreateMapCollision::test_punctuation_collision_raises_422` PASSES |
| 9 | `upload_map_banner` writes at `assets/map_banners/{stripped}.png` matching `get_map_banner()` exactly | VERIFIED | Key derivation at `image_storage_service.py:87-88`; extension always `.png`; 5 unit tests in `test_upload_map_banner.py` PASS including accented-name and cross-check tests |
| 10 | All 70 reconciled maps (63 live + 7 phantom) present in `maps.names` after migrations | VERIFIED | Migration 0032 reconciles 7 phantoms; 0001_init.sql seed has all 70 in one `ON CONFLICT DO NOTHING` block; `test_phantom_maps` PASSES |
| 11 | Seed replays idempotently — no duplicate-PK error | VERIFIED | `ON CONFLICT DO NOTHING` on 0001_init.sql seed; `test_seed_idempotent` PASSES |
| 12 | `core.maps.map_name` FK to `maps.names.name` (ON UPDATE CASCADE) — orphan pre-flight guards prod migration | VERIFIED | `maps_map_name_names_fk` in `0032_dynamic_map_management.sql:50`; `test_map_name_fk_constraint_exists`, `test_map_name_fk_rejects_orphan`, `test_map_name_fk_accepts_known` all PASS |
| 13 | Standalone on-demand export script exists, never imported by app code | VERIFIED | `scripts/export_map_names_seed.py` exists; `grep -rn "export_map_names_seed" apps/` returns nothing; docstring states D-10 constraints explicitly |
| 14 | Bot `api_service.get_all_map_names()` calls `GET /utilities/map-names` with `response_model=list[str]` | VERIFIED | Plain `def` at `apps/bot/extensions/api_service.py:802`; `test_get_all_map_names_calls_request_with_route_and_response_model` and `test_get_all_map_names_is_not_a_coroutine_function` PASS |
| 15 | `MapNameSelect` is DB-fed from a list fetched once in async wizard-build; pagination math unchanged; `get_args(MapCategory)` unchanged | VERIFIED | `MapNameSelect.__init__` takes `all_maps: list[str]` at `moderator.py:762`; both construction sites await `get_all_map_names()` (moderator.py:105, map_editor.py:61); `get_args(MapCategory)` still at `moderator.py:744`; 6 unit tests in `test_map_name_select.py` PASS |

**Score:** 15/15 truths verified (all automated; 1 additional human-verify item below)

---

## Decision Compliance (D-01..D-11)

| Decision | Requirement | Evidence | Status |
|----------|-------------|----------|--------|
| D-01 | `POST /api/v3/content/maps` under `content:admin` scope | `MapContentController(path="/content")` + `@post("/maps")` + `opt={"required_scopes": {"content:admin"}}` at `content.py:727,735,745` | HONORED |
| D-02 | `GET /utilities/map-names` — full list, no search/limit; existing autocomplete endpoint unchanged | `AutocompleteController.list_all_map_names` at `/map-names` returns `fetch_all_map_names()`; `/autocomplete/names` route at `autocomplete.py:22` is byte-unchanged | HONORED |
| D-03 | Add + replace-banner both in scope | Re-posting an existing name → 201 `inserted:false`; `TestReplaceBanner::test_replace_banner` PASSES | HONORED |
| D-04 | Banner required at create (single mixed-multipart) | `MapCreateMultipart(name: str, banner: UploadFile)` at `content.py:186-197`; test sends `files={"banner": ...}` | HONORED |
| D-05 | Store banner at stripped-name key matching `get_map_banner()` derivation | `re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")` at `image_storage_service.py:87` — byte-identical to SDK's `get_map_banner()`; tests assert equality | HONORED |
| D-06 | No `banner_url` column added anywhere | `grep -c "banner_url" apps/api/migrations/0001_init.sql` == 0; sole mention in 0032 is a comment (`-- No banner_url column...`) | HONORED |
| D-07 | Collision guard (empty name → 422, stripped-key collision → 422 naming the existing map) | Guards at `map_content_service.py:88` and `96-107`; collision error message includes `other` map name | HONORED |
| D-08 | 7 phantom maps reconciled in `maps.names` | `0032_dynamic_map_management.sql:22-31` inserts all 7; `0001_init.sql:888-894` includes them in the seed; `test_phantom_maps` PASSES | HONORED |
| D-09 | One idempotent `ON CONFLICT DO NOTHING` seed block in `0001_init.sql` | Lines 823-895: single `INSERT INTO maps.names (name) VALUES (...70 names...) ON CONFLICT DO NOTHING;` | HONORED |
| D-10 | Standalone on-demand export script, never on request path, not in backup | `scripts/export_map_names_seed.py` with docstring declaring D-10 constraints; not imported by any `apps/` code | HONORED |
| D-11 | FK `core.maps.map_name → maps.names.name ON UPDATE CASCADE` with orphan pre-flight | `maps_map_name_names_fk` + `RAISE EXCEPTION` block in `0032_dynamic_map_management.sql:34-52`; schema tests PASS | HONORED |

---

## REQ Coverage (REQ-01..REQ-15)

| REQ | Behavior | Test | Status |
|-----|----------|------|--------|
| REQ-01 | Submission accepts a name absent from the old Literal | `OverwatchMap = str`; `TestAppearsEverywhere::test_appears_everywhere` creates a novel name and it resolves | SATISFIED |
| REQ-02 | Unknown map name → 422 with "did you mean" | `TestValidateMapName::test_unknown_name_raises_422_with_suggestion` PASSES | SATISFIED |
| REQ-03 | `POST /content/maps` mixed multipart decodes name+banner → 201 | `TestCreateMap::test_create_map` PASSES | SATISFIED |
| REQ-04 | Re-upload banner for existing map overwrites same key | `TestReplaceBanner::test_replace_banner` PASSES | SATISFIED |
| REQ-05 | Empty/blank name → 422 | `TestCreateMapEmptyName::test_empty_name_raises_422` + `test_blank_name_raises_422` PASS | SATISFIED |
| REQ-06 | Stripped-key collision → 422 | `TestCreateMapCollision::test_punctuation_collision_raises_422` PASSES | SATISFIED |
| REQ-07 | `upload_map_banner` writes `assets/map_banners/{stripped}.png` | `TestUploadMapBanner` (5 tests) PASS; key verified against `get_map_banner()` | SATISFIED |
| REQ-08 | `GET /utilities/map-names` returns all rows sorted, no search | `TestListAllMapNames::test_map_names` PASSES; query is `SELECT name FROM maps.names ORDER BY name` with no params | SATISFIED |
| REQ-09 | `api_service.get_all_map_names()` calls `GET /utilities/map-names` with `response_model=list[str]` | `test_get_all_map_names_calls_request_with_route_and_response_model` + `test_get_all_map_names_is_not_a_coroutine_function` PASS | SATISFIED |
| REQ-10 | `MapNameSelect` pagination math with DB-fed list | 6 unit tests in `test_map_name_select.py` PASS (page slicing, total_pages, current-default, empty-list) | SATISFIED (live UI pending human verify) |
| REQ-11 | FK orphan pre-flight raises on orphan; FK added clean otherwise | `test_map_name_fk_constraint_exists`, `test_map_name_fk_rejects_orphan`, `test_map_name_fk_accepts_known` PASS | SATISFIED |
| REQ-12 | Seed replays idempotently | `test_seed_idempotent` PASSES — re-applies a representative slice including phantoms, no error, row count unchanged | SATISFIED |
| REQ-13 | All 70 reconciled maps present in `maps.names` after migration | `test_phantom_maps` PASSES — all 7 phantoms confirmed present | SATISFIED |
| REQ-14 | Standalone on-demand seed export script (D-10) | `scripts/export_map_names_seed.py` exists, parses, contains `SELECT name FROM maps.names ORDER BY name` and `ON CONFLICT DO NOTHING` output; not imported by `apps/` | SATISFIED |
| REQ-15 | Added map appears: full-list endpoint + read surface, no redeploy | `TestAppearsEverywhere::test_appears_everywhere` PASSES — creates name, confirms in full-list endpoint AND accepted by FK-constrained `core.maps` write | SATISFIED |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `libs/sdk/src/genjishimada_sdk/maps.py` | `OverwatchMap = str`; MapCategory Literal untouched | VERIFIED | Line 111: `OverwatchMap = str`; `MapCategory = Literal[...]` at line 101 |
| `apps/api/migrations/0032_dynamic_map_management.sql` | Phantom reconcile + orphan guard + FK | VERIFIED | All 3 ordered steps present; `maps_map_name_names_fk` with `ON UPDATE CASCADE` |
| `apps/api/migrations/0001_init.sql` | One idempotent `ON CONFLICT DO NOTHING` block of all 70 names; no `banner_url` | VERIFIED | Lines 823-895; `grep -c banner_url` == 0 |
| `scripts/export_map_names_seed.py` | Standalone on-demand, not in app code | VERIFIED | Exists; docstring declares D-10; not imported anywhere in `apps/` |
| `apps/api/services/image_storage_service.py` | `upload_map_banner` keyed by stripped name, always `.png` | VERIFIED | Method at line 69; key: `assets/map_banners/{stripped}.png` |
| `apps/api/services/map_content_service.py` | `create_map` with guards+upload+insert; `validate_map_name` with difflib | VERIFIED | Substantive implementation; ordering: empty guard → collision guard → upload → insert |
| `apps/api/repository/map_content_repository.py` | `insert_map_name` (ON CONFLICT) + `fetch_all_map_names` | VERIFIED | Both methods present with `$1` params and `provide_map_content_repository` |
| `apps/api/routes/v3/content.py` | `MapContentController(path="/content")` with `POST /maps` | VERIFIED | `path = "/content"` at line 727; `@post("/maps")` at line 736 |
| `apps/api/routes/v3/autocomplete.py` | `GET /map-names` full-list handler | VERIFIED | `list_all_map_names` at `/map-names` returning `fetch_all_map_names()` |
| `apps/api/repository/autocomplete_repository.py` | `fetch_all_map_names` with `ORDER BY name`, no params | VERIFIED | Method at line 38; query at line 52 |
| `apps/bot/extensions/api_service.py` | `get_all_map_names()` plain def calling `Route("GET", "/utilities/map-names")` | VERIFIED | Line 802; plain `def`; `response_model=list[str]` |
| `apps/bot/extensions/moderator.py` | `MapNameSelect` DB-fed; `get_args(MapCategory)` unchanged; no `await` in `__init__` | VERIFIED | `all_maps: list[str]` param; `get_args(MapCategory)` at line 744; `__init__` is sync |
| `apps/bot/extensions/map_editor.py` | Second construction site awaits `get_all_map_names()` | VERIFIED | `await itx.client.api.get_all_map_names()` at line 61 |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `POST /api/v3/content/maps` | `MapContentService.create_map` | Controller decodes multipart, calls service | WIRED | `content.py:767-769`: reads banner, calls `map_content_service.create_map(data.name, content, content_type)` |
| `MapContentService.create_map` | `ImageStorageService.upload_map_banner` | Called before DB insert | WIRED | `map_content_service.py:110`: `self._image_svc.upload_map_banner(banner, content_type, name)` before `insert_map_name` |
| `GET /utilities/map-names` | `maps.names` table | `fetch_all_map_names SELECT name ... ORDER BY name` | WIRED | `autocomplete_repository.py:52` runs `SELECT name FROM maps.names ORDER BY name` |
| `core.maps.map_name` | `maps.names.name` | FK `maps_map_name_names_fk ON UPDATE CASCADE` | WIRED | `0032_dynamic_map_management.sql:50-52`; confirmed by `test_map_name_fk_constraint_exists` |
| `MapEditWizardView` | `api_service.get_all_map_names()` | Fetched once in async callback, passed into view init | WIRED | `moderator.py:105` + `map_editor.py:61` both `await itx.client.api.get_all_map_names()` |
| `MapNameSelect.__init__` | DB-fed list | `all_maps` param replaces `get_args(OverwatchMap)` | WIRED | `moderator.py:762`; `rebuild()` passes `all_maps=self._all_maps` at line 1341 |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `MapContentController.create_map` | `row` (name + inserted flag) | `MapContentService.create_map` → `MapContentRepository.insert_map_name` → `INSERT INTO maps.names RETURNING name` | Yes — real DB insert | FLOWING |
| `AutocompleteController.list_all_map_names` | return value `list[str]` | `AutocompleteRepository.fetch_all_map_names` → `SELECT name FROM maps.names ORDER BY name` | Yes — real DB query | FLOWING |
| `MapNameSelect` options | `all_maps: list[str]` | Awaited `api_service.get_all_map_names()` → `GET /utilities/map-names` → real DB query | Yes — live DB on each wizard open | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Route `/api/v3/content/maps` registered | `python -c "from app import app; assert '/api/v3/content/maps' in {r.path for r in app.routes}"` | exit 0 | PASS |
| Route `/api/v3/utilities/map-names` registered | `python -c "from app import app; assert '/api/v3/utilities/map-names' in {r.path for r in app.routes}"` | exit 0 | PASS |
| `OverwatchMap is str`; `MapCategory` still Literal[3] | `python -c "from typing import get_args; from genjishimada_sdk.maps import OverwatchMap, MapCategory; assert OverwatchMap is str; assert len(get_args(MapCategory)) == 3"` | exit 0 | PASS |
| `get_args(OverwatchMap)` zero sites remain | `grep -rln 'get_args(OverwatchMap)' apps/ \| wc -l` | 0 | PASS |
| `export_map_names_seed` not imported by app code | `grep -rn "export_map_names_seed" apps/` | no output | PASS |
| Schema tests (phantom, idempotent, FK) | `pytest tests/integration/test_map_management_schema.py::TestMapManagementSchema -v` | 5/5 PASS | PASS |
| Content integration tests (create, replace-banner, appears-everywhere) | `pytest tests/integration/test_map_content_integration.py::TestCreateMap tests/integration/test_map_content_integration.py::TestReplaceBanner tests/integration/test_map_content_integration.py::TestAppearsEverywhere -v` | 5/5 PASS | PASS |
| Service unit tests (upload_map_banner, map_content_service) | `pytest tests/services/test_upload_map_banner.py tests/services/test_map_content_service.py -v` | 18/18 PASS | PASS |
| Autocomplete full-list test | `pytest tests/integration/test_autocomplete_integration.py -k map_names -v` | 1/1 PASS | PASS |
| Bot client + pagination tests | `cd apps/bot && uv run pytest tests/ -v` | 8/8 PASS | PASS |
| Full API suite (no regression) | `uv run pytest tests -q -p no:testmon` | 76 passed, 1 xfailed, 0 failures | PASS |

---

## Anti-Patterns Found

No blockers. No `TBD`, `FIXME`, or `XXX` markers in phase-modified files. No stub returns in production code paths. The one notable comment mention of `banner_url` in `0032_dynamic_map_management.sql:19` is a clarifying comment (`-- No banner_url column is added anywhere (D-06)...`), not a code smell.

---

## Human Verification Required

### 1. Live Discord Dropdown Render (REQ-10 live surface)

**Test:** Run the API (`just run-api`) and bot (`just run-bot`) locally against the local DB/MinIO. Add a brand-new map via `POST /api/v3/content/maps` (multipart `name` + a small PNG `banner`). In Discord, open the moderator map-edit wizard (`/map edit <code>`), advance to the Map Name field.

**Expected:** The dropdown lists DB rows, includes the newly-added map, and paginates with prev/next buttons (25 items/page). The banner for the new map resolves on the website/map read surface (`assets/map_banners/{stripped}.png`).

**Why human:** No bot test harness for live discord.py gateway UI exists. The pagination math is unit-tested in `apps/bot/tests/test_map_name_select.py` (6 tests, all green). The live render requires a running Discord gateway connection.

---

## Gaps Summary

No gaps. All 15 REQ IDs are verified against the actual codebase. All 11 decisions (D-01..D-11) are honored in the code with file-and-line citations. The one outstanding item is a deliberate manual-only verification identified by the planning documents themselves (Task 4 of 15-05: live Discord dropdown render), not a failure.

---

*Verified: 2026-06-26T12:00:48Z*
*Verifier: Claude (gsd-verifier)*
