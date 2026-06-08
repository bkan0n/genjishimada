-- Migration 0023: Tournament Cycle Lifecycle Control
-- Adds two admin/test lifecycle-control levers on tournaments.categories and
-- teaches process_cycle_transitions() to honor them:
--   1. transitions_paused boolean - when TRUE, the category is skipped entirely
--      by the scheduled transition function (admin pause/resume).
--   2. debug_cycle_seconds int (nullable) - DEBUG/TEST ONLY override of the
--      cycle length in seconds; NULL preserves the normal weekly/biweekly cadence.
--
-- The function body is copied verbatim from 0021 with exactly three edits:
--   (a) due-detection FOR loop skips paused categories and uses the debug-aware
--       interval (COALESCE(debug seconds, weekly?7:14 days));
--   (b) the promote-pending branch ends_at uses the same debug-aware interval;
--   (c) the inline-create branch ends_at uses the same debug-aware interval.
-- Everything else (advisory lock, placement snapshot, outbox INSERTs, pre-roll)
-- is unchanged, so non-paused / non-debug behavior is identical to 0021.
--
-- This migration does NOT touch the pg_cron registration from 0021: the cron job
-- calls the function by name, so CREATE OR REPLACE is sufficient; pause is handled
-- inside the function and needs no re-scheduling.

BEGIN;

-- =============================================================================
-- Additive lifecycle-control columns on tournaments.categories
-- =============================================================================
ALTER TABLE tournaments.categories
    ADD COLUMN IF NOT EXISTS transitions_paused boolean NOT NULL DEFAULT FALSE;

ALTER TABLE tournaments.categories
    ADD COLUMN IF NOT EXISTS debug_cycle_seconds int
        CHECK (debug_cycle_seconds IS NULL OR debug_cycle_seconds > 0);

COMMENT ON COLUMN tournaments.categories.transitions_paused IS
    'When TRUE, process_cycle_transitions() skips this category (admin pause)';
COMMENT ON COLUMN tournaments.categories.debug_cycle_seconds IS
    'DEBUG/TEST ONLY: overrides cycle length in seconds; NULL = normal weekly/biweekly cadence';

-- =============================================================================
-- Cycle transition state machine (D-01..D-09) with pause + debug-length support
-- =============================================================================
-- Invoked by pg_cron. Finalizes every due active cycle inside one transaction:
-- finalizing -> snapshot placements -> completed -> promote pending -> pre-roll.
CREATE OR REPLACE FUNCTION tournaments.process_cycle_transitions()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_due         record;
    v_pending     record;
    v_standings   jsonb;
    v_winner      bigint;  -- core.users.id is a Discord snowflake (bigint); int overflows
    v_next_map    int;
    v_inline_map  int;
    v_new_cycle   int;
