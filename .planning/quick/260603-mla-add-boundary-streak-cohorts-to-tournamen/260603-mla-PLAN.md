---
phase: quick-260603-mla
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/seed_tournament_fake_data.sql
autonomous: true
requirements: [QUICK-260603-mla]
must_haves:
  truths:
    - "After a reseed, tournaments.streaks contains users at streak values 2, 3, and 5 (boundary cohorts) in addition to the existing 1 and 26"
    - "Cohort users are distinct from v_regulars and distinct across cohorts (no user in two cohorts, no cohort user upgraded to streak 26 by filler selection)"
    - "Existing regulars (streak 26) and filler (streak ~1) behavior is unchanged"
    - "The streak-derivation INSERT (lines ~181-224) is unchanged — cohorts are picked up automatically"
    - "Cohort completions match the existing tournaments.completions column shape (status, completion; never verified)"
    - "Header comment block documents the new cohorts"
  artifacts:
    - path: "scripts/seed_tournament_fake_data.sql"
      provides: "Boundary-streak cohort seeding + updated header docs"
      contains: "cohort"
  key_links:
    - from: "cohort completion INSERT"
      to: "streak-derivation gaps-and-islands query"
      via: "completions seeded into consecutive trailing editions before derivation runs"
      pattern: "INSERT INTO tournaments.completions"
---

<objective>
Add boundary-streak cohorts to `scripts/seed_tournament_fake_data.sql` so that after a
reseed, `tournaments.streaks` contains users sitting at intermediate streak values that
exercise the `streak_xp` thresholds (3 and 5), instead of the current degenerate
{26: 5, 1: many} bimodal distribution.

Purpose: The seed currently produces only streak=26 (the 5 regulars) and streak~1
(random fillers). The threshold branches (threshold 3 -> XP, threshold 5 -> XP) are
never hit by any seeded user, so reward/threshold logic cannot be exercised against
seed data.

Output: A modified debug-only seed script that, on reseed, yields non-zero
`tournaments.streaks` counts at streak values 2, 3, and 5 — derived (not hand-faked)
from cohort completions inserted into consecutive trailing editions.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@scripts/seed_tournament_fake_data.sql

<interfaces>
<!-- Key facts about the existing script the executor must honor. -->

Streaks are DERIVED, never hand-written. The derivation (lines ~181-224) is a
gaps-and-islands query over editions in chronological order:
  - current_streak = trailing run of consecutive editions ending at the user's most-recent participation
  - To make a user with current_streak = N: insert that user's completions into the
    N most-recent (trailing) editions. Edition N (the last, i = v_n_editions) is 'active';
    editions 1..N-1 are 'completed'.

completions column shape (line ~157-170): `verified` is a GENERATED column (migration
0025). Write `status` ('pending'|'verified'|'rejected') and the `completion` boolean,
NEVER `verified`. Columns are exactly:
  (cycle_id, user_id, map_id, time, screenshot, video, status, completion, inserted_at)

The cycles and editions already exist after the FOR i IN 1..v_n_editions loop. Each
edition has one cycle per category (2 categories -> 2 cycles per edition). The completion
timestamp window for a completed edition is [v_start, v_end]; for the active edition it
is [v_start, v_now].

The filler selection (lines ~141-147) excludes v_regulars via `WHERE id <> ALL (v_regulars)`.
This clause MUST be extended to also exclude cohort users, or a cohort user could be
randomly picked as a filler in editions outside its assigned run and corrupt its streak.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Select disjoint cohort users and exclude them from filler selection</name>
  <files>scripts/seed_tournament_fake_data.sql</files>
  <action>
Add cohort infrastructure to the DO block, modeled on the existing v_regulars "single knob" style:

1. Declare cohort variables near v_regulars (line ~54): a size knob `v_cohort_size int := 3;`
   and three cohort arrays `v_cohort2 bigint[]; v_cohort3 bigint[]; v_cohort5 bigint[];`
   Also declare a combined `v_cohorts bigint[];` for exclusion convenience.

