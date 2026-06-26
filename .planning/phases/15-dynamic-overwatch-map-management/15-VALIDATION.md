---
phase: 15
slug: dynamic-overwatch-map-management
status: draft
nyquist_compliant: false
wave_0_complete: false
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

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest apps/api/tests/integration/test_<touched>.py -x` (< 30s)
- **After every plan wave:** Run `just test-api` (full API suite, parallel)
- **Before `/gsd:verify-work`:** `just ci` (lint + test-all) must be green
- **Max feedback latency:** ~30 seconds (per-task quick run)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner; rows below map each phase REQ to its automated proof. The executor binds these to concrete task IDs as plans are written.

| Req | Behavior | Wave | Test Type | Automated Command | File Exists | Status |
|-----|----------|------|-----------|-------------------|-------------|--------|
| REQ-01 | `MapCreateRequest`/submission accepts a name absent from the old Literal | 1 | integration | `pytest apps/api/tests/integration/test_maps_integration.py -k create -x` | ✅ extend | ⬜ pending |
| REQ-02 | Unknown map name → 422 with "did you mean" suggestion | 1 | unit/integration | `pytest -k validate_map_name -x` | ❌ W0 | ⬜ pending |
| REQ-03 | `POST /content/maps` mixed multipart decodes name+banner → 201 | 2 | integration | `pytest -k create_map -x` | ❌ W0 | ⬜ pending |
| REQ-04 | Re-upload banner for existing map overwrites same key | 2 | integration | `pytest -k replace_banner -x` | ❌ W0 | ⬜ pending |
| REQ-05 | Empty/blank name → 422 | 2 | integration | `pytest -k empty_name -x` | ❌ W0 | ⬜ pending |
| REQ-06 | Stripped-key collision (King's Row / Kings Row) → 422 | 2 | unit/integration | `pytest -k collision -x` | ❌ W0 | ⬜ pending |
| REQ-07 | `upload_map_banner` writes `assets/map_banners/{stripped}.png` | 2 | unit | `pytest -k upload_map_banner -x` | ❌ W0 | ⬜ pending |
| REQ-08 | `GET /utilities/map-names` returns all rows sorted, no search | 2 | integration | `pytest apps/api/tests/integration/test_autocomplete_integration.py -k map_names -x` | ❌ W0 extend | ⬜ pending |
| REQ-10 | `MapNameSelect` pagination math with DB-fed list | 3 | unit | `pytest -k map_name_select -x` | ❌ W0 | ⬜ pending |
| REQ-11 | FK orphan pre-flight raises on orphan; FK added clean otherwise | 1 | integration (schema) | `pytest -k map_name_fk -x` | ❌ W0 | ⬜ pending |
| REQ-12 | Seed replays idempotently (no duplicate-PK error) | 1 | integration (schema) | `pytest -k seed_idempotent -x` | ❌ W0 | ⬜ pending |
| REQ-13 | All 70 reconciled maps present in `maps.names` after migration | 1 | integration | `pytest -k phantom_maps -x` | ❌ W0 | ⬜ pending |
| REQ-15 | Added map appears: website read (fetch_maps), submission accept, full-list endpoint | 2 | integration | `pytest -k appears_everywhere -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **Update 14 test files** replacing `get_args(OverwatchMap)` with a seed-name constant — `get_args` returns `()` after the flip and breaks `fake.random_element`, blocking the WHOLE suite. **Must land in the same wave as the SDK flip.**
- [ ] Map-create tests in `apps/api/tests/integration/test_content_integration.py` (extend) or a new `test_map_content_integration.py` — REQ-03/04/05/06.
- [ ] `validate_map_name` + `strip_key`/collision unit tests — REQ-02/06.
- [ ] `upload_map_banner` unit test with mocked S3 client — REQ-07.
- [ ] `GET /utilities/map-names` test in `test_autocomplete_integration.py` (extend) — REQ-08.
- [ ] Migration tests (FK orphan guard, seed idempotency, phantom reconciliation) — REQ-11/12/13. Mirror an existing schema-test pattern (`test_tournaments_schema.py`).
- [ ] Bot unit test for `MapNameSelect` pagination with DB-fed list — REQ-10.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| discord.py `MapNameSelect` dropdown renders the DB-fed list in the moderator wizard | REQ-10 | No bot test harness in `apps/api/tests`; discord.py UI requires a live gateway | Run bot, open the map-edit wizard in the moderator cog, confirm the map-name dropdown shows DB rows (including a newly-added map) and paginates |
| Newly-added map banner resolves on the website surface | REQ-15 | Read path derives the URL via `get_map_banner()`; CDN/R2 round-trip | After `POST /content/maps`, fetch the map and confirm `assets/map_banners/{stripped}.png` resolves to the uploaded image |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (esp. the 14 `get_args(OverwatchMap)` test updates)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
