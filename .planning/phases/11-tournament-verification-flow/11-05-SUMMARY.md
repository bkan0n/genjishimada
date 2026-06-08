---
phase: 11-tournament-verification-flow
plan: 05
subsystem: tournaments
tags: [bot, rabbitmq, verification, discord-ui, tests]
requires:
  - "SDK TournamentCompletionCreatedEvent (extended) + TournamentVerificationChangedEvent (11-01)"
  - "RabbitMQ api.tournament.completion.created + api.tournament.verification.changed (+ DLQs, 11-01)"
  - "PATCH /tournaments/completions/{id}/verify|reject, scope tournaments:verify (11-03)"
provides:
  - "TournamentHandler._on_completion_created consumer (renders the mod Accept/Reject card)"
  - "TournamentHandler._on_verification_changed consumer (surfaces the verdict)"
  - "TournamentVerificationView + Accept/Reject buttons (distinct custom_ids tournament:accept/reject)"
  - "api_service.verify_tournament_completion / reject_tournament_completion bot client methods"
affects: []
tech-stack:
  added: []
  patterns:
    - "@queue_consumer(idempotent=True) — outbox message_id is the only dedupe key (Phase-9)"
    - "AllowedMentions(everyone=False, roles=False) + numeric <@id> mentions (Phase-9 mention-injection mitigation)"
    - "bot never writes the DB — Accept/Reject route through the tournaments:verify API (T-11-17)"
    - "sync def returning self._request (Phase-10 bot-client convention)"
key-files:
  created: []
  modified:
    - apps/bot/extensions/tournaments.py
    - apps/bot/extensions/api_service.py
    - apps/api/tests/bot/test_tournaments_handler.py
decisions:
  - "Reused the existing mod verification queue (channels.submission.verification_queue) for the tournament card rather than a dedicated channel (CONTEXT discretion default — mods already watch this queue)"
  - "Reject sends NO reason payload — the 11-03 reject endpoint takes none (Open-Q1, row left unverified); a local TournamentRejectionReasonModal gates the reject (empty submit cancels) and surfaces the reason to the moderator only"
  - "Local TournamentRejectionReasonModal (not imported from completions) so monkeypatch in tests can swap it and to keep the cog self-contained"
  - "No submit-bypass bot tests existed to rewrite — 11-04 removed the API-side bypass; this bot test file only had cycle + idempotency tests"
metrics:
  duration: 3min
  completed: 2026-05-31
  tasks: 2
  files: 3
---

# Phase 11 Plan 05: Bot Non-PB Tournament Verification Surface Summary

Wires the bot half of D-04's video path: a `TournamentHandler` consumer renders a mod Accept/Reject card for non-PB video tournament runs and a second consumer surfaces the verdict, with the Accept/Reject buttons routing the moderator's decision to the `tournaments:verify` API (the bot never writes the DB).

## What Was Built

**Task 1 — view + two consumers (commit f4560f8)**
- `TournamentVerificationView` (`ui.LayoutView`): renders the run's screenshot (`ui.MediaGallery`), time, cycle, optional video, and submitter (`<@user_id>`) directly from the `TournamentCompletionCreatedEvent` — no extra API fetch (the event carries everything, 11-01).
- `TournamentVerificationAcceptButton` (`custom_id="tournament:accept"`, green) — defers, disables children, edits the message, calls `bot.api.verify_tournament_completion(completion_id)`, then `poll_job_until_complete`.
- `TournamentVerificationRejectButton` (`custom_id="tournament:reject"`, red) — opens `TournamentRejectionReasonModal`; on a non-empty reason disables children, edits, and calls `bot.api.reject_tournament_completion(completion_id)`; an empty reason cancels.
- Both custom_ids are DISTINCT from the completions view's `completions:accept`/`completions:reject` (P3 / T-11-18).
- `@queue_consumer("api.tournament.completion.created", idempotent=True)` → builds the view and posts it to the shared mod verification queue with `AllowedMentions(everyone=False, roles=False)`.
- `@queue_consumer("api.tournament.verification.changed", idempotent=True)` → posts a verified/rejected confirmation line referencing the submitter by numeric `<@id>` with the same mention restrictions.
- `_resolve_channels` now also resolves `verification_channel` from `channels.submission.verification_queue`.

**Task 2 — bot client methods + tests (commit e8dceab)**
- `api_service.verify_tournament_completion(tc_id)` → `Route("PATCH", "/tournaments/completions/{tc_id}/verify")`, `JobStatusResponse`.
- `api_service.reject_tournament_completion(tc_id)` → `Route("PATCH", "/tournaments/completions/{tc_id}/reject")`, `JobStatusResponse`, no body (endpoint takes no reason).
- 5 new handler tests: completion-created posts the view (asserts `completion_id` + mention mitigation); Accept calls `verify_tournament_completion(77)`; Reject (with reason) calls `reject_tournament_completion(77)`; empty reason cancels; verification-changed surfaces the verdict.

## Verification Channel Reused
The EXISTING mod verification queue (`channels.submission.verification_queue`) — not a dedicated channel. Mods already watch this queue for completion review (CONTEXT discretion default).

## Reject Payload Shape
None. The 11-03 reject endpoint takes no body (the row is left unverified, Open-Q1). The reason modal gates the reject and shows the reason to the moderator only; it is not forwarded to the API.

## Submit-Bypass Bot Tests Rewritten
None existed. 11-04 removed the API-side submit bypass; this bot test file contained only the cycle-announcement and idempotency tests, neither of which referenced a bypass.

## Deviations from Plan

None — plan executed as written.

## Threat Mitigations Verified

| Threat ID | Mitigation | Evidence |
|-----------|-----------|----------|
| T-11-17 | bot never writes DB — Accept/Reject call the tournaments:verify API | grep: no asyncpg/pool/fetch/execute in tournaments.py view code |
| T-11-18 | distinct custom_ids tournament:accept / tournament:reject | grep: each present exactly once, distinct from completions:* |
| T-11-19 | AllowedMentions(everyone=False, roles=False) + numeric `<@id>` | both consumers post with the restriction; tests assert it |
| T-11-20 | @queue_consumer(idempotent=True) on both consumers | outbox message_id dedupe; idempotency wrapper test (pre-existing) covers the path |

## Verification Evidence
- `uv run --directory apps/api pytest tests/bot/test_tournaments_handler.py -p no:xdist -q` → 15 passed (10 existing + 5 new).
- `cd apps/bot && uv run ruff check extensions/tournaments.py extensions/api_service.py` → All checks passed.
- `cd apps/bot && uv run basedpyright extensions/tournaments.py extensions/api_service.py` → 0 errors, 0 warnings.
- Acceptance greps: `tournament:accept`/`tournament:reject` == 1 each; two new consumers present; verify/reject client methods present building the correct PATCH routes.

## Self-Check: PASSED
- All 3 modified files + SUMMARY.md exist on disk.
- Both commits (f4560f8, e8dceab) found in git log.