2. After v_regulars is selected (line ~97), select 3 * v_cohort_size DISTINCT users in a
   SINGLE `ORDER BY random()` pick that excludes v_regulars, capturing them into an array,
   then slice disjoint sub-arrays: first v_cohort_size -> v_cohort2, next v_cohort_size ->
   v_cohort3, last v_cohort_size -> v_cohort5. Use array slicing (e.g. picked[1:v_cohort_size],
   picked[v_cohort_size+1 : 2*v_cohort_size], etc.) so no user appears in two cohorts.
   Set `v_cohorts := v_cohort2 || v_cohort3 || v_cohort5;`.
   Guard: this needs 5 regulars + 3*v_cohort_size = 14 users at default; the existing
   `n_users < 10` RAISE is the current floor — leave it but add a brief inline comment that
   the 2000-user staging DB trivially satisfies regulars+cohorts+fillers (do NOT over-engineer
   the guard).

3. Extend the filler WHERE clause (line ~144) from `WHERE id <> ALL (v_regulars)` to ALSO
   exclude cohort users: `WHERE id <> ALL (v_regulars) AND id <> ALL (v_cohorts)`. This
   prevents a cohort user from being randomly upgraded into "plays every edition / extra editions".
  </action>
  <verify>
    <automated>grep -n "v_cohort" scripts/seed_tournament_fake_data.sql | grep -v '^[0-9]*:--' | head -30</automated>
  </verify>
  <done>Three disjoint cohort arrays selected from a single random pick excluding v_regulars; filler WHERE clause excludes both v_regulars and v_cohorts. Existing regulars/filler semantics otherwise unchanged.</done>
</task>

<task type="auto">
  <name>Task 2: Seed cohort completions into trailing editions before derivation</name>
  <files>scripts/seed_tournament_fake_data.sql</files>
  <action>
After the `FOR i IN 1..v_n_editions LOOP` finishes (line ~173, the END LOOP that closes
the editions loop) but BEFORE the streak-derivation INSERT (line ~181), seed cohort
completions so the derivation picks them up automatically (the derivation query needs NO changes):

- v_cohort2 -> last 2 editions (editions v_n_editions-1 and v_n_editions) -> current_streak = 2
- v_cohort3 -> last 3 editions (v_n_editions-2 .. v_n_editions) -> current_streak = 3
- v_cohort5 -> last 5 editions (v_n_editions-4 .. v_n_editions) -> current_streak = 5

