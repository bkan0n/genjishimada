-- Migration 0025: Verification-aware tournament results (Phase 12.1, D-06/D-08)
--
-- Phase 12's process_edition_transitions() (0024) snapshots each child cycle's
-- leaderboard at the instant pg_cron fires and freezes it into the
-- edition_rollover outbox payload. A run still pending verification at the grid
-- boundary sorts below verified runs (verified DESC), so it is excluded from
-- standings, placement XP, AND the champion-role transfer -- and once the
-- results are announced they are final. A run that verifies minutes later never
-- counts. This is the bug Phase 12.1 fixes.
--
-- This migration ships the DB bedrock for the fix:
--
-- (1) TRI-STATE completion status (D-08). Today reject leaves
--     tournaments.completions.verified = FALSE, which is INDISTINGUISHABLE from
--     an un-reviewed pending run -- so "the verification queue has drained" is
--     undetectable. We add a `status text` column constrained to exactly
--     pending / verified / rejected, backfill it from the old `verified`
--     boolean, then re-create `verified` as a STORED generated column
--     (status = 'verified'). This keeps every existing `verified DESC` ranking
--     read and SDK `verified` field working unchanged (writes move to `status`),
--     while making `COUNT(*) WHERE status = 'pending'` an exact drain signal.
--     A single enum column also makes the illegal "verified AND rejected" state
--     unrepresentable (T-12.1-01).
--
-- (2) AWAITING_RESULTS edition status + start_announced marker (D-06). The
--     editions status CHECK gains 'awaiting_results' -- the state an edition
--     sits in after the grid boundary while its results are deferred pending
--     verification drain. start_announced records whether the poller has already
--     emitted the start-only announcement, disambiguating "first tick" from
--     "results still owed" on later poller ticks.
--
-- (3) TIMING-ONLY cron rewrite (D-06). process_edition_transitions() becomes a
--     pure status flip: it detects the due edition, flips it to
--     'awaiting_results' (NOT 'completed'), flips child cycles to 'finalizing'
--     (stops new submissions), and creates edition N+1 grid-anchored
--     (started_at = prev.ends_at, NEVER now()). It NO LONGER snapshots the
--     leaderboard, accumulates a results payload, flips cycles to 'completed',
--     or writes the edition_rollover outbox row. Results computation + reward
--     grants move to the outbox poller (D-07, a downstream plan). This removes
--     any path for a scheduled job to finalize outcomes prematurely (T-12.1-03).
--
-- Ordering is load-bearing for the generated-column swap (Pitfall 1): you cannot
-- DROP the old `verified` while the ranking index references it, and a plain
-- `verified` and a generated `verified` cannot coexist. The sequence MUST be:
-- add status -> backfill -> drop ranking index -> drop verified -> re-add
-- verified GENERATED -> recreate ranking index.
--
-- Wrap DDL/DML in BEGIN;/COMMIT; like 0024. The pg_cron re-registration stays an
-- UNWRAPPED DO $body$ guarded on pg_extension so test DBs without pg_cron no-op.

BEGIN;

-- =============================================================================
-- (1) Tri-state completion status with a generated `verified` column (D-08)
-- =============================================================================
-- ORDER IS LOAD-BEARING (Pitfall 1): add status -> backfill -> drop the ranking
-- index that references verified -> drop verified -> re-add verified as a STORED
-- generated column -> recreate the ranking index.

-- (1a) Add the tri-state status column (default pending; existing rows backfilled below).
ALTER TABLE tournaments.completions
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'verified', 'rejected'));

-- (1b) Backfill status from the existing verified boolean. An un-verified row was
--      either never reviewed or rejected; we cannot distinguish historically, so a
--      FALSE row becomes 'pending' (the conservative choice -- it was never an
--      explicit rejection). TRUE rows are 'verified'.
UPDATE tournaments.completions
    SET status = CASE WHEN verified THEN 'verified' ELSE 'pending' END;

-- (1c) Drop the ranking index FIRST -- it references `verified`, so DROP COLUMN
--      verified would otherwise fail with "cannot drop column ... other objects
--      depend on it".
DROP INDEX IF EXISTS tournaments.idx_tournament_completions_ranking;

-- (1d) Drop the plain boolean column (its value is now mirrored by `status`).
ALTER TABLE tournaments.completions DROP COLUMN verified;

