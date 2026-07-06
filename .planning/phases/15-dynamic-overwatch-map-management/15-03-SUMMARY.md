---
phase: 15-dynamic-overwatch-map-management
plan: 03
subsystem: api
tags: [maps, validation, storage, di]
requires:
  - "15-01: OverwatchMap is str (removed Literal enum gate)"
  - "15-02: migration 0032 maps.names FK + idempotent seed"
provides:
  - "ImageStorageService.upload_map_banner(content, content_type, map_name) -> url (stripped-key .png)"
  - "MapContentRepository.insert_map_name (ON CONFLICT) + fetch_all_map_names"
  - "MapContentService.create_map (empty+collision guards, banner upload, idempotent insert)"
  - "MapContentService.validate_map_name (consumer-side difflib 'did you mean')"
  - "provide_map_content_repository + provide_map_content_service DI providers (declare image_svc dep)"
affects:
  - "15-04: MapContentController wires provide_image_storage_service + provide_map_content_repository into MapContentService"
tech-stack:
  added: []
  patterns:
    - "stripped-key banner upload byte-matching get_map_banner (re.sub [^a-zA-Z0-9] -> lower/strip/replace + .png)"
    - "fallible non-DB work (guards + upload) before a single-statement ON CONFLICT insert (no txn wrap) — RESEARCH Pitfall 1"
    - "difflib.get_close_matches(n=3, cutoff=0.6) for the consumer-side 'did you mean'"
key-files:
  created:
    - apps/api/services/map_content_service.py
    - apps/api/repository/map_content_repository.py
    - apps/api/tests/services/test_upload_map_banner.py
    - apps/api/tests/services/test_map_content_service.py
    - apps/api/tests/repository/maps/test_map_content_repository.py
  modified:
    - apps/api/services/image_storage_service.py
decisions:
  - "Banner CacheControl is 'public, max-age=3600, must-revalidate' (replaceable, not immutable like screenshots) — Open Q1"
  - "Idempotent re-insert returns {inserted: False} (201 + flag), NOT 409 — Open Q2"
  - "Accented vs ASCII names do NOT collide (get_map_banner removes accents, not folds) — corrects plan Test 3 premise"
metrics:
  duration: ~35m
  completed: 2026-06-25
  tasks: 3
  files: 6
---

# Phase 15 Plan 03: Map content service + storage layer Summary

Service-layer runtime gate replacing the removed `OverwatchMap` Literal: a stripped-key banner upload that byte-matches `get_map_banner()`, the new `MapContentRepository` (idempotent `insert_map_name` + `fetch_all_map_names`), and `MapContentService` with `create_map` (empty + stripped-key-collision guards, banner upload, idempotent insert) plus the consumer-side `validate_map_name` difflib "did you mean". All unit-tested with a mocked S3 client (services) and the real test DB (repository); no HTTP route (15-04 wires the controller).

## What was built

- **`ImageStorageService.upload_map_banner(content, content_type, map_name) -> str`** — keys the object at `assets/map_banners/{stripped}.png` where `stripped = re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")`, byte-identical to `get_map_banner()` (`libs/sdk/.../maps.py:946`). Extension is **always `.png`** regardless of source content-type (the read path hardcodes it); the real content-type is passed through as the S3 `ContentType` ExtraArg. Added `import re`.
- **`MapContentRepository`** (`apps/api/repository/map_content_repository.py`) — `insert_map_name` runs `INSERT INTO maps.names (name) VALUES ($1) ON CONFLICT DO NOTHING RETURNING name` and returns `{"name": name, "inserted": row is not None}`; `fetch_all_map_names` runs `SELECT name FROM maps.names ORDER BY name`. `$1` positional params + `_get_connection(conn)` throughout. `provide_map_content_repository` provider added.
- **`MapContentService`** (`apps/api/services/map_content_service.py`) — `create_map` runs, in order: (1) empty/blank guard → 422 (REQ-05); (2) stripped-key collision guard → 422 naming the colliding existing map (REQ-06/D-07); (3) `upload_map_banner` (REQ-07); (4) single-statement idempotent insert. All fallible non-DB work precedes the insert; no `conn.transaction()` wrap (RESEARCH Pitfall 1). `validate_map_name` (REQ-02, consumer-side) returns a known name or raises 422 with a `difflib.get_close_matches` suggestion. Module-level `_strip_key` byte-matches `get_map_banner`. `provide_map_content_service` **declares** `image_svc: ImageStorageService` (wired by the controller in 15-04).

## Task commits

| Task | Name | Commits (test → impl) | Files |
| ---- | ---- | --------------------- | ----- |
| 1 | upload_map_banner stripped-key | `b397311` → `63b7da3` | image_storage_service.py, test_upload_map_banner.py |
| 2 | MapContentRepository | `5b1c13b` → `6856b7a` | map_content_repository.py, test_map_content_repository.py |
| 3 | MapContentService | `0e7eb57` → `90d94e3` | map_content_service.py, test_map_content_service.py |

