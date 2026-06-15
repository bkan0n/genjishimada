-- Migration 0029: Derive tournament `completion` flag from video presence
--
-- BUG: tournaments.completions.completion was introduced in 0020 as a plain
-- `boolean NOT NULL DEFAULT FALSE` column (0020:96) and is NEVER written by any
-- code path -- the sole INSERT (create_tournament_completion,
-- tournaments_repository.py:1499-1503) omits the column, and no UPDATE, trigger,
-- or migration ever sets it. So the column is permanently FALSE for every row.
-- fetch_leaderboard (tournaments_repository.py:1877-1925) faithfully returns this
-- always-FALSE flag, and the SDK exposes it as
-- TournamentLeaderboardEntryResponse.completion, so the UI renders EVERY entry --
-- including fully-verified runs that have a video attached -- as "partial".
-- Prod confirmed this: the affected user's fastest run (id=30) has a video, is
-- status=verified / verified=TRUE, correctly wins rank 1, yet shows completion=FALSE
-- and therefore displays as partial. Ranking/precedence was always correct; only
-- the partial/full LABEL was wrong because `completion` was decorative.
--
-- FIX: redefine `completion` as a STORED generated column derived from video
-- presence -- `completion = (video IS NOT NULL)`. `completion` is a distinct axis
-- from `verified` (mod-approval, generated from status in 0025): a submission is a
-- "full completion" when a video proof was attached. The `video text` column is
-- nullable (0020:94) and absent-video runs store NULL (never empty string), so
-- `video IS NOT NULL` is the correct expression. The generated column self-heals
-- all existing rows, including the affected user's id=30, with no data backfill.
--
-- This mirrors 0025, which dropped+recreated `verified` as a STORED generated
-- column. Unlike `verified`, NO index or view references `completion` (the ranking
-- indexes key on cycle_id/verified/time -- 0020:106-107), so it can be dropped
-- directly with no DROP INDEX first. A plain `completion` and a generated
-- `completion` cannot coexist, so the sequence MUST be: drop the plain column ->
-- re-add it GENERATED.
--
-- No Python or SDK changes are required: fetch_leaderboard already SELECTs
-- tc.completion and the SDK already exposes it; only the value now becomes correct.
--
-- Wrap DDL in BEGIN;/COMMIT; like 0024/0025.

BEGIN;

-- (1) Drop the plain boolean column. Its value was always FALSE (never written),
--     so there is nothing to preserve. No index/view depends on it.
ALTER TABLE tournaments.completions DROP COLUMN completion;

-- (2) Re-add `completion` as a STORED generated column derived from video
--     presence. RETURNING * on create_tournament_completion stays valid (generated
--     columns are read-only on read). The expression self-heals every existing row.
ALTER TABLE tournaments.completions
    ADD COLUMN completion boolean NOT NULL GENERATED ALWAYS AS (video IS NOT NULL) STORED;

COMMENT ON COLUMN tournaments.completions.completion IS 'Whether submission is a full completion -- TRUE when a video proof was attached (generated from video IS NOT NULL)';

COMMIT;
