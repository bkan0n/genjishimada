---
status: resolved
trigger: "Fully verified (time submission WITH a video) should take precedence over partially verified (no video attached) submissions in tournaments. A user submitted a video but in the tournament leaderboard it's showing as partial."
created: 2026-06-14
updated: 2026-06-15
goal: find_root_cause_only
---

# Debug Session: tournament-verified-precedence-partial

## Symptoms

- **Expected:** In tournaments, a fully verified submission (a time with a video attached) should take precedence over a partially verified submission (no video) for the same user/map. The leaderboard should reflect the fully-verified entry.
- **Actual:** A user submitted a video (fully verified), but the tournament leaderboard shows their entry as partial.
- **Error messages:** None reported.
- **Timeline:** Unsure — first time noticing. Unknown whether precedence ever worked.
- **Reproduction:** Specific user/tournament/map IDs exist but only in the prod environment. User can run any prod SQL query provided to them and return results.
- **Symptom scope:** Confirmed via prod data — the DB record IS fully verified (has video, status=verified, verified=true) and DOES win rank 1. The "partial" label is display-only, driven by the `completion` flag.

## Current Focus

- hypothesis: CONFIRMED — The tournament leaderboard's "partial" indicator is driven by the `tournaments.completions.completion` boolean column, which is `NOT NULL DEFAULT FALSE` and is NEVER written by any code path or migration. Therefore every tournament leaderboard row reports `completion = FALSE` (interpreted as "partial / not a full completion") regardless of whether a video is attached or whether the row is verified.
- next_action: RESOLVED — root cause confirmed by prod data. Diagnose-only; no fix applied.
- reasoning_checkpoint: Prod values obtained and analyzed (see Evidence: PROD CONFIRMATION).

## Evidence

- timestamp: 2026-06-14
  source: apps/api/repository/tournaments_repository.py:1877-1925 (fetch_leaderboard)
  note: Leaderboard selects best-per-user via `DISTINCT ON (tc.user_id) ... ORDER BY tc.user_id, tc.verified DESC, tc.time ASC, tc.inserted_at ASC`. Precedence/dedup is keyed ONLY on `verified` then `time` then `inserted_at` — a video being present does NOT influence which row wins or the tier. The query returns `bpu.completion` and `bpu.verified` to clients. Comment: "verified completions outrank unverified, fastest time wins within tier." Video explicitly "does not affect ranking per D-02" (migration 0020:111). VERIFIED against source 2026-06-15.

- timestamp: 2026-06-14
  source: apps/api/migrations/0020_tournaments.sql:86-112 (table def)
  note: `tournaments.completions.completion boolean NOT NULL DEFAULT FALSE` (line 96). Comment (line 112): "Whether submission counts as a full completion." Plain column with a static default — NOT generated, NO trigger. VERIFIED against source 2026-06-15.

- timestamp: 2026-06-14
  source: apps/api/repository/tournaments_repository.py:1499-1503 (create_tournament_completion INSERT)
  note: The ONLY INSERT into tournaments.completions lists `(cycle_id, user_id, map_id, time, screenshot, video)` — it OMITS `completion`, so every inserted row falls back to `DEFAULT FALSE`. Grep across repository/services/migrations found ZERO writes (INSERT col / UPDATE SET / trigger / backfill) that ever set `tournaments.completions.completion`. => the column is permanently FALSE for all rows. VERIFIED against source 2026-06-15.

- timestamp: 2026-06-14
  source: libs/sdk/src/genjishimada_sdk/tournaments.py:416-433 (TournamentLeaderboardEntryResponse)
  note: Leaderboard entry exposes both `verified: bool` and `completion: bool` ("Whether the submission counts as a full completion"). If the frontend renders "partial" when `completion == FALSE`, EVERY entry shows partial because the column is never set TRUE.

- timestamp: 2026-06-14
  source: apps/api/migrations/0025_verification_aware_tournament_results.sql:54-92
  note: 0025 reworked `verified` into a STORED generated column derived from tri-state `status` (pending/verified/rejected). It did NOT touch `completion`. New rows start `status='pending'` => `verified=FALSE` until a mod (or OCR auto-verify) flips status to 'verified'.

