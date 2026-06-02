# Phase 11: Tournament Verification Flow - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Today, tournament times skip verification entirely: `POST /api/v3/tournaments/cycles/{cycle_id}/submit`
writes `tournaments.completions` (`verified=FALSE`) and cross-writes to `core.completions` in one
transaction, with no OCR/mod review. This phase removes that bypass so tournament times are earned
through the **same verification pipeline as normal completions**, and a verified run reaches the
tournament leaderboard via **auto-detection on normal submission** — no separate tournament submit.

**In scope:**
1. Auto-detect: a normal completion on an active cycle's map is considered for that tournament (D1).
2. PB runs ride the existing completion verdict; non-PB runs get their own verification path (D4).
3. Remove the bypass endpoint + bypass cross-write and fix dependents (D5).
4. Grant participation XP + verified standing on verification, not submission (D6).
5. Keep-fastest-tournament-window-time ranking, independent of core's "latest = fastest" (D3).
6. SDK structs / events, API service+repo+route changes, bot handler(s), tests.

**Out of scope (not this phase):**
- Changing how cycles are selected/transitioned (Phases 5/7 own that).
- Changing the leaderboard *ranking* formula (tier-then-time already built in Phase 6).
- Bot writing to Postgres (architecturally forbidden — bot calls the API).
- Recomputing historical tournament standings on map change (future phase).

</domain>

## Carrying Forward — Verified Current-State Facts (locked; from code reads)

- **Bypass submit path:** route `apps/api/routes/v3/tournaments.py:459` `submit_completion` →
  `apps/api/services/tournament_service.py:497` `TournamentService.submit_completion` (single txn):
  rejects slower-than-existing-tournament-time (`SlowerTimeError`), inserts
  `tournaments.completions` via `create_tournament_completion`
  (`apps/api/repository/tournaments_repository.py:885`), cross-writes to `core.completions` via
  `cross_write_to_core` (`tournaments_repository.py:930`, PB-gated `should_insert`), grants
  participation XP on first completion. **No verification anywhere.**
- **Normal completion submit:** `apps/api/services/completions_service.py:413` `submit_completion`.
  - **Early reject:** `SlowerThanPendingError` at `completions_service.py:437` if a *pending*
    submission on that map is faster-or-equal → HTTP 400, never inserted, never verified.
  - **DB trigger `core.enforce_speed_rules_nonlegacy_only()`** (`migrations/0017_fix_speed_trigger_check_verified.sql`,
    trigger declared in `0001_init.sql`) rejects any non-legacy insert into `core.completions`
    that is not strictly faster than the user's best non-legacy time (verified OR pending).
  - **⇒ A tournament run slower than the player's all-time PB has NO `core.completions` row**, so it
    never fires a verification event. This is why non-PB runs need their own verify path (D4).
- **Verification hook (PB path):** `completions_service.py:575` `verify_completion` →
  `update_verification` (`apps/api/repository/completions_repository.py:1678`, SQL `:1697`) →
  publishes `VerificationChangedEvent` on **`api.completion.verification`** (`completions_service.py:639`).
  Bot consumes it at `apps/bot/extensions/completions.py:573` `_process_verification_status_change`.
- **OCR auto-verify (no-video):** in-process Litestar event `completion.ocr.requested`
  (`apps/api/events/completions.py:17`), logic `completions_service.py:281` `attempt_auto_verify_async`
  — a screenshot check that does not inherently require a ranked core row.
- **Mod embed (video / suspicious):** `CompletionCreatedEvent` on `api.completion.submission` →
  bot `_process_create_submission_message` (`apps/bot/extensions/completions.py:562`) posts an
  Accept/Reject embed; Accept calls back the verify endpoint.
- **Tournament leaderboard** ranks `verified DESC, time ASC` over `tournaments.completions`
  (schema `migrations/0020_tournaments.sql:86`); unverified runs already sort below verified.
- **Architecture invariants:** no ORM; single-writer (only API writes Postgres); Litestar + asyncpg +
  msgspec + RabbitMQ patterns only; **`core.completions` "latest = fastest" invariant must be preserved.**

<decisions>
## Implementation Decisions (locked this discussion — do not revisit)

