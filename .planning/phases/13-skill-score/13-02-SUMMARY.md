---
phase: 13-skill-score
plan: 02
subsystem: skill-score
tags: [sdk, msgspec, interface-contract, skill]
requires:
  - "skill.weight_config (single-row typed weight config) — for the Weights field set"
  - "skill.snapshot.breakdown jsonb element shape — for SkillBreakdownRow keys"
provides:
  - "genjishimada_sdk.skill module (Weights, SkillConfigUpdateRequest, SkillSummaryResponse, SkillBreakdownRow)"
  - "CommunityLeaderboardResponse.skill_score (non-optional float)"
affects:
  - "libs/sdk/src/genjishimada_sdk"
tech-stack:
  added: []
  patterns:
    - "msgspec Struct with *Request/*Response suffixes + Google Attributes docstring"
    - "msgspec.UNSET / UnsetType per-field for PATCH partial-update semantics"
    - "SDK module re-export registration in genjishimada_sdk/__init__.py"
key-files:
  created:
    - libs/sdk/src/genjishimada_sdk/skill.py
  modified:
    - libs/sdk/src/genjishimada_sdk/__init__.py
    - libs/sdk/src/genjishimada_sdk/users.py
decisions:
  - "SkillBreakdownRow carries `difficulty: str` (9 fields, per plan <action> line 90 and the spike player_breakdown dict keys), matching the score.py:78-88 output exactly so stored JSONB decodes straight into list[SkillBreakdownRow]."
  - "Weights has NO default values — defaults live only in migration 0027 seed (SPEC req 5: no hardcoded weights in code)."
  - "Registered the new skill module in the SDK __init__.py re-export convention (other domain modules are similarly re-exported)."
  - "skill_score placed adjacent to skill_rank and made non-optional float (SQL COALESCE(...,0) guarantees a value, D-07/D-08); skill_rank label untouched (SPEC req 6)."
metrics:
  duration: "~1m"
  completed: 2026-06-12
  tasks: 2
  files: 3
---

# Phase 13 Plan 02: Skill SDK Wire Contracts Summary

Locked the skill-domain msgspec wire contracts before any consumer is written: a
new `genjishimada_sdk.skill` module exporting the four interface structs, plus a
single non-optional `skill_score: float` field added to
`CommunityLeaderboardResponse`. Every downstream plan (repository, service,
routes, leaderboard) now builds against fixed types.

## What Was Built

**`libs/sdk/src/genjishimada_sdk/skill.py` (new)** — `from __future__ import
annotations` + four msgspec structs (Google docstrings, line length 120):

1. `Weights` — 1:1 with the D-09 `skill.weight_config` row: `diff_base, gamma,
   time_bonus, shrink_k, wr_bonus, partial_factor, medal_gold, medal_silver,
   medal_bronze`, all `float`, all required, **no defaults** (SPEC req 5). This is
   the type `SkillService.fetch_weights()` loads at compute time.
2. `SkillConfigUpdateRequest` — one `float | UnsetType = UNSET` field per weight;
   an omitted field decodes to `UNSET` (PATCH partial-update semantics, mirrors the
   `content.py` UNSET pattern). msgspec strict typing rejects non-float inputs at
   decode (T-13-03).
3. `SkillSummaryResponse` — `user_id, skill_score, maps_cleared, video_clears,
   hardest_raw` (GET `/skill/users/{id}`).
4. `SkillBreakdownRow` — one per-map breakdown entry (the D-06 JSONB array element):
   `map_name, difficulty, raw, fully_verified, medal (str | None), wr, raw_score,
   contribution, rank`. Field names mirror the spike `player_breakdown` dict keys
   (`score.py:78-88`) exactly, so the stored JSONB decodes straight into
   `list[SkillBreakdownRow]` via the app's jsonb<->msgspec codec.

**`libs/sdk/src/genjishimada_sdk/__init__.py` (modified)** — registered the `skill`
module in the existing re-export convention (`from . import (... skill ...)` + `__all__`).

**`libs/sdk/src/genjishimada_sdk/users.py` (modified)** — added a single non-optional
`skill_score: float` to `CommunityLeaderboardResponse`, adjacent to the untouched
`skill_rank: str` label, and documented both in the `Attributes:` docstring. No
existing field renamed, removed, or reordered.

## Verification Performed

- **Task 1 plan verify (`<automated>`):** `msgspec.convert(<full 9-key weights dict>,
  Weights)` succeeds with `.gamma == 0.68`; `SkillBreakdownRow` decodes the spike
  breakdown dict with `medal is None`; `SkillConfigUpdateRequest()` round-trips
  (encode→decode) — printed `ok`.
- **Missing-key guard:** `msgspec.convert({'diff_base':1.44}, Weights)` raises
  `msgspec.ValidationError` (all 9 required).
- **Re-export:** `genjishimada_sdk.skill is skill` and `hasattr(skill, 'Weights')` — `ok`.
- **Task 2 plan verify (`<automated>`):** `{f.name ...}` for
  `CommunityLeaderboardResponse` contains both `skill_score` and `skill_rank` — `ok`.
- **Lint:** `just lint-sdk` clean after each task (ruff format / ruff check / basedpyright: 0 errors).

## Deviations from Plan

None - plan executed exactly as written.

The plan's Pattern-Map struct sketch (13-PATTERNS.md line 321) omitted `difficulty`
from `SkillBreakdownRow`; the authoritative task `<action>` (PLAN line 90) and the
spike `player_breakdown` keys both include it, so the 9-field version was built. Not
a deviation — the plan body is authoritative over the pattern sketch.

## Acceptance Criteria

- [x] `skill.py` defines `Weights`, `SkillConfigUpdateRequest`, `SkillSummaryResponse`, `SkillBreakdownRow`.
- [x] `msgspec.convert(<full weights dict>, Weights)` succeeds, `.gamma == 0.68`; omitting a key raises.
- [x] `SkillConfigUpdateRequest()` round-trips with all fields UNSET.
- [x] `SkillBreakdownRow` decodes the spike breakdown dict; `medal` accepts `None`.
- [x] `Weights` carries NO default values (defaults live in migration seed, SPEC req 5).
- [x] `CommunityLeaderboardResponse` gains non-optional `skill_score: float`; `skill_rank` unchanged.
- [x] `just lint-sdk` clean.

## Self-Check: PASSED

- FOUND: libs/sdk/src/genjishimada_sdk/skill.py
- FOUND: libs/sdk/src/genjishimada_sdk/users.py (skill_score field)
- FOUND commit: 77985ef (feat(13-02): add skill SDK structs)
- FOUND commit: 1250506 (feat(13-02): add skill_score field to CommunityLeaderboardResponse)
