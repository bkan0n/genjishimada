---
phase: 11-tournament-verification-flow
plan: 01
subsystem: tournaments
tags: [contracts, repository, sdk, rabbitmq, tests]
requires: []
provides:
  - "tournaments_repository.get_active_cycle_by_map_id (D-01 auto-detect)"
  - "tournaments_repository.set_tournament_verified (D-04a/D-06 verify flip)"
  - "SDK TournamentVerificationChangedEvent + extended TournamentCompletionCreatedEvent"
  - "RabbitMQ api.tournament.completion.created + api.tournament.verification.changed (+ DLQs)"
  - "events.schemas.TournamentOcrVerificationRequestedEvent"
  - "Wave-0 SC-2/SC-3 test scaffold (test_tournament_verification.py)"
affects:
  - "11-02 (submit hook): consumes get_active_cycle_by_map_id + fetch_map_metadata_by_code"
  - "11-03 (verify surface): consumes set_tournament_verified + new queues + OCR schema"
tech-stack:
  added: []
  patterns:
    - "asyncpg positional-param lookups via _get_connection(conn)"
    - "per-queue DLQ isolation (Phase 09-03)"
    - "xfail(strict=False) Wave-0 test stubs"
key-files:
  created:
    - apps/api/tests/services/test_tournament_verification.py
  modified:
    - apps/api/repository/tournaments_repository.py
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - infra/rabbitmq/definitions.json
    - apps/api/events/schemas.py
decisions:
  - "Reused completions_repository.fetch_map_metadata_by_code as the code->map_id resolver (returns map_id, difficulty, category) instead of adding a duplicate lookup_map_id"
  - "Extended TournamentCompletionCreatedEvent (user_id, time, video, screenshot) so the bot embed needs no extra fetch (RESEARCH: fewer round-trips)"
  - "No verified_by field on TournamentVerificationChangedEvent (table has no such column; 0023 migration out of scope)"
metrics:
  duration: 9min
  completed: 2026-05-31
  tasks: 3
  files: 5
---

# Phase 11 Plan 01: Tournament Verification Contracts Summary

Interface-first landing of the Phase 11 verification contracts: two new tournament repo lookups, the new/extended SDK event structs, two new RabbitMQ queues with isolated DLQs, the in-process OCR-variant schema, and a green Wave-0 SC-2/SC-3 test scaffold — all with zero behavior change so the hot-path edits in 11-02/11-03 can build directly against them.

## What Was Built

**Task 1 — repo lookups (commit cbe822c)**
- `TournamentRepository.get_active_cycle_by_map_id(map_id, *, conn)` → `dict | None`: `SELECT id, category_id, map_id, status FROM tournaments.cycles WHERE map_id = $1 AND status = 'active' LIMIT 1` (D-01/D-02; backed by `idx_cycles_map_id`).
- `TournamentRepository.set_tournament_verified(tournament_completion_id, verified=True, *, conn)` → `dict | None`: `UPDATE tournaments.completions SET verified = $2 WHERE id = $1 RETURNING id, cycle_id, user_id, time` (D-04a/D-06; idempotent).
- **code→map_id resolver:** reused existing `CompletionsRepository.fetch_map_metadata_by_code(code)` (returns `map_id`, `difficulty`, `category`) — no new `lookup_map_id` added. 11-02 reads `["map_id"]` to feed `get_active_cycle_by_map_id`.
- Preserved `cross_write_to_core` and `create_tournament_completion` unchanged (PB path).

**Task 2 — SDK events (commit b4dd6db)**
- Extended `TournamentCompletionCreatedEvent` field order: `completion_id, cycle_id, user_id, time, video, screenshot`.
- Added `TournamentVerificationChangedEvent` field order: `tournament_completion_id, cycle_id, user_id, verified, time`.
- `__all__` updated (sorted; `TournamentVerificationChangedEvent` inserted before `TournamentXpGrantEvent`). `just fix` run so API+bot resolve the workspace package.

**Task 3 — queues + schema + tests (commit d12acb9)**
- `infra/rabbitmq/definitions.json`: added `api.tournament.completion.created` (+ `.dlq`) and `api.tournament.verification.changed` (+ `.dlq`), copying the `api.tournament.cycle_started` block (durable, classic, per-queue DLQ routing).
- `events/schemas.py`: `TournamentOcrVerificationRequestedEvent` (`tournament_completion_id, cycle_id, user_id, code, time, screenshot`).
- `tests/services/test_tournament_verification.py`: 2 passing contract-pin tests + 4 `xfail(strict=False)` SC-2/SC-3 stubs (`pb_path` / `non_pb_path`, `-k`-selectable).

## New Queue Names
- `api.tournament.completion.created` + `api.tournament.completion.created.dlq`
- `api.tournament.verification.changed` + `api.tournament.verification.changed.dlq`

## Deviations from Plan

None — plan executed as written. The plan's optional `lookup_map_id` addition was intentionally skipped per the plan's own instruction (reuse if a resolver exists): `fetch_map_metadata_by_code` already returns `map_id`.

## Deferred Issues

- Pre-existing RUF100 unused-`noqa` (`PLR0913`) on `claim_xp_grant` (tournaments_repository.py:869) — present in HEAD before this plan, out of scope, not fixed. Logged in `deferred-items.md`.

## Verification Evidence
- `python -c "import json; json.load(...definitions.json)"` → ok; all four queue names present.
- `uv run python -c "from genjishimada_sdk.tournaments import TournamentVerificationChangedEvent"` → ok (after `just fix`).
- `uv run --directory apps/api pytest tests/services/test_tournament_verification.py -p no:xdist -q` → 2 passed, 4 xfailed.
- `ruff check` on changed repo + schema files → no new errors (only the pre-existing L869 RUF100).

## Self-Check: PASSED
- All 5 key files exist on disk.
- All 3 commits (cbe822c, b4dd6db, d12acb9) found in git log.
