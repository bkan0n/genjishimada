-- =============================================================================
-- Tournament fake-data seed  ***DEBUG ONLY — DO NOT COMMIT***
-- =============================================================================
-- Creates:
--   * 2 categories   ("Hard", "Extreme")           -> ids 1 and 2 on an empty table
--   * 26 editions     (weekly chain: 25 completed + 1 active)
--   * 52 cycles       (one per category per edition, distinct maps within an edition)
--   * 520 completions (10 users per cycle: 5 fixed "regulars" + 5 random)
--   * ~9 boundary-streak cohort users (3 per cohort) seeded into trailing edition
--     runs -> derived streaks 2/3/5 to exercise the streak_xp thresholds (3 and 5)
--   * per-user streaks (derived from the seeded completion data)
--
-- "Tournament" here == an edition (one weekly rotation). Bumping v_n_editions is
-- the single knob for how many tournaments to seed.
--
-- Streaks (tournaments.streaks):
--   To make streaks interesting (instead of the all-1s you'd get from picking 10
--   independent random users per cycle), we pin a pool of 5 "regular" users who
--   play EVERY edition. They build long streaks (up to v_n_editions) that exercise
--   the streak_xp thresholds (3 and 5); the 5 random fillers per cycle produce a
--   natural spread of shorter streaks. In addition, small disjoint "boundary"
--   cohorts (v_cohort_size users each) are pinned to consecutive TRAILING edition
--   runs of 2, 3, and 5 editions, so the same derivation lands them exactly on
--   current_streak 2, 3, and 5 — the streak_xp threshold boundaries (3 and 5) that
--   regulars (long streaks) and fillers (~1) would otherwise never land on. Cohort
--   users are distinct from the regulars and from each other (sliced from a single
--   random draw), and are excluded from filler selection so they cannot be randomly
--   upgraded into a longer streak. After seeding completions we DERIVE streaks
--   from the data via gaps-and-islands over editions (chronological), so the table
--   is always consistent with the completions, not hand-faked. Participation is
--   per-edition (weekly), matching the "weekly participation streak" semantics.
--   current_streak = trailing run of consecutive editions ending at the user's
--   most-recent participation; max_streak = longest such run ever; last_cycle_id =
--   the most recent cycle the user submitted to.
--
-- Schema is current as of migration 0025:
--   - tournaments.completions.verified is a GENERATED column -> we write `status`
--     ('pending'|'verified'|'rejected'), never `verified` directly.
--   - cadence lives on tournaments.config (global), not on the category.
--   - cycles hang off an edition via edition_id; the edition owns started_at/ends_at.
--
-- Run (local dev):
--   psql "postgresql://genji:local_dev_password@localhost:5432/genji" \
--        -f scripts/seed_tournament_fake_data.sql
--
-- Requires at least 6 maps in core.maps and 10 users in core.users (import a DB
-- snapshot first via ./scripts/import-db-from-vps.sh dev).
-- =============================================================================

-- Optional reset so this is re-runnable (uncomment if you need to wipe + reseed).
-- WARNING: destroys ALL tournament data and resets ids to 1.
-- TRUNCATE tournaments.completions, tournaments.cycles,
--          tournaments.editions, tournaments.streaks,
--          tournaments.pending_transitions, tournaments.categories
--     RESTART IDENTITY CASCADE;

BEGIN;

DO $$
DECLARE
    v_n_editions int := 26;                 -- how many tournaments (editions) to seed
    v_cat_ids    int[];
    v_regulars   bigint[];                  -- 5 users who play every edition (long streaks)
    v_cohort_size int := 3;                 -- users per boundary-streak cohort (single knob)
    v_cohort2    bigint[];                  -- users pinned to a trailing run of 2 editions -> streak 2
    v_cohort3    bigint[];                  -- users pinned to a trailing run of 3 editions -> streak 3
    v_cohort5    bigint[];                  -- users pinned to a trailing run of 5 editions -> streak 5
    v_cohorts    bigint[];                  -- v_cohort2 || v_cohort3 || v_cohort5 (for filler exclusion)
    v_cohort_pick bigint[];                 -- the single random pick we slice the disjoint cohorts from
    v_used_maps  int[];                     -- keep maps distinct WITHIN an edition
    v_edition_id int;
    v_cycle_id   int;
    v_map_id     int;
    v_users      bigint[];
    v_now        timestamptz := now();
    v_start      timestamptz;
    v_end        timestamptz;
    v_window_end timestamptz;               -- upper bound for completion timestamps
    v_ed_status  text;
    v_cy_status  text;
    v_cy_ended   timestamptz;
    v_status     text;
    v_cat        int;
    i            int;
    j            int;
    n_maps       int;
    n_users      int;
