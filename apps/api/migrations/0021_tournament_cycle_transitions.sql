-- Migration 0021: Tournament Cycle Transitions
-- Adds the automatic cycle-transition state machine:
--   1. tournaments.select_eligible_map() - SQL mirror of the Phase 5 Python
--      map-selection logic, used to pre-roll the next pending cycle.
--   2. tournaments.process_cycle_transitions() - pg_cron-driven PL/pgSQL
--      function that finalizes due cycles, snapshots placements, promotes the
--      pre-rolled pending cycle, and writes outbox rows.
--   3. Idempotent pg_cron registration (guarded so test/local DBs without
--      pg_cron no-op).

-- Enable pg_cron extension for automatic cycle scheduling.
-- NOTE: Requires shared_preload_libraries = 'pg_cron' in postgresql.conf.
-- Silently ignore if extension is not available (e.g., in test environments).
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
END $$;

-- =============================================================================
-- Map-selection helper (D-06 / D-07)
-- =============================================================================
-- Mirrors TournamentRepository.fetch_eligible_maps + fetch_least_recently_used_map
-- (apps/api/repository/tournaments_repository.py). Kept in SQL so the transition
-- can pre-roll the next cycle atomically inside its own transaction.
--
-- DUPLICATION NOTE: the eligibility rules here intentionally duplicate the
-- Phase 5 Python selection SQL. Any change to selection rules must be applied in
-- both places. See 07-RESEARCH.md "THE KEY RISK" for the rationale (atomicity is
-- worth more than DRY for the scheduled transition).
CREATE OR REPLACE FUNCTION tournaments.select_eligible_map(p_category_id int)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
    v_difficulties    text[];
    v_blacklist_weeks int;
    v_map_id          int;
BEGIN
    SELECT cat.difficulties INTO v_difficulties
    FROM tournaments.categories cat
    WHERE cat.id = p_category_id;

    SELECT cfg.blacklist_weeks INTO v_blacklist_weeks
    FROM tournaments.config cfg
    WHERE cfg.id = 1;

    -- Primary selection: random eligible map matching the category difficulties,
    -- excluding maps used within the blacklist window and maps already pending.
    SELECT m.id INTO v_map_id
    FROM core.maps m
    WHERE m.official = TRUE
      AND m.archived = FALSE
      AND m.code IS NOT NULL
      AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY(v_difficulties)
      AND m.id NOT IN (
          SELECT cy.map_id
          FROM tournaments.cycles cy
          WHERE cy.started_at > now() - make_interval(weeks => v_blacklist_weeks)
      )
      AND m.id NOT IN (
          SELECT cy.map_id
          FROM tournaments.cycles cy
          WHERE cy.status = 'pending'
      )
    ORDER BY random()
    LIMIT 1;

    -- LRU fallback (pool exhausted): least recently used eligible map.
    IF v_map_id IS NULL THEN
        SELECT m.id INTO v_map_id
        FROM core.maps m
        LEFT JOIN tournaments.cycles cy ON cy.map_id = m.id
        WHERE m.official = TRUE
          AND m.archived = FALSE
          AND m.code IS NOT NULL
          AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY(v_difficulties)
        ORDER BY cy.started_at ASC NULLS FIRST
        LIMIT 1;
    END IF;

    RETURN v_map_id;  -- NULL if no eligible map exists at all
END;
$$;

COMMENT ON FUNCTION tournaments.select_eligible_map(int) IS
    'Selects a random eligible tournament map for a category (LRU fallback). Mirrors fetch_eligible_maps.';

-- =============================================================================
-- Cycle transition state machine (D-01..D-09)
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
    FOR v_due IN
        SELECT cy.id, cy.category_id, cy.map_id, cat.cycle_frequency
        FROM tournaments.cycles cy
        JOIN tournaments.categories cat ON cat.id = cy.category_id
        WHERE cy.status = 'active'
          AND now() >= cy.started_at + make_interval(
                days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)
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
                    'ends_at', now() + make_interval(
                        days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)
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
                        'ends_at', now() + make_interval(
                            days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)
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
    'pg_cron-driven cycle transition: finalizes due cycles, snapshots placements, promotes pending, pre-rolls next.';

-- =============================================================================
-- Idempotent pg_cron registration (D-01 / D-12)
-- =============================================================================
-- Guarded on pg_extension so the migration is safe where pg_cron is absent
-- (local/test). Unschedules before scheduling so re-runs are idempotent.
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('tournament-cycle-transitions') WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions'
        );

        PERFORM cron.schedule(
            'tournament-cycle-transitions',
            '* * * * *',                                   -- D-12: every minute
            'SELECT tournaments.process_cycle_transitions()'
        );

        RAISE NOTICE 'Scheduled pg_cron job: tournament-cycle-transitions';
    ELSE
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
    END IF;
END $body$;