-- (1e) Re-add `verified` as a STORED generated column so every existing
--      `verified DESC` ranking read and SDK `verified` field keeps working; only
--      WRITES now target `status`. (create_tournament_completion does RETURNING *,
--      which is allowed for generated columns on read.)
ALTER TABLE tournaments.completions
    ADD COLUMN verified boolean GENERATED ALWAYS AS (status = 'verified') STORED;

-- (1f) Recreate the ranking index (byte-identical to 0020:106-107). Generated
--      column reads are allowed in index expressions.
CREATE INDEX IF NOT EXISTS idx_tournament_completions_ranking
    ON tournaments.completions (cycle_id, verified DESC, time ASC);

COMMENT ON COLUMN tournaments.completions.status IS
    'Tri-state verification (D-08): pending | verified | rejected. The write-side source of truth; `verified` is a generated mirror. status=pending is the exact drain signal (no row can be both verified and rejected).';
COMMENT ON COLUMN tournaments.completions.verified IS
    'Generated mirror of (status = ''verified'') (D-08). Read-only; writes go to `status`. Preserves the verified DESC ranking tier and every existing `verified` read/field.';

-- =============================================================================
-- (2) Edition awaiting_results status + start_announced marker (D-06)
-- =============================================================================
-- Extend the editions status CHECK to add 'awaiting_results' (drop-by-name then
-- re-add, the 0024:115-120 idiom). The CHECK was defined inline at table-create
-- (0024:43-44) so the auto-generated name is editions_status_check; DROP IF
-- EXISTS is safe even if the name differs.
ALTER TABLE tournaments.editions
    DROP CONSTRAINT IF EXISTS editions_status_check;
ALTER TABLE tournaments.editions
    ADD CONSTRAINT editions_status_check
    CHECK (status IN ('active', 'awaiting_results', 'completed'));

-- start_announced disambiguates the poller's "first tick" from "results still
-- owed" (D-06/D-07): set TRUE when the start-only announcement is emitted.
ALTER TABLE tournaments.editions
    ADD COLUMN IF NOT EXISTS start_announced boolean NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN tournaments.editions.status IS
    'Edition lifecycle (D-06): active -> awaiting_results (grid boundary reached, results deferred pending verification drain) -> completed (poller published results). The cron only flips to awaiting_results; the poller flips to completed.';
COMMENT ON COLUMN tournaments.editions.start_announced IS
    'TRUE once the poller has emitted the start-only announcement for this edition (D-06/D-07). Distinguishes the poller first tick from later "results still owed" ticks.';

-- =============================================================================
-- (3) Timing-only process_edition_transitions() rewrite (D-06)
-- =============================================================================
-- Same signature () RETURNS void so the cron registration (below) is unchanged.
-- KEEP: advisory lock, config read, period CASE, due-edition detect, the child
-- UPDATE ... status='finalizing', and the entire N+1 creation block.
-- DELETE: the snapshot leaderboard CTE, the child flip to 'completed', and the
-- edition_rollover outbox INSERT.
-- CHANGE: the edition flip from status='completed' to status='awaiting_results'.
-- The function must end with the edition in 'awaiting_results', child cycles in
-- 'finalizing', edition N+1 created, and NO outbox row written. Results
-- computation + reward grants are owned by the outbox poller (D-07).
CREATE OR REPLACE FUNCTION tournaments.process_edition_transitions()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_cfg         record;
    v_edition     record;
    v_period      interval;
    v_child       record;
    v_new_edition int;
    v_next_map    int;
    v_cat         record;
