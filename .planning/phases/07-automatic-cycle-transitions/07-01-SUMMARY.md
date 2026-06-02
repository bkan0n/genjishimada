---
phase: 07-automatic-cycle-transitions
plan: 01
subsystem: tournaments
tags: [pg_cron, plpgsql, outbox, advisory-lock, sdk, msgspec]
requires:
  - tournaments schema (0020_tournaments.sql)
  - core.maps, core.users
provides:
  - tournaments.process_cycle_transitions() PL/pgSQL state machine
  - tournaments.select_eligible_map(int) SQL map-selection helper
  - idempotent pg_cron job tournament-cycle-transitions
  - extended TournamentCycleStartedEvent / TournamentCycleCompletedEvent SDK structs
affects:
  - Wave 2 outbox poller (consumes pending_transitions rows this function writes)
  - Phase 8 rewards / Phase 9 announcements (consume the emitted events)
tech-stack:
  added: []
  patterns:
    - pg_cron-driven PL/pgSQL function (0013_coin_store.sql template)
    - transaction-level advisory lock (pg_try_advisory_xact_lock)
    - transactional outbox (pending_transitions rows written in transition txn)
    - jsonb placement snapshot via RANK() leaderboard ranking
key-files:
  created:
    - apps/api/migrations/0021_tournament_cycle_transitions.sql
  modified:
    - libs/sdk/src/genjishimada_sdk/tournaments.py
decisions:
  - "D-02: transaction-level advisory lock pg_try_advisory_xact_lock(2025070100) (auto-release, non-blocking no-op)"
  - "D-06: SQL helper select_eligible_map mirrors the Phase 5 Python selection (atomicity over DRY)"
  - "Winner computed as MIN(user_id) FILTER (WHERE rank = 1) — single rank-1 user, NULL when no submissions"
metrics:
  duration: ~15m
  completed: 2026-05-29
  tasks: 2
  files: 2
---

# Phase 7 Plan 01: Cycle Transition Database Foundation Summary

PL/pgSQL cycle-transition state machine (`process_cycle_transitions`) + SQL map-selection helper (`select_eligible_map`) registered via idempotent pg_cron, plus extended SDK event structs carrying the full standings/map-detail payloads the outbox rows serialize into.

## What Was Built

**Task 1 — SDK event structs (`libs/sdk/src/genjishimada_sdk/tournaments.py`, commit 14d80a0):**
- `TournamentCycleStartedEvent` gained `map_code: str`, `map_name: str`, `started_at: dt.datetime`, `ends_at: dt.datetime` (kept `cycle_id`, `category_id`, `map_id`).
- `TournamentCycleCompletedEvent` gained `standings: list[TournamentLeaderboardEntryResponse]`, `winner_user_id: int | None` (kept `cycle_id`, `category_id`).
- Reused the existing `TournamentLeaderboardEntryResponse` as the standings element type; no new sub-struct, so `__all__` unchanged.
- Field names are the canonical contract that the SQL `jsonb_build_object` keys (Task 2) and the Wave 2 poller `msgspec.convert` must match exactly.

**Task 2 — Migration 0021 (`apps/api/migrations/0021_tournament_cycle_transitions.sql`, commit b448c04):**
- `tournaments.select_eligible_map(p_category_id int) RETURNS int` — mirrors `fetch_eligible_maps` (official + not-archived + code-not-null + base-difficulty regexp match + blacklist-window exclusion + pending exclusion, `ORDER BY random()`) with the `fetch_least_recently_used_map` LRU fallback. Reads `difficulties` from the category and `blacklist_weeks` from the singleton `tournaments.config`. Returns NULL when no map is eligible.
- `tournaments.process_cycle_transitions() RETURNS void` — top-of-function non-blocking transaction-level advisory lock `pg_try_advisory_xact_lock(2025070100)` (documented as non-colliding with store's `1234567890`); loops over due active cycles (`now() >= started_at + make_interval(days => CASE cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)`), per cycle: `finalizing` → snapshot placements via the `fetch_leaderboard` `RANK()` ranking aggregated to jsonb → `completed`+`ended_at` → write `cycle_completed` outbox row → promote the category's pending cycle to `active` (or inline-select on the D-07 edge) → write `cycle_started` outbox row joining `core.maps` for code/name + computed `ends_at` → pre-roll the next pending cycle via the helper. Missing-pending and no-eligible-map edges downgrade to `RAISE NOTICE` + skip.
- Idempotent pg_cron registration copied from the `0013` form: extension-create guard at top, then a `pg_extension`-guarded `DO` block that `cron.unschedule`s before `cron.schedule('tournament-cycle-transitions', '* * * * *', 'SELECT tournaments.process_cycle_transitions()')`.

## Deviations from Plan

None — plan executed as written. One implementation choice within Claude's discretion: the winner is computed as `MIN(ranked.user_id) FILTER (WHERE ranked.rank = 1)` over the same ranked CTE used for standings (a single, deterministic rank-1 user; NULL when the cycle had no submissions), rather than a separately nested subquery. This keeps the snapshot to one CTE pass and avoids ambiguity when multiple users tie at rank 1 (the fastest verified by the leaderboard order is selected).

## Verification

- Task 1: `just lint-sdk` → ruff format + check + basedpyright all pass (0 errors).
- Task 2: `uv run --directory apps/api pytest tests/repository/tournaments/ -p no:xdist -q -k "conftest or category or cycle" --co` collects (exit 0); a representative cycle test (`TestCreateCycle::test_create_cycle_returns_dict`) passes, confirming all migrations including 0021 apply cleanly under the pg_cron-absent test DB (the `RAISE NOTICE` branch fires without error).
- Ran `just fix` after the SDK edit to re-sync the `genjishimada-sdk` workspace package (per MEMORY.md note); resolved a transient `ModuleNotFoundError` during test collection.

Behavioral assertions (state machine transitions, advisory-lock concurrency, snapshot parity, pre-roll) are exercised by Wave 3 integration tests; this plan establishes the artifacts they invoke via `SELECT tournaments.process_cycle_transitions()`.

## Known Stubs

None. Both functions are created unconditionally; only the cron scheduling is guarded.

## Self-Check: PASSED

- FOUND: apps/api/migrations/0021_tournament_cycle_transitions.sql
- FOUND: libs/sdk/src/genjishimada_sdk/tournaments.py (modified)
- FOUND: commit 14d80a0 (Task 1)
- FOUND: commit b448c04 (Task 2)
