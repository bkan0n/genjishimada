---
phase: 15-dynamic-overwatch-map-management
plan: 04
subsystem: api
tags: [litestar, multipart, asyncpg, msgspec, content-cms, overwatch-maps, file-upload]

# Dependency graph
requires:
  - phase: 15-03
    provides: "MapContentService.create_map (guards + upload + idempotent insert), MapContentRepository (insert_map_name, fetch_all_map_names), ImageStorageService.upload_map_banner, provide_map_content_service/repo"
  - phase: 15-02
    provides: "core.maps.map_name -> maps.names FK backstop (migration 0032); idempotent maps.names seed"
  - phase: 15-01
    provides: "OverwatchMap Literal -> str (relaxed request boundary)"
provides:
  - "POST /api/v3/content/maps — content:admin mixed-multipart {name, banner} create + replace-banner endpoint (201)"
  - "MapContentController(path=/content) sibling to MovementTechController with full DI wiring"
  - "GET /utilities/map-names — full-list read endpoint (sorted list[str], no search/limit)"
  - "AutocompleteRepository.fetch_all_map_names (full-list query)"
  - "Integration coverage: create, replace-banner, full-list, appears-everywhere (REQ-15)"
affects: [website-map-reads, admin-dashboard, bot-map-name-dropdown]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Mixed-multipart create (msgspec Struct{name: str, banner: UploadFile} via Body(MULTI_PART)) fusing upload_image + MovementTech create shape"
    - "Sibling Controller under a shared CMS namespace to control exact route resolution (path=/content -> /api/v3/content/maps)"
    - "Idempotent create == replace: ON CONFLICT DO NOTHING returns 201 + inserted flag (never 409)"

key-files:
  created:
    - "apps/api/tests/integration/test_map_content_integration.py"
  modified:
    - "apps/api/routes/v3/content.py"
    - "apps/api/routes/v3/autocomplete.py"
    - "apps/api/repository/autocomplete_repository.py"
    - "apps/api/services/map_content_service.py"
    - "apps/api/tests/integration/test_autocomplete_integration.py"

key-decisions:
  - "New sibling MapContentController(path=/content) — NOT an extension of MovementTechController (path=/content/movement-tech) — so the route resolves to EXACTLY /api/v3/content/maps (D-01)"
  - "Promoted ImageStorageService import out of TYPE_CHECKING in map_content_service.py so provide_map_content_service's signature resolves at Litestar registration (DI graph fix)"
  - "Banner upload stubbed in tests via monkeypatching ImageStorageService.__init__ + upload_map_banner so the suite needs no MinIO/S3"

patterns-established:
  - "Route-resolution control via sibling Controller path rather than nesting under an existing controller"
  - "create==replace idempotency surfaced to the client via an `inserted` boolean response field"

requirements-completed: [REQ-03, REQ-04, REQ-08, REQ-15, D-01, D-02, D-03]

# Metrics
duration: ~25min
completed: 2026-06-25
---

# Phase 15 Plan 04: Dynamic Map Management HTTP Surface Summary

**`POST /api/v3/content/maps` (content:admin mixed-multipart create + replace-banner, 201) and `GET /utilities/map-names` full-list read, wired on a sibling `MapContentController(path=/content)` so the create route resolves to exactly `/api/v3/content/maps`, with appears-everywhere proof.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-25T21:40:00Z (approx)
- **Completed:** 2026-06-25T22:05:00Z (approx)
- **Tasks:** 3
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- Wired the phase's primary write surface: `POST /api/v3/content/maps` decodes a mixed-multipart `{name, banner}` in one request, requires `content:admin`, caps the body at 25 MB, and returns 201 — doubling as replace-banner (re-post -> 201 `inserted: false`, banner overwritten at the same stripped key).
- Added the full-list read endpoint `GET /utilities/map-names` returning all `maps.names` rows sorted as `list[str]` with no search/limit; the existing search-required `/autocomplete/names` route is byte-unchanged.
- Proved REQ-15 end-to-end: a newly-created map immediately appears on the full-list endpoint AND is accepted by a `core.maps` write (the migration-0032 FK resolves only because the name now exists) — i.e. it appears on read surfaces with no redeploy.
- Confirmed the DI graph resolves via `from app import app` route introspection (`/api/v3/content/maps` registered) — the assertion intentionally deferred from 15-03 to this plan.

## Task Commits

Each task was committed atomically:

1. **Task 1: MapContentController (path=/content) — POST /api/v3/content/maps multipart create + DI wiring** — `2457922` (feat)
2. **Task 2: GET /utilities/map-names full-list endpoint + repo method** — `4a7f2a9` (feat)
3. **Task 3: Integration tests — create, replace-banner, full-list, appears-everywhere** — `22eebd4` (test)

**Plan metadata:** _(this commit)_ (docs: complete plan)

## Files Created/Modified

- `apps/api/routes/v3/content.py` — Added `MapContentController(path=/content)` with the `create_map` multipart handler (content:admin, 25 MB cap), `MapCreateMultipart{name, banner}` + `MapCreateResponse{name, inserted}` structs, multipart imports, and DI wiring for `provide_map_content_service`/`provide_map_content_repository`/`provide_image_storage_service`.
- `apps/api/routes/v3/autocomplete.py` — Added the `list_all_map_names` handler (`GET /map-names` -> `/api/v3/utilities/map-names`, `list[str]`); existing routes untouched.
- `apps/api/repository/autocomplete_repository.py` — Added `fetch_all_map_names` (`SELECT name FROM maps.names ORDER BY name`).
- `apps/api/services/map_content_service.py` — Promoted `from services.image_storage_service import ImageStorageService` out of the `TYPE_CHECKING` block so the provider signature resolves at registration.
- `apps/api/tests/integration/test_map_content_integration.py` (new) — `create_map`, `replace_banner`, `appears_everywhere`, empty-name 422, and auth-gate tests; stubs the image service via monkeypatch.
- `apps/api/tests/integration/test_autocomplete_integration.py` — Added `TestListAllMapNames` (`map_names` full-list, no-search-param contrast, auth gate).