BEGIN
    -- Concurrency gate (D-02): non-blocking transaction-level advisory lock.
    -- Auto-releases on COMMIT/ROLLBACK so no cleanup boilerplate is needed.
    -- Lock ID 2025070100 is unique to tournament transitions; it MUST NOT
    -- collide with the store rotation lock (1234567890, 0013_coin_store.sql).
    IF NOT pg_try_advisory_xact_lock(2025070100) THEN
        RAISE NOTICE 'Cycle transition already in progress, skipping';
        RETURN;
    END IF;

    -- Due-cycle detection (D-03 / D-04): end time computed inline from the
    -- category cycle_frequency. weekly -> 7 days, biweekly -> 14 days.
    -- EDIT (0023): paused categories are skipped, and debug_cycle_seconds (when
    -- set) overrides the weekly/biweekly interval so transitions can be tested.
    FOR v_due IN
        SELECT cy.id, cy.category_id, cy.map_id, cat.cycle_frequency, cat.debug_cycle_seconds
        FROM tournaments.cycles cy
        JOIN tournaments.categories cat ON cat.id = cy.category_id
        WHERE cy.status = 'active'
          AND cat.transitions_paused = FALSE
          AND now() >= cy.started_at + COALESCE(
                make_interval(secs => cat.debug_cycle_seconds),
                make_interval(days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))
    LOOP
        -- (a) Stop new submissions before snapshotting (Pitfall 4: the existing
        -- submit_completion status guard rejects on any non-active status).
        UPDATE tournaments.cycles
        SET status = 'finalizing'
        WHERE id = v_due.id;

        -- (b) Snapshot final placements (D-08): identical ranking to
        -- fetch_leaderboard (tier-then-time), aggregated as JSON. The winner is
        -- the single rank-1 user (NULL when the cycle had no submissions).
        WITH best_per_user AS (
            SELECT DISTINCT ON (tc.user_id)
                tc.user_id, tc.time, tc.verified, tc.completion
            FROM tournaments.completions tc
            WHERE tc.cycle_id = v_due.id
            ORDER BY tc.user_id, tc.verified DESC, tc.time ASC
        ),
        ranked AS (
            SELECT
                RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)::int AS rank,
                bpu.user_id,
                COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
                bpu.time::float AS time,
                bpu.verified,
                bpu.completion
            FROM best_per_user bpu
            JOIN core.users u ON u.id = bpu.user_id
        )
        SELECT
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'rank', ranked.rank,
                        'user_id', ranked.user_id,
                        'name', ranked.name,
                        'time', ranked.time,
                        'verified', ranked.verified,
                        'completion', ranked.completion
                    ) ORDER BY ranked.rank
                ),
                '[]'::jsonb
            ),
            MIN(ranked.user_id) FILTER (WHERE ranked.rank = 1)
        INTO v_standings, v_winner
        FROM ranked;

        -- (c) Complete the cycle.
        UPDATE tournaments.cycles
        SET status = 'completed', ended_at = now()
        WHERE id = v_due.id;

        -- (d) Outbox: cycle_completed (D-09). Keys MUST match
        -- TournamentCycleCompletedEvent (libs/sdk/.../tournaments.py).
        INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
        VALUES (
            v_due.id,
            'cycle_completed',
            jsonb_build_object(
                'cycle_id', v_due.id,
                'category_id', v_due.category_id,
                'standings', v_standings,
                'winner_user_id', v_winner
            )
        );

        -- (e) Promote the pre-rolled pending cycle (D-05).
        SELECT cy.id, cy.map_id INTO v_pending
        FROM tournaments.cycles cy
        WHERE cy.category_id = v_due.category_id AND cy.status = 'pending'
        ORDER BY cy.created_at ASC
        LIMIT 1;

        IF v_pending.id IS NOT NULL THEN
            UPDATE tournaments.cycles
            SET status = 'active', started_at = now()
            WHERE id = v_pending.id;

            -- (f) Outbox: cycle_started (D-09). Keys MUST match
            -- TournamentCycleStartedEvent.
            -- EDIT (0023): ends_at uses the same debug-aware interval so the bot's
            -- announced end time matches the actual next transition time.
            INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
            SELECT
                v_pending.id,
                'cycle_started',
                jsonb_build_object(
                    'cycle_id', v_pending.id,
                    'category_id', v_due.category_id,
                    'map_id', v_pending.map_id,
                    'map_code', m.code,
                    'map_name', m.map_name,
                    'started_at', now(),
                    'ends_at', now() + COALESCE(
                        make_interval(secs => v_due.debug_cycle_seconds),
                        make_interval(days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))
                )
            FROM core.maps m
            WHERE m.id = v_pending.map_id;
        ELSE
            -- D-07 edge: no pending cycle pre-rolled. Select inline and create an
            -- active cycle rather than aborting the whole run.
            RAISE NOTICE 'No pending cycle for category %, selecting inline (D-07)', v_due.category_id;
            v_inline_map := tournaments.select_eligible_map(v_due.category_id);
            IF v_inline_map IS NOT NULL THEN
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES (v_due.category_id, v_inline_map, 'active', now())
                RETURNING id INTO v_new_cycle;

                -- EDIT (0023): ends_at uses the same debug-aware interval.
                INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
                SELECT
                    v_new_cycle,
                    'cycle_started',
                    jsonb_build_object(
                        'cycle_id', v_new_cycle,
                        'category_id', v_due.category_id,
                        'map_id', v_inline_map,
                        'map_code', m.code,
                        'map_name', m.map_name,
                        'started_at', now(),
                        'ends_at', now() + COALESCE(
                            make_interval(secs => v_due.debug_cycle_seconds),
                            make_interval(days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))
                    )
                FROM core.maps m
                WHERE m.id = v_inline_map;
            ELSE
                RAISE NOTICE 'No eligible map for category %, leaving without active cycle (D-07)', v_due.category_id;
            END IF;
        END IF;

        -- (g) Pre-roll the NEXT pending cycle (D-06). On no eligible map,
        -- RAISE NOTICE and skip rather than aborting (D-07).
        v_next_map := tournaments.select_eligible_map(v_due.category_id);
        IF v_next_map IS NOT NULL THEN
            INSERT INTO tournaments.cycles (category_id, map_id)
            VALUES (v_due.category_id, v_next_map);
        ELSE
            RAISE NOTICE 'No eligible map to pre-roll for category % (D-07)', v_due.category_id;
        END IF;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION tournaments.process_cycle_transitions() IS
    'pg_cron-driven cycle transition: finalizes due cycles, snapshots placements, promotes pending, pre-rolls next. Skips categories with transitions_paused = TRUE and honors debug_cycle_seconds as a cycle-length override.';

COMMIT;
