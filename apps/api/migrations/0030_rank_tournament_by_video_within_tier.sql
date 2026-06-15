-- Migration 0030: Rank tournament leaderboard by video presence within the verified tier
--
-- Tournament ranking previously ordered strictly by `verified DESC, time ASC`
-- (0020:107, 0025:98) -- video presence did not affect ranking ("does not affect
-- ranking per D-02", 0020:111). Product decision: a fully-verified submission (a
-- video proof was attached -> completion=TRUE, see 0029) should take precedence
-- over a partial (no-video) submission. So a slower video run now outranks a
-- faster no-video run.
--
-- New precedence (applied in Python -- fetch_leaderboard and its sibling ranking
-- queries in tournaments_repository.py): `verified DESC, completion DESC, time ASC`.
-- `verified` (mod-approval, generated from status in 0025) stays the TOP axis so
-- pending runs keep sorting below verified runs -- the invariant the edition
-- finalization drain logic depends on (0025). `completion` (video presence,
-- generated in 0029) is inserted beneath it; `time ASC` breaks ties within a tier.
-- The outbox poller builds the champion event from fetch_leaderboard verbatim
-- (tournament_outbox_service.py), so this single ordering drives the display
-- leaderboard, the awarded champion (standings[0]), and placement XP together.
--
-- This migration realigns the ranking index with the new ORDER BY. Correctness
-- does not depend on it (per-cycle leaderboards are small), but 0020 and 0025 both
-- kept this index byte-aligned with the ranking, so we do too. `completion` is a
-- STORED generated column (0029); generated columns are valid in index keys (0025
-- indexes the generated `verified` column the same way).
--
-- Wrap DDL in BEGIN;/COMMIT; like 0024/0025/0029.

BEGIN;

-- Drop the old ranking index (cycle_id, verified DESC, time ASC) and recreate it
-- with `completion DESC` inserted to match `verified DESC, completion DESC, time ASC`.
DROP INDEX IF EXISTS tournaments.idx_tournament_completions_ranking;

CREATE INDEX IF NOT EXISTS idx_tournament_completions_ranking
    ON tournaments.completions (cycle_id, verified DESC, completion DESC, time ASC);

COMMIT;
