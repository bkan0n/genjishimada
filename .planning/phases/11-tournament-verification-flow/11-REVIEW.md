---
phase: 11-tournament-verification-flow
reviewed: 2026-05-31T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - apps/api/events/completions.py
  - apps/api/events/schemas.py
  - apps/api/repository/completions_repository.py
  - apps/api/repository/tournaments_repository.py
  - apps/api/routes/v3/completions.py
  - apps/api/routes/v3/tournaments.py
  - apps/api/services/completions_service.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/services/tournament_service.py
  - apps/api/tests/bot/test_tournaments_handler.py
  - apps/api/tests/integration/test_tournament_rewards.py
  - apps/api/tests/integration/test_tournaments_integration.py
  - apps/api/tests/repository/tournaments/test_cycle_transitions.py
  - apps/api/tests/services/test_completions_service.py
  - apps/api/tests/services/test_tournament_service.py
  - apps/api/tests/services/test_tournament_verification.py
  - apps/bot/extensions/api_service.py
  - apps/bot/extensions/tournaments.py
  - infra/rabbitmq/definitions.json
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - scripts/seed-tournament-local.sh
findings:
  critical: 1
  warning: 7
  info: 4
  total: 12
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-05-31
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Reviewed the tournament verification flow: the API verify/reject service+repo+route, the
non-PB submit branch in `completions_service`, the OCR auto-verify variant, the SDK events,
the RabbitMQ topology, the bot consumer/view, and the seed script. The implementation is
careful and well-documented — transaction boundaries are mostly correct, the XP ledger
(08-01) provides a real double-grant guard, mention-injection is mitigated in the bot, and
the FK/unique → 409 translation on the submit path (commit `9b36dbe`) is correct and
test-covered.

The adversarial pass concentrated on the verify/reject state machine. The migration
(`0020_tournaments.sql`) was confirmed: `tournaments.completions` has only a single
`verified boolean NOT NULL DEFAULT FALSE` — there is NO `verified_by`/status column, so
"rejected" and "never reviewed" are the same DB state. That single-bit design plus an
unconditional `UPDATE ... SET verified = $2` is the root of the one BLOCKER: a
verify-then-reject sequence (by a second mod, or via at-least-once redelivery of the reject
message) silently flips an already-verified run back to `verified=FALSE`, re-publishes a
`verified=False` event, and does NOT reverse the participation XP already granted — leaving
the XP ledger and the completion row permanently inconsistent. The verify-twice integration
test only proves the XP LEDGER is idempotent; nothing tests reject-after-verify, so this is
invisible in CI.

The remaining findings are robustness/maintainability concerns: publish-after-commit
dual-write of the verified event with no outbox (the cycle lifecycle DOES use the
`pending_transitions` outbox, so this is an inconsistency), the broad `except Exception` in
the OCR path that can double-surface a run as both auto-verified and mod-review, the bot
button disabling components before the API call succeeds, a phantom-event publish on a
TOCTOU-deleted row, and the masked seed-script failure.

No `<structural_findings>` block was provided, so all findings below are narrative
(direct-read).

## Critical Issues

### CR-01: Reject reverts an already-verified run and de-syncs XP (no terminal guard, no reversal)

**File:** `apps/api/services/tournament_service.py:570-645` (`_set_verified`) + `apps/api/repository/tournaments_repository.py:1043-1076` (`set_tournament_verified`)
**Issue:** `set_tournament_verified` is an unconditional
`UPDATE tournaments.completions SET verified = $2 WHERE id = $1` with no guard on the
current state, and `_set_verified` calls it for BOTH verify (`verified=True`) and reject
(`verified=False`). The migration confirms `tournaments.completions` has only a single
`verified` boolean — no `verified_by`/terminal-status column — so "verified" is the only
state bit. Two real sequences corrupt state:

1. **verify then reject** — a run is verified (participation XP granted via the 08-01
   ledger; row `verified=TRUE`), then a moderator hits Reject (the Accept and Reject
   buttons coexist on the same card and are only disabled per-card, so a second mod on a
   re-fetched card, or a stale card, can still reject). `set_tournament_verified(id, False)`
   flips the row back to `verified=FALSE`, dropping it below verified runs on the
   `idx_tournament_completions_ranking` leaderboard, and publishes a `verified=False`
   event — but the participation XP is NOT reversed (reject takes the `award_xp=False`
   path and never touches `tournaments.xp_grants`). Net: the player keeps the XP yet loses
   verified standing — a permanent divergence between the ledger and the completion row.