## Verification

- `pytest -k "validate_map_name or empty_name or collision or upload_map_banner or insert or fetch_all"` → **48 passed**.
- Full suite (no testmon): **1942 passed, 2 skipped, 2 xfailed** in 62s.
- `just lint-api` → ruff clean, basedpyright **0 errors, 0 warnings, 0 notes**.
- Ordering proven: `test_upload_precedes_insert` asserts the banner upload mock is called before the insert mock; guard tests assert `insert_map_name` / `upload_map_banner` are NOT called on guard failure.

## TDD Gate Compliance

Each task followed RED → GREEN: a `test(15-03)` commit (failing) precedes each `feat(15-03)` commit. RED was confirmed failing for all three (AttributeError / ModuleNotFoundError) before implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Real-DB repository tests relocated out of `tests/services/`**
- **Found during:** Task 2 (GREEN). `tests/services/conftest.py` overrides `setup_test_db` with a **no-op** (service unit tests run with mocked pools, migrations skipped). The plan's `<verify>` placed the `insert`/`fetch_all` real-DB tests in `tests/services/test_map_content_service.py`, where `maps.names` does not exist (`UndefinedTableError`).
- **Fix:** Moved the real-DB `MapContentRepository` tests to `apps/api/tests/repository/maps/test_map_content_repository.py` (where migrations are applied, matching `test_release_code_repository.py`). `tests/services/test_map_content_service.py` keeps the service-layer tests with a **mocked** `MapContentRepository` + **mocked** `ImageStorageService`. The plan's intent ("inject a mock ImageStorageService and the real test-DB MapContentRepository directly into MapContentService") is preserved in spirit: the service logic (guards/collision/validate) is pure Python over `fetch_all_map_names()` output and is fully covered with a mocked repo; the repository's real SQL behavior is covered by the relocated real-DB tests. The acceptance `-k "insert or fetch_all"` still matches (now in the repository file).
- **Files:** test_map_content_repository.py (new), test_map_content_service.py.
- **Commit:** `6856b7a` (repo + real-DB tests), `90d94e3` (mocked service tests).

**2. [Rule 1 - Bug] Plan's accent-collision test premise corrected**
- **Found during:** Task 1 and Task 3. The plan assumed `Château Guillard` and `Chateau Guillard` collide on the stripped key. They do NOT: `get_map_banner`'s `re.sub(r"[^a-zA-Z0-9]", "", name)` **removes** the accented `â` entirely (it is not ASCII-folded to `a`), so `Château Guillard` → `chteauguillard` while `Chateau Guillard` → `chateauguillard` — **different** keys, no overwrite risk.
- **Fix:** The implementation matches `get_map_banner` byte-for-byte (the load-bearing contract). Adjusted the Task 1 accent test expectation to `chteauguillard.png` (cross-checked against `get_map_banner`). Replaced the Task 3 accent-collision test with a TRUE collision case (internal whitespace: `Lijiang Tower` vs `Lijiang  Tower`, both → `lijiangtower`) and added an explicit `test_accented_vs_ascii_is_not_a_collision` documenting the non-collision. Punctuation collisions (`King's Row` / `Kings Row`) work as planned.
- **Files:** test_upload_map_banner.py, test_map_content_service.py.
- **Commit:** `63b7da3`, `90d94e3`.

## Threat surface

All `<threat_model>` mitigations from the plan are satisfied: `$1` positional params (T-15-06), `_strip_key` reduces the object key to `[a-z0-9]` with a hardcoded `.png` extension and the collision guard prevents cross-map overwrite (T-15-07/T-15-08), and `validate_map_name` + create guards are the runtime replacement for the removed Literal (T-15-09). No new security surface introduced beyond the plan's register. The 25 MB body cap is a route-boundary concern deferred to 15-04 as documented.

## Notes for plan 15-04

- `provide_map_content_service(state, map_content_repo, image_svc)` declares `image_svc: ImageStorageService` as a DI parameter — the controller must wire `Provide(provide_image_storage_service)` AND `Provide(provide_map_content_repository)` in `MapContentController.dependencies`. The end-to-end `from app import app` DI-graph resolution is asserted in 15-04 (intentionally NOT here).
- `validate_map_name` is the consumer-side validator for the submission path; `create_map` does NOT call it (it inserts a NEW name).

## Self-Check: PASSED

All 6 created/modified source files exist on disk; all 6 task commits (`b397311`, `63b7da3`, `5b1c13b`, `6856b7a`, `0e7eb57`, `90d94e3`) are present in git history.
