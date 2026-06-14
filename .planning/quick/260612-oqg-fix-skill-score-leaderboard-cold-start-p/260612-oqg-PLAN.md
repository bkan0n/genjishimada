---
phase: quick-260612-oqg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/api/repository/skill_repository.py
  - apps/api/app.py
autonomous: true
requirements: [QUICK-260612-oqg]

must_haves:
  truths:
    - "Starting the API against a fresh DB with eligible verified non-legacy completions populates skill.snapshot automatically within a few seconds of boot, no manual step"
    - "GET /api/v3/community/leaderboard?sort_column=skill_score&sort_direction=desc returns players ordered by descending non-zero skill score after cold boot"
    - "Restarting the API with an already-populated snapshot neither errors nor blocks startup, and skips the redundant initial rebuild"
    - "A failed initial population is logged and never crashes the lifespan loop"
  artifacts:
    - path: "apps/api/repository/skill_repository.py"
      provides: "snapshot_is_empty() repository method used to decide whether to run the one-time initial population"
      contains: "async def snapshot_is_empty"
    - path: "apps/api/app.py"
      provides: "skill_nightly_rebuild_poller with one-time initial population before the nightly loop"
  key_links:
    - from: "apps/api/app.py:skill_nightly_rebuild_poller"
      to: "SkillRepository.snapshot_is_empty"
      via: "skill_repo.snapshot_is_empty() guard before recompute_all on first iteration"
      pattern: "snapshot_is_empty"
    - from: "apps/api/app.py:skill_nightly_rebuild_poller"
      to: "SkillService.recompute_all"
      via: "the SAME provide_skill_repository/provide_skill_service/recompute_all path the nightly run uses"
      pattern: "recompute_all"
---

<objective>
Fix the skill-score leaderboard cold-start bug. On a fresh deploy `skill.snapshot` is
created empty by migration 0027 and never populated, so the leaderboard returns
`coalesce(skill_score,0)=0` for every player until a verification event, a config PATCH,
or the nightly 04:00 UTC rebuild fires.

Add a one-time initial population to the existing app-side poller
`skill_nightly_rebuild_poller` in `apps/api/app.py`. On startup, after the existing
sleep-before-run that dodges the cold-start `db_pool` race, run
`SkillService.recompute_all()` ONCE if `skill.snapshot` is empty, then fall into the
existing sleep-until-04:00-UTC nightly loop.

Purpose: the leaderboard sorts by real non-zero skill scores immediately on a fresh deploy.
Output: a `snapshot_is_empty()` repository method + an initial-population step in the poller.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Extracted from the codebase. The executor reuses these EXACT signatures — DO NOT fork the rebuild logic (D-04, one rebuild routine). -->

From apps/api/repository/skill_repository.py:
```python
class SkillRepository(BaseRepository):
    def __init__(self, pool: Pool) -> None: ...
    async def fetch_snapshot(self, user_id: int, *, conn: Connection | None = None) -> dict | None: ...
    async def replace_snapshot(self, rows: list[dict], *, conn: Connection | None = None) -> None: ...
    # self._get_connection(conn) returns the injected conn or falls back to self._pool

async def provide_skill_repository(state: State) -> SkillRepository:
    return SkillRepository(state.db_pool)
```

From apps/api/services/skill_service.py:
```python
class SkillService(BaseService):
    async def recompute_all(self) -> None: ...  # the single D-04 rebuild routine; in-flight collapse guard (D-05) makes overlap safe

async def provide_skill_service(state: State, skill_repo: SkillRepository) -> SkillService:
    return SkillService(state.db_pool, state, skill_repo)
```

From apps/api/app.py (the poller to modify — lines ~110-156):
```python
@asynccontextmanager
async def skill_nightly_rebuild_poller(_app: Litestar) -> AsyncGenerator[None, None]:
    async def _loop() -> None:
        from repository.skill_repository import provide_skill_repository  # local import avoids circular import
        from services.skill_service import provide_skill_service          # local import avoids circular import
        while True:
            # sleep-before-run dodges the cold-start db_pool race (asyncpg lifespan entered AFTER this poller's)
            ...
            await asyncio.sleep((next_run - now).total_seconds())
            try:
                skill_repo = await provide_skill_repository(_app.state)
                skill_service = await provide_skill_service(_app.state, skill_repo)
                await skill_service.recompute_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[!] skill nightly rebuild failed")
    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```