2. **redelivered reject** — RabbitMQ is at-least-once (CLAUDE.md), and the verify/reject
   endpoints are driven by the bot consumer. A redelivered or manually-replayed reject after
   a verify reproduces (1) with no second moderator at all.

The verify-side tests only assert the XP ledger is idempotent
(`test_verify_tournament_completion_twice_awards_xp_once`, lines 469-502; integration
`test_verify_twice_grants_participation_once`). None assert that reject-after-verify is
refused or that XP is reconciled, so this gap passes CI.
**Fix:** Make the transition conditional and refuse the no-op/illegal transition instead of
silently flipping, and gate the publish/grant on a real state change:
```python
# repository: only transition when the value actually changes; report it
row = await _conn.fetchrow(
    """
    UPDATE tournaments.completions
    SET verified = $2
    WHERE id = $1 AND verified IS DISTINCT FROM $2
    RETURNING id, cycle_id, user_id, time
    """,
    tournament_completion_id, verified,
)
return dict(row) if row else None
```
Then in `_set_verified`, when `updated is None`, re-fetch to distinguish "row missing"
(404) from "already in target state" and short-circuit WITHOUT re-publishing/re-granting.
Separately decide the product rule for reject-after-verify: forbid it (409 "already
verified") OR reverse the participation grant in the same transaction. Do not leave the
current silent revert-without-reversal.

## Warnings

### WR-01: Verified event published after the transaction commits, with no outbox (dual-write)

**File:** `apps/api/services/tournament_service.py:622-645`; mirrored in `apps/api/services/completions_service.py:1117-1141`
**Issue:** `_set_verified` commits the `verified` flip + XP grant inside the
`async with ... raw_conn.transaction()` block, then publishes the
`TournamentVerificationChangedEvent` AFTER the block exits. If `publish_message` fails
(broker down) the DB is already committed: the run is verified and XP granted, but the bot
never receives the verification-changed event — no Discord confirmation, no surfaced
verdict. There is no retry/outbox here, even though the Phase-7 cycle lifecycle DOES use the
`tournaments.pending_transitions` outbox for exactly this dual-write problem. The publish is
fire-and-forget and lost on failure.
**Fix:** Route the verified event through the same `pending_transitions` outbox the cycle
lifecycle uses (insert inside the txn, let the poller publish), or at minimum wrap the
publish in try/except logging at `exception` level with the tournament_completion_id so a
dropped event is reconcilable.

### WR-02: OCR path's broad `except Exception` can double-surface a run (auto-verify AND mod-review)

**File:** `apps/api/services/completions_service.py:473-543`
**Issue:** `attempt_tournament_auto_verify_async` wraps the whole body — including
`await self.verify_tournament_completion(...)` (line 501), which itself runs a DB txn + XP
grant + publish — in `except Exception`, and on ANY exception publishes a mod-review
`TournamentCompletionCreatedEvent`. If the OCR matches and `verify_tournament_completion`
commits the flip+grant but then raises during its post-commit publish (WR-01), the broad
`except` ALSO queues the run for manual mod review. Net: the run is both auto-verified in
the DB AND posted to the verification queue — a contradictory double surface, and a mod who
then Accepts/Rejects re-triggers CR-01.
**Fix:** Narrow the `try` to wrap only the OCR HTTP call + match decision; perform
`verify_tournament_completion(...)` (and its `return`) OUTSIDE that `try` so a post-verify
publish failure cannot fall through to the mod-review fallback.

### WR-03: `tournaments.completions` lacks a reject/terminal state (single `verified` bool)

**File:** `apps/api/migrations/0020_tournaments.sql:86-99` (schema) used by `apps/api/services/tournament_service.py`
**Issue:** Unlike `core.completions` (which encodes a three-state Pending/Verified/Rejected
via `verified` + `verified_by` in `fetch_dashboard_completions`), the tournament table has
only `verified`. Reject and "not yet reviewed" are indistinguishable, which is the schema
root cause that makes CR-01 possible (a re-verify or reject-after-verify cannot be detected).
This is a contract gap, not pure style.
**Fix:** Add a `verified_by`/`status` column so reject is a distinct terminal state (parity
with core completions), making CR-01's terminal guard well-defined and giving the bot a real
"already decided" signal.

### WR-04: Bot verify/reject buttons disable the card BEFORE the API call succeeds

**File:** `apps/bot/extensions/tournaments.py:111-141` (Accept) and `:160-179` (Reject)
**Issue:** Both callbacks disable the buttons and `itx.message.edit(view=...)` FIRST, then
call `verify_tournament_completion` / `reject_tournament_completion`. If the API call raises
(`APIHTTPError`/`APIUnavailableError`) the card is permanently disabled while the verdict
never took effect — the moderator cannot retry from that card and the run is stuck
unverified.
**Fix:** Call the API (and confirm the job was at least accepted) before disabling the
components, or re-enable the buttons in an `except` so a failed verdict leaves a retryable
card.

### WR-05: Inconsistent verdict reporting; reject reports success without polling

**File:** `apps/bot/extensions/tournaments.py:124-141` (Accept polls) vs `:178-179` (Reject)
**Issue:** Accept polls the job and on `not job` tells the mod "unknown error ... do not try
again" — but the API mutation may have actually succeeded (only the job row wasn't observed),
and because verify is not idempotent (CR-01) a retry could double-fire. Reject does NOT poll
at all: it reports "Successfully rejected" immediately after the call returns regardless of
whether the published job ultimately succeeds, so a failed reject is reported as success.
**Fix:** Make Reject poll the job like Accept; align the user-facing copy with CR-01's
idempotency fix (a retry-safe verb makes "you may retry" copy correct).

### WR-06: Phantom verified-event published off a stale precheck row on TOCTOU delete

**File:** `apps/api/services/tournament_service.py:632-645`
**Issue:** `time_value = float(updated["time"]) if updated else float(existing["time"])`.
`updated` is None when `set_tournament_verified` matched no row — i.e. the completion was
deleted between the `fetch_tournament_completion` precheck (line 596) and the UPDATE. The
code then still publishes a `TournamentVerificationChangedEvent` built from the STALE
`existing` row, telling the bot a now-deleted completion was verified/rejected.
**Fix:** When `updated is None` after the UPDATE, raise `TournamentCompletionNotFoundError`
(or return without publishing) instead of publishing a phantom event from the stale precheck
row.

### WR-07: `|| true` masks `ensure_active_cycle` failure behind the seed "Done" banner

**File:** `scripts/seed-tournament-local.sh:193,200`
**Issue:** `ensure_active_cycle` can `return 1` (no eligible maps) with diagnostics, but
`EM_CYCLE="$(ensure_active_cycle "$EM_ID" || true)"` swallows the failure, so `set -euo
pipefail` is defeated for that step and the script prints the "Done" summary with
`active cycle=<none>`. A developer skimming output sees a success banner while no cycle was
activated and the follow-up curl example targets a map with no active cycle. Local-dev script,
so warning not blocker.
**Fix:** Drop `|| true` (let it abort), or print an explicit
`[x] could not activate a cycle for <category>` line in the summary when `EM_CYCLE`/`HV_CYCLE`
is empty rather than hiding it behind "Done".

## Info

### IN-01: Stale review-id reference in `verify_tournament_completion` docstring

**File:** `apps/api/services/tournament_service.py:513`
**Issue:** The docstring ends "...flushed only after the transaction commits (CR-02)" — a
leftover reference to a prior review finding id, not a code symbol.
**Fix:** Drop the `(CR-02)` parenthetical.

### IN-02: Stale `_ = cycle_id  # reserved for ... 11-05` no-op

**File:** `apps/api/services/completions_service.py:470`
**Issue:** `cycle_id` is now actually used (passed to `_publish_tournament_mod_review` at
line 507/539), so the `_ = cycle_id` "reserved" no-op and its comment are dead.
**Fix:** Remove the line and comment.

### IN-03: Dead tournament exception classes with no remaining raisers

**File:** `apps/api/services/exceptions/tournaments.py:39-101`
**Issue:** `CycleAlreadyActiveError`, `CycleNotActiveError`, `MapMismatchError`,
`DuplicateTournamentCompletionError`, and `NoCycleActiveError` have no raisers now that the
bypass submit was removed (D-05) — confirmed: none are imported by the reviewed service/route
files. Dead code.
**Fix:** Remove the exception classes with no remaining raisers, or comment that they are
intentionally retained for a future website/admin surface.

### IN-04: Seed activation UPDATE not re-guarded on `status='pending'`

**File:** `scripts/seed-tournament-local.sh:170`
**Issue:** `UPDATE tournaments.cycles SET status='active' ... WHERE id=$pending_id` does not
re-check the row is still pending; two concurrent seed runs could activate two cycles for one
category (no single-active DB guard is asserted here). Local-dev only.
**Fix:** Add `AND status='pending'` to the WHERE so it is a no-op if the row already moved on.

---

_Reviewed: 2026-05-31_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
