-- Migration 0024: Tournament Editions Overhaul (single-edition grid-anchored model)
--
-- Backend refactor of the already-shipped tournament system (phases 01-11).
-- The old model gave every category an independently-timed tournaments.cycles
-- row, and process_cycle_transitions() (0023) re-stamped started_at = now() on
-- every promote (lines 152, 183). Because the cron tick fires up to ~60s late and
-- the new start was anchored to *execution time*, categories drifted apart and
-- never re-converged. That now() write was the single root-cause drift bug.
--
-- This migration introduces an explicit top-level tournaments.editions entity that
-- owns the one shared, grid-anchored started_at/ends_at; each category's cycle row
-- becomes a child of the edition (FK edition_id). The cron job becomes a
-- STATUS-ONLY flip: it detects "is the configured grid boundary reached?" and
-- writes EXACT grid timestamps (next.started_at = prev.ends_at, never now()).
-- The cycle_started/cycle_completed events collapse into one edition_rollover
-- outbox row -> one TournamentRolloverEvent. Global cadence/anchor/pause/debug move
-- off tournaments.categories (0023) onto tournaments.config. A fresh-restart wipe
-- clears all cycles + tournament completions and NULLs core.completions FK on
-- cross-written rows (keeping PB times), without bootstrapping the first edition
-- (bootstrap is a service-driven action in Plan 03 so the snap-to-boundary uses
-- the configured anchor at runtime, D-13a).
--
-- Decisions resolved: single migration file (RESEARCH OQ2); outbox carries the
-- combined event via a new nullable edition_id column + nullable cycle_id +
-- extended event_type CHECK (RESEARCH A3 option a).
--
-- Wrap DDL/DML in BEGIN;/COMMIT; like 0023. The CREATE EXTENSION/cron.schedule
-- block stays an UNWRAPPED DO $body$ guarded on pg_extension like 0021 so test DBs
-- without pg_cron no-op.

BEGIN;