BEGIN
    -- Concurrency gate (T-12-02): non-blocking transaction-level advisory lock.
    -- Auto-releases on COMMIT/ROLLBACK. Lock ID 2025070100 is unique to tournament
    -- transitions; it MUST NOT collide with the store rotation lock (1234567890).
    IF NOT pg_try_advisory_xact_lock(2025070100) THEN
        RAISE NOTICE 'Edition transition already in progress, skipping';
        RETURN;
    END IF;

    SELECT * INTO v_cfg FROM tournaments.config WHERE id = 1;

    -- Period from the global cadence (debug override wins). Calendar interval for
    -- weekly/biweekly so DST keeps the wall-clock slot (Pitfall 2).
    v_period := CASE
        WHEN v_cfg.debug_cycle_seconds IS NOT NULL
            THEN make_interval(secs => v_cfg.debug_cycle_seconds)
        WHEN v_cfg.cadence = 'biweekly' THEN make_interval(weeks => 2)
        ELSE make_interval(weeks => 1)
    END;

    -- Detection (D-01/D-08): the single active edition whose grid boundary is reached.
    SELECT * INTO v_edition
    FROM tournaments.editions
    WHERE status = 'active' AND now() >= ends_at
    ORDER BY ends_at ASC
    LIMIT 1;

    IF v_edition.id IS NULL THEN
        RETURN;  -- no edition due
    END IF;

    -- (a) Stop new submissions on every child cycle of the due edition: flip them
    --     to 'finalizing' (the submit guard rejects any non-active status). The
    --     cron does NOT compute standings or flip cycles to 'completed' (D-06);
    --     the poller does that when results publish.
    FOR v_child IN
        SELECT cy.id
        FROM tournaments.cycles cy
        WHERE cy.edition_id = v_edition.id
          AND cy.status IN ('active', 'finalizing')
        ORDER BY cy.id
    LOOP
        UPDATE tournaments.cycles SET status = 'finalizing' WHERE id = v_child.id;
    END LOOP;

    -- (b) Flip the edition to awaiting_results (timing-only; D-06). The poller
    --     later flips it (and its cycles) to 'completed' when verification drains.
    --     NO now() into started_at/ends_at.
    UPDATE tournaments.editions SET status = 'awaiting_results' WHERE id = v_edition.id;

    -- (c) Create the next edition UNLESS paused (D-12 hiatus). The next edition
    --     inherits the EXACT grid boundary -- the drift fix (D-08):
    --     started_at = old.ends_at, ends_at = old.ends_at + period. No now().
    IF NOT v_cfg.transitions_paused THEN
        INSERT INTO tournaments.editions (started_at, ends_at, status)
        VALUES (v_edition.ends_at, v_edition.ends_at + v_period, 'active')
        RETURNING id INTO v_new_edition;

        -- One child cycle per active category, pre-rolled via select_eligible_map.
        FOR v_cat IN
            SELECT cat.id AS category_id
            FROM tournaments.categories cat
            WHERE cat.is_active = TRUE
            ORDER BY cat.id
        LOOP
            v_next_map := tournaments.select_eligible_map(v_cat.category_id);
            IF v_next_map IS NULL THEN
                RAISE NOTICE 'No eligible map for category % in new edition % (D-07)',
                    v_cat.category_id, v_new_edition;
                CONTINUE;
            END IF;

            INSERT INTO tournaments.cycles (edition_id, category_id, map_id, status, started_at)
            VALUES (v_new_edition, v_cat.category_id, v_next_map, 'active', v_edition.ends_at);
        END LOOP;
    END IF;

    -- (d) NO outbox row, NO leaderboard snapshot, NO reward grants (D-06). The
    --     outbox poller owns results computation for awaiting_results editions (D-07).
END;
$$;

COMMENT ON FUNCTION tournaments.process_edition_transitions() IS
    'pg_cron-driven TIMING-ONLY edition rollover (D-06): flips the due edition active -> awaiting_results, flips child cycles -> finalizing, and creates edition N+1 with started_at = prev.ends_at (NEVER now()). It does NOT snapshot the leaderboard, write an outbox row, or grant rewards -- the outbox poller owns results computation when verification drains (D-07). transitions_paused suppresses the next edition (hiatus, D-12).';

COMMIT;

-- =============================================================================
-- (4) Idempotent pg_cron re-registration (guarded on pg_extension; test DBs no-op)
-- =============================================================================
-- Keep the job NAME 'tournament-cycle-transitions' and the same function
-- reference (the signature is unchanged). UNWRAPPED DO block per the 0021/0024
-- pattern so test DBs without pg_cron no-op.
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('tournament-cycle-transitions') WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions'
        );

        PERFORM cron.schedule(
            'tournament-cycle-transitions',
            '* * * * *',
            'SELECT tournaments.process_edition_transitions()'
        );

        RAISE NOTICE 'Scheduled pg_cron job: tournament-cycle-transitions (process_edition_transitions)';
    ELSE
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
    END IF;
END $body$;