Implementation approach: write a set-based INSERT (or a small loop) that, for each cohort
user and each target trailing edition, inserts ONE completion into one existing cycle of
that edition. To resolve cycle_id, map_id, and the timing window for a given edition, join
the already-created `tournaments.editions` (ordered by started_at to map sequence ->
edition) to `tournaments.cycles` (pick one cycle per edition, e.g. MIN(cycle.id) or the first
category's cycle). Use the cycle's own status to decide the window upper bound: a 'completed'
cycle uses its `ended_at`; the 'active' cycle uses v_now. Derive cycle started_at from the
edition for the lower bound.

Column shape MUST match the existing completion INSERT exactly:
(cycle_id, user_id, map_id, time, screenshot, video, status, completion, inserted_at).
Use `status = 'verified'` and `completion = true` for cohort rows (participation is what the
derivation keys on — a verified row is the simplest valid participation). map_id = the cycle's
map_id. time = a plausible value (e.g. round((20 + random()*100)::numeric, 2)). screenshot =
a seed URL referencing cycle id + user. video = NULL. inserted_at = a timestamp inside the
edition window (started_at + random()*(window_end - started_at)).

Recommended structure: a helper expression set that maps edition row_number (chronological)
to the desired cohorts. The cleanest form is a CTE-driven INSERT: build `ed` with
row_number() OVER (ORDER BY started_at) AS seq, join one cycle per edition, cross-join the
appropriate cohort users filtered by `seq > v_n_editions - <run_length>`. Do this as three
INSERTs (one per cohort with its run length) or one INSERT with a UNION/VALUES table of
(cohort_array, run_length). Prefer whichever is clearer; do not over-engineer.

CRITICAL: insert ONLY new rows; do not alter the existing in-loop completion inserts. The
cohort users are excluded from fillers (Task 1) so their ONLY participations are these
trailing-run rows -> derivation yields exactly current_streak 2/3/5.
  </action>
  <verify>
    <automated>grep -c "INSERT INTO tournaments.completions" scripts/seed_tournament_fake_data.sql</automated>
  </verify>
  <done>Cohort completions are inserted after the editions loop and before the streak-derivation INSERT, using the exact completions column shape (status/completion, never verified), each cohort assigned to its consecutive trailing run (2/3/5 editions). The derivation INSERT is unchanged.</done>
</task>

<task type="auto">
  <name>Task 3: Update header documentation and review correctness</name>
  <files>scripts/seed_tournament_fake_data.sql</files>
  <action>
1. Update the header comment block (lines ~4-25):
   - In "Creates:" add a line describing the boundary-streak cohorts (e.g. "~9 cohort users
     seeded into trailing edition runs -> streaks 2/3/5 to exercise streak_xp thresholds").
   - In the "Streaks (tournaments.streaks):" paragraph, add a sentence explaining that, in
     addition to regulars (long streaks) and fillers (~1), small disjoint cohorts are pinned
     to consecutive trailing edition runs so the derivation lands users exactly on streak 2,
     3, and 5 — the streak_xp threshold boundaries (3 and 5). Note cohorts are distinct from
     regulars and from each other, and are excluded from filler selection.
   - Keep the documentation as thorough and self-consistent as the existing header.

2. Perform a careful SQL review (the executor likely has no DB access): confirm array slicing
   indices are 1-based and disjoint; confirm `id <> ALL (v_cohorts)` is added to fillers;
   confirm cohort INSERTs run after the editions loop and before the derivation INSERT;
   confirm the completion column list matches and `verified` is never written; confirm the
   trailing-run edition selection uses chronological row_number (ORDER BY started_at) so the
   trailing run ends at the active edition.

3. If psql is available, run a parse/dry check; otherwise document in the SUMMARY that the
   verification is a careful SQL review (the script is debug-only with no automated tests; a
   live check is `SELECT max_streak, count(*) FROM tournaments.streaks GROUP BY max_streak
   ORDER BY max_streak` showing non-zero counts at 2, 3, 5 in addition to 1 and 26).
  </action>
  <verify>
    <automated>grep -ni "cohort" scripts/seed_tournament_fake_data.sql | head -5; command -v psql >/dev/null 2>&1 && echo "psql available — optional parse check" || echo "psql absent — careful SQL review is the verification"</automated>
  </verify>
  <done>Header "Creates:" and "Streaks" sections document the cohorts; SQL review confirms disjoint cohorts, filler exclusion, insertion ordering, and correct (status-not-verified) column shape.</done>
</task>

</tasks>

<verification>
- Script remains a single transactional DO block that parses (psql -f, or careful review if no DB).
- After reseed against a 2000-user staging DB:
  `SELECT max_streak, count(*) FROM tournaments.streaks GROUP BY max_streak ORDER BY max_streak`
  shows non-zero counts at 2, 3, and 5 in addition to the existing 1 and 26.
- The streak-derivation INSERT (lines ~181-224) is byte-for-byte unchanged.
- Only `scripts/seed_tournament_fake_data.sql` is modified.
</verification>

<success_criteria>
- Cohort users are distinct from v_regulars and from each other; excluded from filler selection.
- Cohorts assigned to trailing runs of 2, 3, and 5 editions -> derived current_streak 2/3/5.
- Existing regulars (26) and fillers (~1) behavior unchanged; only rows added.
- Cohort completions use the exact completions column shape (status/completion, never verified).
- Header comment block documents the cohorts and stays self-consistent.
</success_criteria>

<output>
Create `.planning/quick/260603-mla-add-boundary-streak-cohorts-to-tournamen/260603-mla-SUMMARY.md` when done.
</output>