Note: `skill.snapshot` columns are `user_id, skill_score, maps_cleared, video_clears, hardest_raw, breakdown, computed_at`. There is NO existing count/empty method — Task 1 adds one.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add snapshot_is_empty() to SkillRepository</name>
  <files>apps/api/repository/skill_repository.py, apps/api/tests/integration/test_skill.py</files>
  <behavior>
    - Returns True when skill.snapshot has zero rows (fresh DB / post-truncate / no eligible players)
    - Returns False after recompute_all() populates the snapshot for eligible completions
  </behavior>
  <action>
    Add an async method `snapshot_is_empty(self, *, conn: Connection | None = None) -> bool` to
    `SkillRepository`, placed alongside the other snapshot methods (near `fetch_snapshot`). Use the
    existing connection pattern `_conn = self._get_connection(conn)` and run a cheap existence probe:
    `await _conn.fetchval("SELECT NOT EXISTS (SELECT 1 FROM skill.snapshot)")` and return the bool.
    Prefer `NOT EXISTS` over `COUNT(*) = 0` so the query short-circuits on the first row. Match the
    Google-style docstring format and type-annotation conventions of the surrounding methods (return
    type annotated, keyword-only `conn` via `*`, no f-strings in SQL). This is the repo method the
    constraint asks for — the poller will NOT use ad-hoc SQL.

    For the test: add a focused test in `apps/api/tests/integration/test_skill.py` that builds a
    `SkillRepository` on the `asyncpg_pool` fixture (mirror the `_recompute` helper at lines ~55-72
    which already constructs `SkillRepository(pool)`), asserts `snapshot_is_empty()` is True before any
    recompute, then seeds an eligible completion via the existing `seed` fixture, runs the shared
    recompute helper, and asserts `snapshot_is_empty()` is now False. Reuse existing fixtures and helpers;
    do not introduce new fixtures.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py -o addopts="" -p no:cacheprovider -q -k snapshot_is_empty</automated>
  </verify>
  <done>`snapshot_is_empty()` exists on SkillRepository, returns True on an empty snapshot and False after population; the new test passes.</done>
</task>

<task type="auto">
  <name>Task 2: Add one-time initial population to skill_nightly_rebuild_poller</name>
  <files>apps/api/app.py</files>
  <action>
    Modify `skill_nightly_rebuild_poller._loop` in `apps/api/app.py` to perform a one-time initial
    population before entering the nightly 04:00 UTC cadence, reusing the SAME
    `provide_skill_repository` / `provide_skill_service` / `recompute_all` path the nightly run already
    uses (D-04 — DO NOT fork the rebuild logic).

    Structure the change so the cold-start db_pool race is still dodged (the asyncpg lifespan is entered
    AFTER this poller's, so an immediate run would hit a not-ready pool):

    1. Keep the local imports of `provide_skill_repository` and `provide_skill_service` at the top of `_loop`.
    2. BEFORE the `while True:` nightly loop, add an initial-population block wrapped in the same
       try/except shape as the nightly body: `except asyncio.CancelledError: raise` then a broad
       `except Exception: log.exception("[!] skill initial population failed")`. Inside the try:
         a. First `await asyncio.sleep(...)` a short fixed delay (e.g. 5 seconds) so the asyncpg lifespan
            has populated `state.db_pool` — reuse the existing "sleep-before-run dodges the cold-start
            db_pool race" reasoning in a comment. This sleep is also the cancellation point shutdown relies on.
         b. Build `skill_repo = await provide_skill_repository(_app.state)` and
            `skill_service = await provide_skill_service(_app.state, skill_repo)`.
         c. Guard on emptiness: `if await skill_repo.snapshot_is_empty(): await skill_service.recompute_all()`.
            This makes normal restarts with a populated snapshot skip the redundant full rebuild (constraint:
            prefer "recompute only when snapshot empty"). The plan-13-04 in-flight collapse guard (D-05)
            already makes overlap with any concurrent event-driven recompute safe.
    3. Leave the existing `while True:` nightly loop (sleep-until-04:00-UTC then recompute_all) unchanged
       below the initial-population block.
    4. Update the function docstring's first paragraph to note it now also performs a one-time initial
       population on startup when the snapshot is empty (cold-start fix), before the nightly backstop.

    Do NOT change the lifespan registration, the task create/cancel/await teardown, the nightly schedule
    math, or anything outside this poller. Do NOT add a manual recompute endpoint, pg_cron, or touch the
    scoring math / the four /skill/* endpoints / the leaderboard query / the event listener.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just lint-api</automated>
  </verify>
  <done>`skill_nightly_rebuild_poller` runs `recompute_all()` once on startup only when `snapshot_is_empty()` is True (after a short db_pool-warmup sleep), then enters the unchanged nightly loop; broad except + log.exception preserved; clean cancel/await teardown preserved; `just lint-api` passes with 0 errors.</done>
</task>

</tasks>

<verification>
1. `just lint-api` passes (ruff + basedpyright strict, 0 errors).
2. Skill integration tests pass with testmon disabled:
   `cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py -o addopts="" -p no:cacheprovider -q`
3. Manual cold-start check (local): with `genjishimada-db-local` (database `genjishimada`) holding eligible
   verified non-legacy completions, boot the API (`just run-api`) and within a few seconds confirm
   `SELECT count(*) FROM skill.snapshot;` (schema `skill`) returns > 0 rows with no manual step.
4. `GET /api/v3/community/leaderboard?sort_column=skill_score&sort_direction=desc` returns players ordered
   by descending non-zero skill score with `skill_rank` unchanged.
5. Restart the API with the snapshot already populated: startup does not error or block, and the initial
   recompute is skipped (snapshot not empty).
</verification>

<success_criteria>
- Cold boot against a fresh eligible-completion DB auto-populates `skill.snapshot` within seconds, no manual step.
- Leaderboard `sort_column=skill_score&sort_direction=desc` returns descending non-zero scores; `skill_rank` unchanged.
- Restart with populated snapshot neither errors nor blocks startup; redundant rebuild skipped.
- `just lint-api` passes (0 errors).
- `test_skill.py` passes with testmon disabled.
- Initial population reuses the exact existing recompute path (no forked rebuild logic); a failure is logged, not fatal.
</success_criteria>

<output>
Create `.planning/quick/260612-oqg-fix-skill-score-leaderboard-cold-start-p/260612-oqg-SUMMARY.md` when done
</output>
