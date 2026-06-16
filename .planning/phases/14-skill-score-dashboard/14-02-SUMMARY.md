---
phase: 14-skill-score-dashboard
plan: 02
subsystem: skill-dashboard-contracts
tags: [sdk, msgspec, events, wire-contracts, skill]
requires:
  - "Phase 13 skill SDK module (libs/sdk/.../skill.py) + SkillRecomputeRequestedEvent (Phase 13 13-05)"
  - "Migration 0031 cause_category CHECK (Plan 14-01) as the DB backstop for the Literal"
provides:
  - "SkillHistoryResponse / SkillHistoryPoint / SkillHistorySummary / SkillHistoryExtremum (req 3)"
  - "SkillChangeFeedItem (req 4)"
  - "SkillChangeCause / SkillChangeDetailResponse (req 5)"
  - "CauseCategory Literal[PLAYER_ACTION, MAP_ENVIRONMENT, SYSTEM] — single SDK source for the closed set"
  - "SkillRecomputeRequestedEvent.cause_category (str, default SYSTEM) + actor_user_id (int|None) [D-10]"
affects:
  - "Wave 2 repository (history/change reads), Wave 2/3 service capture + cause threading, Wave 3 routes, Wave 4 tests"
  - "apps/api/events/skill.py listener + completions_service.py emit sites (downstream, thread actor_user_id)"
tech-stack:
  added: []
  patterns:
    - "text + msgspec Literal for closed sets (CauseCategory), not DB enums — codebase idiom"
    - "Event module kept dependency-light: cause_category as plain str on the API-side event, SDK Literal only on response structs"
    - "*Response for reads, *Item/*Point/*Cause/*Extremum for nested array elements"
key-files:
  created: []
  modified:
    - "libs/sdk/src/genjishimada_sdk/skill.py (7 new structs + CauseCategory Literal + __all__)"
    - "apps/api/events/schemas.py (SkillRecomputeRequestedEvent: +cause_category, +actor_user_id)"
decisions:
  - "cause_category on the event is a plain str default 'SYSTEM' (not the SDK Literal) — keeps events/schemas.py dependency-light; the service validates against the closed set (per Task 2 action)"
  - "reason kept first; the two new event fields appended with defaults so positional + keyword construction stay backward-compatible (no unmigrated emitter breaks)"
metrics:
  duration: "~3 min"
  completed: 2026-06-16
  tasks: 2
  files: 2
---

# Phase 14 Plan 02: Skill Dashboard Wire Contracts Summary

Interface-first wire contracts for the skill dashboard: seven new msgspec response
structs + the `CauseCategory` Literal in the SDK, and the `SkillRecomputeRequestedEvent`
enriched with the typed `cause_category` + `actor_user_id` (D-10) fields — so Waves 2-4
implement against fixed contracts instead of exploring the codebase.

## What Was Built

**Task 1 — SDK dashboard response structs + `CauseCategory` Literal** (`libs/sdk/src/genjishimada_sdk/skill.py`):
- `CauseCategory = Literal["PLAYER_ACTION", "MAP_ENVIRONMENT", "SYSTEM"]` — the single SDK
  source of truth for the closed set; the migration 0031 CHECK is the DB-side backstop.
- History (req 3): `SkillHistoryPoint` (`captured_at`, `skill_score`), `SkillHistoryExtremum`
  (`score`, `date: datetime | None`), `SkillHistorySummary` (`point_change`, `percent_change`,
  `best`, `lowest`, `average`), `SkillHistoryResponse` (`user_id`, `points`, `summary`).
- Feed (req 4): `SkillChangeFeedItem` (`change_id`, `captured_at`, `delta`, `cause_category`,
  `description`).
- Drill-down (req 5): `SkillChangeCause` (`map`, `reason`, `impact`), `SkillChangeDetailResponse`
  (`change_id`, `captured_at`, `previous_score`, `new_score`, `delta`, `percent_change`,
  `cause_category`, `main_causes`, `other_factors`).
- All seven new struct names + `CauseCategory` added to the `__all__` tuple. Imported
  `Literal` from `typing`. No existing struct (Weights, SkillSummaryResponse, SkillBreakdownRow,
  SkillTiersResponse, etc.) touched — Phase 13 surface frozen.

**Task 2 — Enriched `SkillRecomputeRequestedEvent`** (`apps/api/events/schemas.py`):
- Added `cause_category: str = "SYSTEM"` — plain `str` (NOT the SDK Literal) defaulting to
  `"SYSTEM"` so config/tier/nightly/cold-start emitters construct cleanly; the service
  validates against the closed set.
- Added `actor_user_id: int | None = None` — the completion owner for a single clean
  PLAYER_ACTION trigger; `None` for SYSTEM.
- `reason` kept first; new fields appended with defaults → existing
  `SkillRecomputeRequestedEvent(reason=...)` calls and the `events/skill.py` listener
  remain backward-compatible. No other event struct modified.

## Verification Results

- **Task 1 automated verify:** `SDK structs OK` — `SkillHistoryResponse` round-trips with
  empty points + zero summary (the SPEC req 7 empty shape); `SkillChangeDetailResponse`
  round-trips with a `main_causes` list + `other_factors` scalar (`cause_category=='PLAYER_ACTION'`).
- **CauseCategory closed-set:** decoding a `SkillChangeDetailResponse` with `cause_category="BOGUS"`
  raises `msgspec.ValidationError` (`BOGUS rejected OK`) — T-14-04 mitigated at decode.
- **Task 2 automated verify:** `event OK` — `E()` → `cause_category=='SYSTEM'`, `actor_user_id is None`,
  `reason is None`; `E(reason='x')` still constructs; `E(reason='verify', cause_category='PLAYER_ACTION', actor_user_id=42)` constructs with expected values.
- **`just lint-sdk`:** ruff format/check + basedpyright — 0 errors, 0 warnings.
- **`just lint-api`:** ruff format/check + basedpyright — 0 errors, 0 warnings.

## Deviations from Plan

None - plan executed exactly as written.

## Threat Model Notes

- **T-14-04 (Tampering, CauseCategory Literal) — mitigated:** msgspec strict decode rejects
  any value outside the closed set in responses (verified: `BOGUS` raises ValidationError),
  defense alongside the migration 0031 DB CHECK.
- **T-14-05 (Spoofing, actor_user_id) — accepted:** the event is in-process only (Litestar
  `app.emit`), never external input; actor id is supplied by trusted server code (downstream
  `completions_service`). No new external surface introduced by this plan.

## Self-Check: PASSED

- libs/sdk/src/genjishimada_sdk/skill.py — modified, FOUND
- apps/api/events/schemas.py — modified, FOUND
- Commit 0501374 (Task 1) — FOUND
- Commit d3129e5 (Task 2) — FOUND