- timestamp: 2026-06-14
  source: apps/api/services/completions_service.py:640-909 (submit_completion / _dispatch_non_pb_tournament)
  note: A PB run WITH video on the active cycle map takes the D-04 PB path: it creates a core completion AND a linked tournament row, then publishes to the bot mod-review queue (`api.tournament.completion.created`). On mod acceptance, `status` flips to 'verified' (so `verified=TRUE`) — but nothing flips `completion`. The real "did they submit a video" signal lives in `tournaments.completions.video IS NOT NULL`, which the leaderboard query does NOT read.

- timestamp: 2026-06-15
  source: PROD CONFIRMATION — user-supplied read-only query results (treated as data)
  note: |
    Query A (tournaments.completions for user 313459248942153729, cycle 1, map 195):
      id=30  time=123.87  has_video=TRUE   status=verified  verified=TRUE  completion=FALSE  inserted_at=2026-06-15 00:22:06
      id=17  time=125.77  has_video=FALSE  status=verified  verified=TRUE  completion=FALSE  inserted_at=2026-06-09 02:39:53
      id=15  time=134.67  has_video=FALSE  status=verified  verified=TRUE  completion=FALSE  inserted_at=2026-06-09 01:28:20
      id=14  time=145.46  has_video=FALSE  status=verified  verified=TRUE  completion=FALSE  inserted_at=2026-06-09 00:37:36
    Query B (fetch_leaderboard output for cycle 1):
      rank=1  user_id=313459248942153729  time=123.87  verified=TRUE  completion=FALSE
    Query C: not needed (cycle_id=1 already known).

    DECISIVE FINDINGS:
    1. The user's fastest run (id=30) HAS a video, is status=verified / verified=TRUE, and the leaderboard
       CORRECTLY selects this exact row at rank 1 (time 123.87 matches). => Precedence/ranking is WORKING.
    2. `completion = FALSE` on EVERY row, including the verified video row and the leaderboard winner.
    3. Leaderboard returns verified=TRUE for the entry, yet the UI shows "partial". Therefore the "partial"
       label is NOT driven by `verified` (which is TRUE) — it is driven by `completion = FALSE`.
    => Confirms the column-never-written root cause. The fully-verified video run wins ranking exactly as
       intended; only the partial/full LABEL is wrong because `completion` is decorative and never set TRUE.

## Eliminated

- timestamp: 2026-06-14
  candidate: "The leaderboard ORDER BY / DISTINCT ON picks the wrong row for the user (a no-video row beating their video row)."
  note: ELIMINATED by prod data. The leaderboard selected id=30 (the video row, verified, fastest at 123.87) at rank 1 — the correct row won. Ranking/precedence is functioning; the symptom is purely the display label.

- timestamp: 2026-06-15
  candidate: "The user's run is still status='pending' (verified=FALSE), so the 'partial' tier surfaces from the verified flag."
  note: ELIMINATED by prod data. id=30 is status=verified / verified=TRUE, and the leaderboard returns verified=TRUE for the entry. The 'partial' label persists despite verified=TRUE, so it cannot be driven by verified.

## Resolution