-- =============================================================================
-- (1) Edition entity (D-05) + child FK on cycles (D-01)
-- =============================================================================
-- The timing-owning parent. started_at/ends_at hold EXACT grid values; never now().
-- Editions need no pending/finalizing states -- those stay on the child cycles.
CREATE TABLE IF NOT EXISTS tournaments.editions
(
    id         int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL,
    ends_at    timestamptz NOT NULL,
    status     text        NOT NULL DEFAULT 'active'
               CHECK (status IN ('active', 'completed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_editions_status ON tournaments.editions (status);
CREATE INDEX IF NOT EXISTS idx_editions_ends_at ON tournaments.editions (ends_at);

COMMENT ON TABLE tournaments.editions IS
    'Top-level tournament timing entity (D-05): one shared grid-anchored started_at/ends_at per rotation. Child tournaments.cycles link via edition_id.';
COMMENT ON COLUMN tournaments.editions.started_at IS
    'EXACT grid value (anchor + N x period); NEVER now() (D-08).';
COMMENT ON COLUMN tournaments.editions.ends_at IS
    'started_at + period; the next edition inherits this as its started_at (D-08).';

-- Child link: each cycle belongs to one edition; cascade-delete on edition wipe.
ALTER TABLE tournaments.cycles
    ADD COLUMN IF NOT EXISTS edition_id int REFERENCES tournaments.editions(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_cycles_edition_id ON tournaments.cycles (edition_id);

COMMENT ON COLUMN tournaments.cycles.edition_id IS
    'Parent edition (D-01/D-05): all active categories share one edition per rotation.';

-- =============================================================================
-- (2) Global cadence/anchor/pause/debug config on the singleton (D-02/03/06/07)
-- =============================================================================
ALTER TABLE tournaments.config
    ADD COLUMN IF NOT EXISTS cadence text NOT NULL DEFAULT 'weekly'
        CHECK (cadence IN ('weekly', 'biweekly')),
    ADD COLUMN IF NOT EXISTS anchor_weekday int NOT NULL DEFAULT 1
        CHECK (anchor_weekday BETWEEN 0 AND 6),
    ADD COLUMN IF NOT EXISTS anchor_time time NOT NULL DEFAULT '00:00',
    ADD COLUMN IF NOT EXISTS anchor_tz text NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS transitions_paused boolean NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS debug_cycle_seconds int
        CHECK (debug_cycle_seconds IS NULL OR debug_cycle_seconds > 0);

COMMENT ON COLUMN tournaments.config.cadence IS
    'Global cycle cadence (D-02): weekly | biweekly. Replaces per-category cycle_frequency.';
COMMENT ON COLUMN tournaments.config.anchor_weekday IS
    'Grid anchor weekday using PostgreSQL EXTRACT(DOW) convention: 0=Sun..6=Sat (A8). 1=Monday default.';
COMMENT ON COLUMN tournaments.config.anchor_time IS
    'Grid anchor time-of-day in anchor_tz wall-clock (D-06/D-07).';
COMMENT ON COLUMN tournaments.config.anchor_tz IS
    'IANA timezone name for the grid anchor (D-07). NOT CHECK-constrained (subquery against pg_timezone_names is not allowed in a CHECK); the service layer MUST validate anchor_tz is a known tz name before persisting (RESEARCH Security V5). Default UTC.';
COMMENT ON COLUMN tournaments.config.transitions_paused IS
    'Global hiatus lever (D-03/D-12): when TRUE, the boundary still finalizes the active edition but no next edition is created.';
COMMENT ON COLUMN tournaments.config.debug_cycle_seconds IS
    'DEBUG/TEST ONLY (D-03): overrides the edition period in seconds; NULL = normal weekly/biweekly cadence.';

-- =============================================================================
-- (3) Migrate per-category levers to global, then DROP them (D-02/D-03)
-- =============================================================================
UPDATE tournaments.config SET transitions_paused = (
    SELECT COALESCE(bool_or(transitions_paused), FALSE) FROM tournaments.categories
) WHERE id = 1;

ALTER TABLE tournaments.categories
    DROP COLUMN IF EXISTS transitions_paused,
    DROP COLUMN IF EXISTS debug_cycle_seconds,
    DROP COLUMN IF EXISTS cycle_frequency;

-- =============================================================================
-- (4) Outbox schema for the combined edition_rollover event (RESEARCH Pattern 3, A3a)
-- =============================================================================
-- A per-edition rollover row has no single cycle, so cycle_id becomes nullable and
-- a nullable edition_id is added; the event_type CHECK is extended.
ALTER TABLE tournaments.pending_transitions
    ADD COLUMN IF NOT EXISTS edition_id int REFERENCES tournaments.editions(id) ON DELETE CASCADE;
ALTER TABLE tournaments.pending_transitions
    ALTER COLUMN cycle_id DROP NOT NULL;

-- Extend the event_type CHECK to include edition_rollover (drop + re-add by name).
ALTER TABLE tournaments.pending_transitions
    DROP CONSTRAINT IF EXISTS pending_transitions_event_type_check;
ALTER TABLE tournaments.pending_transitions
    ADD CONSTRAINT pending_transitions_event_type_check
    CHECK (event_type IN ('cycle_started', 'cycle_completed', 'edition_rollover'));

CREATE INDEX IF NOT EXISTS idx_pending_transitions_edition_id
    ON tournaments.pending_transitions (edition_id);

COMMENT ON COLUMN tournaments.pending_transitions.edition_id IS
    'Set for edition_rollover rows; the poller groups/keys by edition_id (idempotency tournament:rollover:{edition_id}).';

-- =============================================================================
-- (5) Grid-boundary helper (D-06/D-07) -- the only place now() is consulted, and
--     only to PICK a boundary, never to store one. Body per RESEARCH Pattern 1.
-- =============================================================================
CREATE OR REPLACE FUNCTION tournaments.next_grid_boundary(
    p_from      timestamptz,
    p_weekday   int,
    p_tod       time,
    p_tz        text,
    p_period    interval
) RETURNS timestamptz
LANGUAGE plpgsql
AS $$
DECLARE
    v_local       timestamp;     -- wall-clock in the anchor tz
    v_anchor_day  date;
    v_candidate   timestamptz;
    v_dow_diff    int;
BEGIN
    -- Interpret "from" as wall-clock in the configured anchor timezone.
    v_local := p_from AT TIME ZONE p_tz;                  -- timestamptz -> local timestamp
    -- Days until the next occurrence of the target weekday (0..6).
    v_dow_diff := (p_weekday - EXTRACT(DOW FROM v_local)::int + 7) % 7;
    v_anchor_day := (v_local::date) + v_dow_diff;
    -- Compose local wall-clock boundary, convert back to timestamptz in the anchor tz
    -- (the DST-correct step: AT TIME ZONE resolves the offset for THAT date).
    v_candidate := (v_anchor_day + p_tod) AT TIME ZONE p_tz;
    -- If that instant is already past (same-day but time elapsed), step one period.
    IF v_candidate <= p_from THEN
        v_candidate := v_candidate + p_period;
    END IF;
    RETURN v_candidate;
END;
$$;

COMMENT ON FUNCTION tournaments.next_grid_boundary(timestamptz, int, time, text, interval) IS
    'Next anchor weekday@time-of-day in the given tz at/after p_from, stepping one period if already past. DST-correct via AT TIME ZONE wall-clock composition. weekday: 0=Sun..6=Sat (EXTRACT(DOW)). Used by bootstrap/resume only (D-13a).';

-- =============================================================================
-- (6) Edition transition state machine (D-01/05/08/12) -- status-only flip rewrite
-- =============================================================================
-- Invoked by pg_cron. Copies the 0023 skeleton (advisory lock + tier-then-time
-- RANK() snapshot CTE), but operates on the EDITION and NEVER writes now() into
-- edition timestamps: the next edition inherits started_at = old.ends_at and
-- ends_at = old.ends_at + period. On pause it finalizes the active edition and
-- creates NO next edition (hiatus, D-12). Writes ONE edition_rollover outbox row
-- with payload {results, started, edition_id} -- keys byte-identical to
-- TournamentRolloverEvent (Pitfall 5).
CREATE OR REPLACE FUNCTION tournaments.process_edition_transitions()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_cfg         record;
    v_edition     record;
    v_period      interval;
    v_child       record;
    v_standings   jsonb;
    v_winner      bigint;  -- core.users.id is a Discord snowflake (bigint); int overflows
    v_results     jsonb := '[]'::jsonb;
    v_started     jsonb := '[]'::jsonb;
    v_new_edition int;
    v_next_map    int;
    v_new_cycle   int;
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

    -- (a) Finalize every child cycle of the due edition: snapshot standings + winner,
    --     mark completed, accumulate the results[] payload (one entry per category).
    FOR v_child IN
        SELECT cy.id, cy.category_id, cy.map_id
        FROM tournaments.cycles cy
        WHERE cy.edition_id = v_edition.id
          AND cy.status IN ('active', 'finalizing')
        ORDER BY cy.id
    LOOP
        -- Stop new submissions before snapshotting (the submit guard rejects on any
        -- non-active status).
        UPDATE tournaments.cycles SET status = 'finalizing' WHERE id = v_child.id;

        -- Snapshot final placements: identical tier-then-time ranking to
        -- fetch_leaderboard (verified DESC, time ASC). winner = the rank-1 user.
        WITH best_per_user AS (
            SELECT DISTINCT ON (tc.user_id)
                tc.user_id, tc.time, tc.verified, tc.completion
            FROM tournaments.completions tc
            WHERE tc.cycle_id = v_child.id
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

        UPDATE tournaments.cycles
        SET status = 'completed', ended_at = now()
        WHERE id = v_child.id;

        -- Accumulate this category's results (shape == TournamentCycleCompletedEvent).
        v_results := v_results || jsonb_build_object(
            'cycle_id', v_child.id,
            'category_id', v_child.category_id,
            'standings', v_standings,
            'winner_user_id', v_winner
        );
    END LOOP;

    -- (b) Finalize the edition itself (status-only flip; NO now() into started_at/ends_at).
    UPDATE tournaments.editions SET status = 'completed' WHERE id = v_edition.id;

    -- (c) Create the next edition UNLESS paused (D-12 hiatus). The next edition
    --     inherits the EXACT grid boundary -- this is the drift fix (D-08):
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
            VALUES (v_new_edition, v_cat.category_id, v_next_map, 'active', v_edition.ends_at)
            RETURNING id INTO v_new_cycle;

            -- Accumulate this category's start (shape == TournamentCycleStartedEvent).
            v_started := v_started || (
                SELECT jsonb_build_object(
                    'cycle_id', v_new_cycle,
                    'category_id', v_cat.category_id,
                    'map_id', v_next_map,
                    'map_code', m.code,
                    'map_name', m.map_name,
                    'started_at', v_edition.ends_at,
                    'ends_at', v_edition.ends_at + v_period
                )
                FROM core.maps m
                WHERE m.id = v_next_map
            );
        END LOOP;
    END IF;

    -- (d) Outbox: ONE edition_rollover row. payload keys (results, started, edition_id)
    --     are byte-identical to TournamentRolloverEvent (Pitfall 5). cycle_id is NULL.
    INSERT INTO tournaments.pending_transitions (cycle_id, edition_id, event_type, payload)
    VALUES (
        NULL,
        v_edition.id,
        'edition_rollover',
        jsonb_build_object(
            'results', v_results,
            'started', v_started,
            'edition_id', v_edition.id
        )
    );
END;
$$;

COMMENT ON FUNCTION tournaments.process_edition_transitions() IS
    'pg_cron-driven single-edition rollover (D-01/05/08/12): finalizes the due edition + its child cycles (tier-then-time snapshot), creates the next edition with started_at = prev.ends_at (NEVER now()), pre-rolls one child cycle per active category, and writes ONE edition_rollover outbox row {results, started, edition_id}. transitions_paused suppresses the next edition (hiatus).';

-- =============================================================================
-- (7) Fresh-restart wipe (D-13/14/15) -- preserve core PBs, NULL the FK only
-- =============================================================================
-- 1) NULL the link on cross-written core rows (KEEP the core.completions PB rows).
--    The FK is ON DELETE SET NULL (0020:170-172); the explicit UPDATE is
--    intention-revealing and order-safe. NEVER add CASCADE to that FK.
UPDATE core.completions SET tournament_completion_id = NULL
WHERE tournament_completion_id IS NOT NULL;
-- 2) Wipe tournament state with ordered DELETEs (children first), NOT TRUNCATE CASCADE.
--    CRITICAL (D-15): `TRUNCATE tournaments.completions CASCADE` would structurally
--    truncate core.completions (which has an FK into tournaments.completions),
--    destroying PB rows regardless of the ON DELETE SET NULL action -- TRUNCATE
--    ignores per-row FK actions. Row-level DELETE honors ON DELETE SET NULL/CASCADE,
--    so deleting tournaments.completions only NULLs the (already-NULLed) core link
--    and never deletes a core.completions row.
DELETE FROM tournaments.completions;  -- core.completions FK -> SET NULL (already NULL)
DELETE FROM tournaments.cycles;       -- xp_grants CASCADE; streaks.last_cycle_id SET NULL
DELETE FROM tournaments.editions;
-- 3) Drop any stale outbox rows.
DELETE FROM tournaments.pending_transitions;

COMMIT;

-- =============================================================================
-- (8) Idempotent pg_cron re-registration (guarded on pg_extension; test DBs no-op)
-- =============================================================================
-- Keep the job NAME 'tournament-cycle-transitions' (A7); point it at the new fn.
-- UNWRAPPED DO block per the 0021 pattern so test DBs without pg_cron no-op.
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