### Auto-detect on normal submit
- **D-01:** A normal completion whose map is the **active cycle's map** is automatically considered
  for that tournament. No separate player-facing tournament-submit step. Detection keys off the
  active cycle's `map_id` (a cycle already pins a specific map).

### Eligibility
- **D-02:** **Anyone who completes the active tournament map participates** — no opt-in. The first
  *counted* (verified) run auto-enrolls the player (grants participation XP). Apply any eligibility
  gates the tournament system already enforces (e.g. blacklist/active-cycle checks) — planner to
  confirm which.

### Keep fastest tournament-window time (independent ranking)
- **D-03:** The tournament board keeps each player's **fastest tournament-window time**, recorded on
  `tournaments.completions`, **independent of** core's "latest = fastest". A valid run slower than
  the player's all-time PB still counts (kept only if it beats their current tournament best).
  **No slower-than-PB row is ever inserted into `core.completions`** (would break the invariant + be
  rejected by the speed trigger). Cross-write to `core.completions` happens **only when the run is a
  PB**.

### Verification split (PB rides core verdict; non-PB has own path)
- **D-04:** Verification splits by PB-vs-non-PB. **PB run** (faster than all-time best): a
  `core.completions` row exists and flows through the existing OCR/mod verification; the linked
  tournament record is marked verified — **no second embed**. **Non-PB run** (no core row): the
  tournament record gets its **own** verification — OCR auto-verify for no-video runs, a mod
  Accept/Reject embed for video runs — operating on `tournaments.completions`, reusing the existing
  OCR service + embed pattern. A single screenshot is **never reviewed twice**.

### Remove the bypass
- **D-05:** Delete `POST /api/v3/tournaments/cycles/{cycle_id}/submit` and its verification-skipping
  cross-write. Fix all dependents (tests, any caller). No code path may write a tournament completion
  without verification. (Preserve `cross_write_to_core` + `create_tournament_completion` — reused by
  the new flow.)

### Rewards / standing on verification
- **D-06:** Participation XP and a *verified* leaderboard standing are granted **on verification**,
  not on submission. Unverified runs appear as pending (ranked below verified, as today).

### Claude's Discretion (defer to research/planning)
- Exact new RabbitMQ event/queue names + SDK structs for the non-PB tournament verification path
  (mirroring `api.completion.submission` / `api.completion.verification`), the tournament verify
  endpoint, and the bot handler wiring.
- Whether the non-PB OCR path reuses the in-process `completion.ocr.requested` event or a tournament
  variant.
- How the active-cycle-by-`map_id` lookup is implemented (new repo method vs. existing).
- Where/how the cross-write becomes `verified=TRUE` once a PB run is actually verified (today it
  writes `verified=FALSE`).
- Mod verification channel reuse vs. a dedicated tournament verification channel (default: reuse).

## Confirmed during planning research (2026-05-31 — locked)

- **D-07:** Submit-path relax (confirmed by user). Modify the shared normal-submit path
  (`completions_service.py:413` `submit_completion`) so that on an **active tournament map**, a
  valid run that is slower than the player's all-time PB is **accepted and routed to tournament
  verification** (returns a "recorded, pending verification" result) instead of raising
  `SlowerThanPendingError` / hitting the speed trigger. **Non-tournament maps keep the existing
  HTTP 400 "must be faster" rejection unchanged.** Because this touches the shared completion hot
  path, heavy regression tests must guard normal (non-tournament) submission behavior.
- **D-04 mechanism (refinement, not a new decision):** supersedes the earlier CONTEXT/RESEARCH
  phrasing — mark the linked tournament record verified **inside `verify_completion`
  (`completions_service.py:575`)**, NOT by consuming `VerificationChangedEvent` (that event carries
  no `map_id`, so it cannot resolve the cycle). Link the PB completion to its tournament row via the
  existing `core.completions.tournament_completion_id` FK (set in the submit transaction). [folded]

</decisions>

<canonical_refs>
## Canonical References
- `docs/specs/tournament-leaderboard.md`, `docs/specs/tournament-frontend-spec.md` (untracked specs).
- Phase 6 (`06-*`) submission/cross-write/leaderboard; Phase 9 (`09-*`) bot tournament consumers.
- `CLAUDE.md` — Tournament System constraints (cross-write preserves "latest = fastest"; bot never
  writes DB; new `tournaments` schema; existing stack only).
</canonical_refs>