- root_cause: The tournament leaderboard's "partial" vs "full" label is driven by `tournaments.completions.completion`, a `NOT NULL DEFAULT FALSE` boolean that is never written by any INSERT, UPDATE, trigger, or migration. The sole INSERT (create_tournament_completion, tournaments_repository.py:1499-1503) omits the column, so it is permanently FALSE for every row. `fetch_leaderboard` (tournaments_repository.py:1877-1925) faithfully returns this always-FALSE flag to clients, so the UI renders every entry — including fully-verified video submissions — as "partial". Prod data confirms: the user's verified video run (id=30) correctly wins rank 1 with verified=TRUE, but completion=FALSE, so it displays as partial. Ranking/precedence is correct; only the completion label is wrong.
- fix: Migration `apps/api/migrations/0029_completion_derived_from_video.sql` (Option 1, DB generated column) redefines `tournaments.completions.completion` as a STORED generated column derived from video presence: `ALTER TABLE ... DROP COLUMN completion;` then `ADD COLUMN completion boolean NOT NULL GENERATED ALWAYS AS (video IS NOT NULL) STORED;`, wrapped in BEGIN;/COMMIT;. `completion` is a distinct axis from `verified` (mod-approval): a submission is a "full completion" when a video proof was attached. `video` is nullable and absent-video runs store NULL (never empty string), so `video IS NOT NULL` is correct. This mirrors 0025's `verified` swap; no index/view references `completion`, so no DROP INDEX is needed. The generated column self-heals all existing rows. NO Python/SDK changes required — `fetch_leaderboard` already SELECTs `tc.completion` and the SDK already exposes `completion: bool` (TournamentLeaderboardEntryResponse / TournamentCompletionResponse), so the value simply becomes correct. Committed on branch `fix/tournament-completion-derived-from-video` as `fix: derive tournament completion flag from video presence` (not pushed). `just lint-api` passes.
- verification: After applying migration 0029, re-run `fetch_leaderboard` for cycle 1 (or query `tournaments.completions`): the affected user's row id=30 (has_video=TRUE) should now report `completion=TRUE` while the no-video rows (id=14/15/17) report `completion=FALSE`. The leaderboard winner (rank=1, user 313459248942153729) should now return `completion=TRUE`, so the UI renders it as a full completion rather than partial. Existing rows self-heal because the column is generated from `video IS NOT NULL` (no backfill needed).
- files_changed: apps/api/migrations/0029_completion_derived_from_video.sql (new)

### Follow-up (bug 2 — RANKING PRECEDENCE)

- root_cause: After 0029 fixed the label, fully-verified (video) runs still sorted BELOW faster partial (no-video) runs because the leaderboard ranked strictly by `verified DESC, time ASC` — video presence was deliberately excluded ("does not affect ranking per D-02", 0020:111). Prod cycle showed two verified video runs (Dziubson 99.77, LulledLion 123.87) below faster no-video runs (e.g. Hello 93.71). All rows verified=TRUE, so it was pure time order.
- decision (user): video must take precedence — any fully-verified (video) run outranks ALL partial (no-video) runs within the verified tier, even if slower; applied everywhere (display + champion + placement XP).
- fix: ranking changed to `verified DESC, completion DESC, time ASC` in `fetch_leaderboard`, the cycle-list winner LATERAL, and `fetch_user_completion` (tournaments_repository.py). `verified` kept as TOP axis to preserve 0025's pending-below-verified drain invariant. The outbox poller builds the champion event from `fetch_leaderboard` verbatim (tournament_outbox_service.py:263-285), so display, champion (standings[0]), and placement XP all move together — no pg-function migration needed (the live cron 0025 is timing-only). Migration `0030_rank_tournament_by_video_within_tier.sql` realigns the ranking index to `(cycle_id, verified DESC, completion DESC, time ASC)`. Test fixtures updated for the now-generated `completion` column; added `test_leaderboard_video_beats_no_video_within_tier` and `test_leaderboard_verified_tier_outranks_pending_video`.
- verification: `just lint-api` clean; tournament + completions suites pass (252+ tests, 0 failures). Prod: after applying 0029 AND 0030, the two video runs should sort above the faster no-video runs and show completion=TRUE.
- files_changed (bug 2): apps/api/migrations/0030_rank_tournament_by_video_within_tier.sql (new), apps/api/repository/tournaments_repository.py, apps/api/tests/repository/tournaments/conftest.py, apps/api/tests/repository/tournaments/test_tournaments_repository.py, apps/api/tests/repository/tournaments/test_outbox_poller.py, apps/api/tests/integration/test_tournaments_integration.py, apps/api/tests/integration/test_tournaments_schema.py
- NOTE: migrations are applied externally (no runner in justfile/app). Both 0029 and 0030 must be run against dev/prod to take effect.