BEGIN
    SELECT count(*) INTO n_maps  FROM core.maps;
    SELECT count(*) INTO n_users FROM core.users;
    IF n_maps  < 6  THEN RAISE EXCEPTION 'Need >= 6 maps in core.maps (found %)',  n_maps;  END IF;
    IF n_users < 10 THEN RAISE EXCEPTION 'Need >= 10 users in core.users (found %)', n_users; END IF;

    -- ---- Categories (empty table -> ids 1 and 2) ----------------------------
    INSERT INTO tournaments.categories
        (name, difficulties, participation_xp, placement_xp, streak_xp, champion_role_id)
    VALUES
        ('Hard', ARRAY['Hard', 'Very Hard'], 50,
         '[{"place": 1, "xp": 200}, {"place": 2, "xp": 100}, {"place": 3, "xp": 50}]'::jsonb,
         '[{"threshold": 3, "xp": 150}, {"threshold": 5, "xp": 300}]'::jsonb, NULL),
        ('Extreme', ARRAY['Extreme', 'Hell'], 75,
         '[{"place": 1, "xp": 300}, {"place": 2, "xp": 150}, {"place": 3, "xp": 75}]'::jsonb,
         '[{"threshold": 3, "xp": 200}, {"threshold": 5, "xp": 400}]'::jsonb, NULL);

    SELECT array_agg(id ORDER BY id) INTO v_cat_ids
    FROM tournaments.categories
    WHERE name IN ('Hard', 'Extreme');

    -- ---- Regulars: 5 users who participate in EVERY edition -----------------
    -- These build the long streaks (up to v_n_editions) that exercise streak_xp.
    SELECT array_agg(id) INTO v_regulars
    FROM (SELECT id FROM core.users ORDER BY random() LIMIT 5) s;

    -- ---- Boundary-streak cohorts: small disjoint pools at streaks 2/3/5 -----
    -- Pick 3 * v_cohort_size DISTINCT non-regular users in ONE random draw, then
    -- slice into disjoint cohorts so no user appears in two cohorts. Each cohort
    -- is later pinned to a consecutive trailing edition run (Task 2) so the streak
    -- derivation lands them exactly on 2, 3, and 5 (the streak_xp thresholds).
    -- The existing `n_users < 10` floor is the only guard; the 2000-user staging
    -- DB trivially satisfies 5 regulars + 3*v_cohort_size cohorts + 5 fillers/cycle.
    SELECT array_agg(id) INTO v_cohort_pick
    FROM (
        SELECT id FROM core.users
        WHERE id <> ALL (v_regulars)
        ORDER BY random()
        LIMIT 3 * v_cohort_size
    ) s;

    v_cohort2 := v_cohort_pick[1 : v_cohort_size];
    v_cohort3 := v_cohort_pick[v_cohort_size + 1 : 2 * v_cohort_size];
    v_cohort5 := v_cohort_pick[2 * v_cohort_size + 1 : 3 * v_cohort_size];
    v_cohorts := v_cohort2 || v_cohort3 || v_cohort5;

    -- ---- N editions (weekly chain): editions 1..N-1 completed, N active -----
    -- The last edition starts ~2 days ago and ends ~5 days in the future (active);
    -- every earlier edition is a closed 7-day window walking back in time.
    FOR i IN 1..v_n_editions LOOP
        v_start := v_now - ((7 * (v_n_editions - 1) + 2 - (i - 1) * 7) || ' days')::interval;
        v_end   := v_start + interval '7 days';

        IF i < v_n_editions THEN
            v_ed_status  := 'completed';
            v_cy_status  := 'completed';
            v_cy_ended   := v_end;
            v_window_end := v_end;       -- completions land inside the closed window
        ELSE
            v_ed_status  := 'active';
            v_cy_status  := 'active';
            v_cy_ended   := NULL;
            v_window_end := v_now;       -- active completions land up to "now"
        END IF;

        INSERT INTO tournaments.editions (started_at, ends_at, status, start_announced)
        VALUES (v_start, v_end, v_ed_status, TRUE)
        RETURNING id INTO v_edition_id;

        -- maps are distinct within an edition, but may repeat across editions
        v_used_maps := ARRAY[]::int[];

        -- one cycle per category, each on a distinct random map
        FOREACH v_cat IN ARRAY v_cat_ids LOOP
            SELECT id INTO v_map_id
            FROM core.maps
            WHERE id <> ALL (v_used_maps)
            ORDER BY random()
            LIMIT 1;
            v_used_maps := v_used_maps || v_map_id;

            INSERT INTO tournaments.cycles
                (edition_id, category_id, map_id, status, started_at, ended_at)
            VALUES
                (v_edition_id, v_cat, v_map_id, v_cy_status, v_start, v_cy_ended)
            RETURNING id INTO v_cycle_id;

            -- 10 distinct users: the 5 fixed regulars + 5 random fillers
            -- Exclude both regulars AND cohort users: a cohort user randomly picked
            -- as a filler in an edition outside its assigned trailing run would
            -- corrupt its derived streak (e.g. upgrade a streak-2 user toward 26).
            SELECT v_regulars || array_agg(id) INTO v_users
            FROM (
                SELECT id FROM core.users
                WHERE id <> ALL (v_regulars) AND id <> ALL (v_cohorts)
                ORDER BY random()
                LIMIT 5
            ) s;

            FOR j IN 1..10 LOOP
                -- completed cycles: 8 verified + 2 pending; active: 6 verified + 4 pending
                IF v_cy_status = 'completed' THEN
                    v_status := CASE WHEN j <= 8 THEN 'verified' ELSE 'pending' END;
                ELSE
                    v_status := CASE WHEN j <= 6 THEN 'verified' ELSE 'pending' END;
                END IF;

                INSERT INTO tournaments.completions
                    (cycle_id, user_id, map_id, time, screenshot, video, status, completion, inserted_at)
                VALUES
                    (v_cycle_id,
                     v_users[j],
                     v_map_id,
                     round((20 + random() * 100)::numeric, 2),     -- 20.00 .. 120.00 s
                     'https://cdn.genji.pk/seed/fake-screenshot-' || v_cycle_id || '-' || j || '.png',
                     CASE WHEN j % 3 = 0
                          THEN 'https://youtu.be/seed-' || v_cycle_id || '-' || j
                          ELSE NULL END,
                     v_status,
                     (v_status = 'verified'),                       -- completion flag
                     v_start + random() * (v_window_end - v_start)); -- inserted within window
            END LOOP;
        END LOOP;
    END LOOP;

    -- ---- Boundary-streak cohort completions (seeded before derivation) ------
    -- Pin each cohort to a consecutive trailing run of editions so the SAME
    -- gaps-and-islands derivation below lands them on current_streak 2/3/5 with no
    -- changes to that query. Cohort users are excluded from fillers (above), so
    -- these trailing-run rows are their ONLY participations.
    --   v_cohort2 -> last 2 editions  (seq > v_n_editions - 2)
    --   v_cohort3 -> last 3 editions  (seq > v_n_editions - 3)
    --   v_cohort5 -> last 5 editions  (seq > v_n_editions - 5)
    -- One completion per cohort user per target edition, in ONE cycle of that
    -- edition (MIN(cycle id) per edition). The completion column shape matches the
    -- in-loop INSERT exactly; `verified` is GENERATED so we only write status/completion.
    INSERT INTO tournaments.completions
        (cycle_id, user_id, map_id, time, screenshot, video, status, completion, inserted_at)
    WITH ed AS (   -- chronological edition sequence; trailing run ends at the active edition
        SELECT id, started_at, row_number() OVER (ORDER BY started_at) AS edition_seq
        FROM tournaments.editions
    ),
    edition_cycle AS (   -- one representative cycle per edition (lowest cycle id)
        SELECT DISTINCT ON (cy.edition_id)
               cy.edition_id, cy.id AS cycle_id, cy.map_id, cy.status AS cy_status,
               ed.started_at, ed.edition_seq
        FROM tournaments.cycles cy
        JOIN ed ON ed.id = cy.edition_id
        ORDER BY cy.edition_id, cy.id
    ),
    cohort_runs (cohort, run_length) AS (
        -- explicit casts keep the array element type unambiguous for unnest() below
        VALUES (v_cohort2::bigint[], 2), (v_cohort3::bigint[], 3), (v_cohort5::bigint[], 5)
    ),
    cohort_users AS (   -- expand each cohort array into its users + run length
        SELECT run_length, unnest(cohort) AS user_id
        FROM cohort_runs
    )
    SELECT
        ec.cycle_id,
        cu.user_id,
        ec.map_id,
        round((20 + random() * 100)::numeric, 2),                      -- 20.00 .. 120.00 s
        'https://cdn.genji.pk/seed/fake-screenshot-' || ec.cycle_id || '-' || cu.user_id || '.png',
        NULL,                                                          -- video
        'verified',                                                    -- status (verified -> participation)
        TRUE,                                                          -- completion flag
        -- inside the edition window: active cycle bounds to v_now, completed to ended-window
        ec.started_at
            + random() * (CASE WHEN ec.cy_status = 'active'
                               THEN v_now
                               ELSE ec.started_at + interval '7 days'
                          END - ec.started_at)
    FROM cohort_users cu
    JOIN ed              ON ed.edition_seq > v_n_editions - cu.run_length
    JOIN edition_cycle ec ON ec.edition_seq = ed.edition_seq;

    -- ---- Streaks (derived from the seeded completions) ----------------------
    -- Gaps-and-islands over editions (chronological) per user:
    --   * island = run of consecutive editions the user participated in
    --   * max_streak     = longest island
    --   * current_streak = the island containing the user's most-recent edition
    --   * last_cycle_id  = the most recent cycle they submitted to
    INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
    WITH ed AS (
        SELECT id, row_number() OVER (ORDER BY started_at) AS edition_seq
        FROM tournaments.editions
    ),
    part AS (   -- distinct (user, edition) participations
        SELECT DISTINCT c.user_id, ed.edition_seq
        FROM tournaments.completions c
        JOIN tournaments.cycles cy ON cy.id = c.cycle_id
        JOIN ed ON ed.id = cy.edition_id
    ),
    grp AS (    -- gaps-and-islands key: edition_seq minus its per-user rank is constant within a run
        SELECT user_id, edition_seq,
               edition_seq - row_number() OVER (PARTITION BY user_id ORDER BY edition_seq) AS island
        FROM part
    ),
    islands AS (
        SELECT user_id, island,
               count(*)         AS streak_len,
               max(edition_seq) AS last_edition_seq
        FROM grp
        GROUP BY user_id, island
    ),
    maxs AS (
        SELECT user_id, max(streak_len) AS max_streak
        FROM islands
        GROUP BY user_id
    ),
    current_island AS (   -- the island reaching the user's most recent participation
        SELECT DISTINCT ON (user_id) user_id, streak_len AS current_streak
        FROM islands
        ORDER BY user_id, last_edition_seq DESC
    ),
    last_cycle AS (       -- most recent cycle the user submitted to
        SELECT DISTINCT ON (c.user_id) c.user_id, c.cycle_id
        FROM tournaments.completions c
        JOIN tournaments.cycles cy ON cy.id = c.cycle_id
        JOIN ed ON ed.id = cy.edition_id
        ORDER BY c.user_id, ed.edition_seq DESC, c.cycle_id DESC, c.inserted_at DESC
    )
    SELECT ci.user_id, ci.current_streak, m.max_streak, lc.cycle_id, v_now
    FROM current_island ci
    JOIN maxs m       ON m.user_id  = ci.user_id
    JOIN last_cycle lc ON lc.user_id = ci.user_id;

    RAISE NOTICE 'Seeded % categories, % editions, % cycles, % completions, % streak rows.',
        array_length(v_cat_ids, 1),
        v_n_editions,
        v_n_editions * array_length(v_cat_ids, 1),
        v_n_editions * array_length(v_cat_ids, 1) * 10,
        (SELECT count(*) FROM tournaments.streaks);
END $$;

COMMIT;