## Decisions Made

- **Sibling controller for route control (D-01):** `MovementTechController.path` is `/content/movement-tech`; attaching `/maps` there would resolve to the wrong `/api/v3/content/movement-tech/maps`. A new `MapContentController(path=/content)` makes `@post("/maps")` resolve to exactly `/api/v3/content/maps`. It is auto-discovered by `routes/v3/__init__.py` (any `Controller` subclass defined in `content.py`), so no manual registration was needed.
- **create==replace idempotency:** the `ON CONFLICT DO NOTHING` insert from 15-03 returns `inserted: false` for an existing name (201, not 409), and the banner re-upload overwrites the same stripped key — so a single endpoint serves both create (D-03 add) and replace-banner (D-03 replace).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Promoted `ImageStorageService` import out of `TYPE_CHECKING` in `map_content_service.py`**
- **Found during:** Task 1 (DI graph verification)
- **Issue:** `from app import app` failed with `NameError: name 'ImageStorageService' is not defined`. The 15-03 provider `provide_map_content_service(state, map_content_repo, image_svc: ImageStorageService)` annotates `image_svc` with a type imported only under `TYPE_CHECKING`. Litestar evaluates provider signatures at route registration via `get_type_hints`, which needs the name resolvable at runtime — so the entire app failed to construct once the new controller wired the provider.
- **Fix:** Moved `from services.image_storage_service import ImageStorageService` out of the `if TYPE_CHECKING:` block to a top-level import (left `Pool` under `TYPE_CHECKING`). No circular-import issue (image_storage_service has no back-dependency on map_content_service).
- **Files modified:** `apps/api/services/map_content_service.py`
- **Verification:** `uv run python -c "from app import app; assert '/api/v3/content/maps' in {r.path for r in app.routes}"` exits 0; `just lint-api` clean (basedpyright 0 errors).
- **Committed in:** `2457922` (Task 1 commit)

**2. [Rule 3 - Blocking] Stubbed `ImageStorageService.__init__` in tests (not just `upload_map_banner`)**
- **Found during:** Task 3 (first test run)
- **Issue:** Monkeypatching only `upload_map_banner` was insufficient — `ImageStorageService.__init__` builds a boto3 S3 client at construction time, which raises `ValueError: Invalid endpoint: https://.r2.cloudflarestorage.com` in the test environment (no R2/S3 endpoint configured), so the DI provider blew up with a 500 before the upload method was ever reached.
- **Fix:** The `banner_spy` fixture also monkeypatches `__init__` to a no-op (`self.client = None`), so the service constructs cleanly and the stubbed `upload_map_banner` records calls. This is test-only scaffolding.
- **Files modified:** `apps/api/tests/integration/test_map_content_integration.py`
- **Verification:** Targeted `-k "create_map or replace_banner or map_names or appears_everywhere"` -> 5 passed; broader run 17 passed.
- **Committed in:** `22eebd4` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 blocking).
**Impact on plan:** Both fixes were required to make the planned work run (DI graph resolution and a MinIO-free test suite). No scope creep; deviation 1 was explicitly anticipated by the plan's prior-wave note ("15-04 must wire ... the DI-graph resolution is asserted there"). The fix was the minimal change to satisfy that assertion.

## Issues Encountered

- The plan suggested optionally flipping `list[OverwatchMap]` return hints to `list[str]` in `autocomplete.py` as cosmetic cleanup. Left as-is: `OverwatchMap` is already aliased to `str` (15-01), the existing route signatures are byte-unchanged per the D-02 constraint, and touching them risks the "byte-unchanged `/autocomplete/names`" acceptance criterion for no behavioral gain. The NEW handler uses `list[str]` directly.

## Threat Surface Notes

All threat-model mitigations (T-15-10..T-15-14) are present and asserted:
- T-15-10 (authz): `opt={"required_scopes": {"content:admin"}}` on `create_map`; auth-gate test asserts 401 unauthenticated.
- T-15-11 (oversized upload): `request_max_body_size=1024*1024*25`.
- T-15-12/13 (injection / runtime-validation bypass): handled by the 15-03 service guards + `$1` params + FK backstop (unchanged here); empty-name 422 asserted through the HTTP boundary.
- T-15-14 (info disclosure on `/map-names`): accept — public names only; auth-gate test confirms it inherits global auth (401 unauthenticated).

No new security surface beyond the planned threat model.

## User Setup Required

None - no external service configuration required. (The banner upload uses the existing `ImageStorageService` / R2/MinIO config already documented in CLAUDE.md.)

## Next Phase Readiness

- The full API write surface for dynamic map management is live and reachable: create, replace-banner, and the full-list read endpoint all resolve and are covered by integration tests.
- Remaining phase-15 work (per CONTEXT in-scope list) is the bot-side `MapNameSelect` DB-fed dropdown + `api_service.get_all_map_names()` client — the `GET /utilities/map-names` endpoint this plan added is the contract those consume.

## Self-Check: PASSED

All 7 created/modified files exist on disk; all 3 task commits (`2457922`, `4a7f2a9`, `22eebd4`) are present in git history.

---
*Phase: 15-dynamic-overwatch-map-management*
*Completed: 2026-06-25*
