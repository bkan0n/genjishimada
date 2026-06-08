---
phase: 260602-ld2
plan: 01
subsystem: docs
tags: [tournaments, frontend-spec, documentation]
requires: []
provides:
  - "Factual tournament frontend spec aligned to migration 0025"
affects:
  - docs/specs/tournament-frontend-spec.md
tech-stack:
  added: []
  patterns: []
key-files:
  created: []
  modified:
    - docs/specs/tournament-frontend-spec.md
decisions:
  - "Kept the plan-mandated explicit negations (\"There is no POST /cycles/{cycle_id}/submit\" and \"No cycle_frequency\") even though they make the two literal exclusion-greps return nonzero — the plan itself required both statements, and they satisfy the stated truths."
metrics:
  duration: "~5m"
  completed: 2026-06-02
  tasks: 1
  files: 1
---

# Phase 260602-ld2 Plan 01: Rewrite Tournament Frontend Spec Summary

Rewrote `docs/specs/tournament-frontend-spec.md` to be factual and current as of migration 0025 — documents the Edition timing entity, global cadence, and all live `/api/v3/tournaments` endpoints, frames the web frontend as read-only display + admin dashboard (submit/verify happen via the Discord bot), and drops the removed `/submit` route plus the old client-side `ends_at` derivation math.

## What changed

Full replacement of the spec (209 insertions, 150 deletions). New section structure:
1. Mental model — Edition vs Cycle vs Category (Edition is the shared grid-anchored timing parent; cadence is global; automatic `pg_cron` transitions; `awaiting_results` semantics).
2. Auth & scopes — `tournaments:read` / `tournaments:write` / `tournaments:verify` (bot-only).
3. Data models — only fields that exist now, spot-checked against the SDK.
4. Endpoints — split into public read, admin dashboard write, and Discord-bot-only verify/reject; explicitly states there is no web `/submit` route.
5. Frontend flows — view/countdown (from stored `edition.ends_at`), leaderboard, archive, streaks, admin dashboard.
6. Polling & async behavior.
7. Reference values — statuses, cadence, difficulty tiers, ranking rule, verified-vs-completion distinction, champion definition.

## Source-of-truth spot-check

Before finalizing, verified every documented struct field and endpoint against the two source files:

- **Structs** (`libs/sdk/src/genjishimada_sdk/tournaments.py`): `TournamentConfigResponse`, `TournamentCategoryResponse` (no `cycle_frequency`), `TournamentEditionResponse` (stored `started_at`/`ends_at`), `TournamentCycleWithWinnerResponse`, `TournamentCycleListResponse`, `TournamentNextCycleResponse`, `TournamentLeaderboardEntryResponse`, `TournamentStreakResponse`, `TournamentLifecycleResponse`, and all request bodies — field names and types match exactly. Cadence literal is `weekly|biweekly`; cycle statuses `pending|active|finalizing|completed`; edition statuses `active|awaiting_results|completed`.
- **Endpoints** (`apps/api/routes/v3/tournaments.py`): all 20 routes confirmed by path, method, scope, and status/error codes — incl. `GET /editions/active`, `POST /bootstrap`, `PATCH /publish-results`, `PATCH /pause`, `PATCH /debug-cycle-length`, `POST /categories/{id}/reroll-active`, and the bot-only `tournaments:verify` verify/reject routes. Confirmed there is no `/submit` route in the controller.

## Verification (content greps, no code/tests run)

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| `/editions/active` present | ≥1 | 3 | PASS |
| `reroll-active` present | ≥1 | 3 | PASS |
| `publish-results` present | ≥1 | 5 | PASS |
| `bootstrap` present | ≥1 | 4 | PASS |
| old `ends_at` derivation math (7/14 days) | 0 | 0 | PASS |
| submit-route literal grep | 0 | 1 | see note |
| `cycle_frequency` literal grep | 0 | 2 | see note |

Manual read confirmed: cadence presented as global `config.cadence`; countdown reads stored `edition.ends_at` directly with no `started_at + cadence` math; frontend scope stated as read-only display + admin dashboard with submission/verify via the Discord bot.

## Deviations from Plan

The two literal exclusion-greps (`/submit` route and `cycle_frequency`) return nonzero, but every match is a **plan-mandated explicit negation**, not a real occurrence:

- Line 264: `**There is no \`POST /cycles/{cycle_id}/submit\`.**` — the plan (action step, line 119) explicitly required this sentence.
- Lines 93 & 186: `No \`cycle_frequency\` — cadence is global config.` — the plan (lines 83, 91) explicitly required documenting that the field is gone.

The grep targets in the plan's `<verify>` are a proxy for the intent "the removed route / removed field is not documented as live." That intent is fully satisfied: the spec documents no submit route and no per-category cadence; the only textual matches are the negating statements the plan itself dictated. Removing them to force the greps to 0 would delete content the plan required, so the plan-mandated wording was kept. No code or behavior involved.

## Self-Check: PASSED

- FOUND: docs/specs/tournament-frontend-spec.md
- FOUND commit: 3ecd817 (docs(260602-ld2): rewrite tournament frontend spec for migration 0025)
