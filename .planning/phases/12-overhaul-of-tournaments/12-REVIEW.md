---
phase: 12-overhaul-of-tournaments
reviewed: 2026-06-01T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - apps/api/migrations/0024_tournament_editions_overhaul.sql
  - apps/api/repository/tournaments_repository.py
  - apps/api/routes/v3/tournaments.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/services/tournament_outbox_service.py
  - apps/api/services/tournament_service.py
  - apps/bot/extensions/tournaments.py
  - apps/bot/extensions/api_service.py
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/tests/integration/test_config_tournament.py
  - apps/api/tests/integration/test_tournament_rewards.py
  - apps/api/tests/integration/test_tournaments_integration.py
  - apps/api/tests/integration/test_tournaments_schema.py
  - apps/api/tests/repository/tournaments/conftest.py
  - apps/api/tests/repository/tournaments/test_edition_transitions.py
  - apps/api/tests/repository/tournaments/test_grid_boundary.py
  - apps/api/tests/repository/tournaments/test_outbox_poller.py
  - apps/api/tests/repository/tournaments/test_tournaments_repository.py
  - apps/api/tests/services/test_tournament_lifecycle.py
  - apps/api/tests/bot/test_tournaments_handler.py
  - apps/api/tests/bot/test_tournament_commands.py
  - apps/api/tests/bot/conftest.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-06-01T00:00:00Z
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

This phase introduces a single-edition grid-anchored tournament model to fix the category drift bug from phase 0023. The core architectural changes are sound: the drift fix (`next.started_at = prev.ends_at`, never `now()`) is correct and the migration comments accurately describe the intent. The PL/pgSQL `next_grid_boundary()` function implements DST-correct wall-clock composition properly via `AT TIME ZONE`. The fresh-restart wipe ordering is correct (UPDATE core.completions NULL first, then row-level DELETEs in child-first order, no TRUNCATE CASCADE).

Three blockers are identified. The most serious is an SQL injection vector in `TournamentRepository.update_config()` (and its mirror in the test fixture `set_global_config`): field names are interpolated directly into SQL without any allow-list guard. The second blocker is a winner-selection bug in `process_edition_transitions()`: when multiple users tie for rank 1, `MIN(user_id)` deterministically picks the lowest-ID user as champion rather than applying a fair and stable tiebreak. The third blocker is an unguarded `assert` in the bot's `tournament_reroll` slash command that will crash with an `AssertionError` (unhandled, surfaced as a 500-level Discord error) when the command is used in DMs or via a User App integration.

Five warnings cover: a TOCTOU gap in the `update_category`/`delete_category` cycle-lock check (no transaction wrapping the READ+WRITE pair), a missing `_resolve_channels()` call in `TournamentHandler` setup, the `advance_past_ends_at` test fixture applying only a flat backwards shift rather than computing the actual time-until-boundary (causing intermittent test failures on slow CI), reward processing inside the outbox transaction growing unboundedly with category count, and stale deprecated SDK types exported in `__all__` that will confuse consumers.

---

## Critical Issues

### CR-01: SQL Injection in `update_config` — field names not allow-listed

**File:** `apps/api/repository/tournaments_repository.py:75-79`

**Issue:** `update_config()` builds a dynamic `SET` clause by interpolating `field` names directly from the caller-supplied `updates` dict into the SQL string:

```python
for idx, (field, value) in enumerate(updates.items(), start=1):
    set_clauses.append(f"{field} = ${idx}")
    values.append(value)
query = f"UPDATE tournaments.config SET {', '.join(set_clauses)} WHERE id = 1"
```

There is **no allow-list check** on the field names. Any caller that passes an attacker-controlled key — even transitively (e.g. from a PATCH body that is incompletely filtered upstream) — can inject arbitrary SQL into the `SET` clause. The method is called from `TournamentService.update_config()` with a dict built from `data.*` fields, but a future refactor or middleware bug could allow untrusted keys to reach this path.

The sibling method `_set_global_config()` correctly implements an allow-list (`_GLOBAL_CONFIG_FIELDS`) and raises `ValueError` on unknown fields; `update_config()` has no equivalent guard. The test fixture `set_global_config` in `tests/repository/tournaments/conftest.py` (line 84-106) mirrors this exact vulnerability.

**Fix:**

```python
_CONFIG_FIELDS = frozenset({
    "blacklist_weeks",
    "cadence",
    "anchor_weekday",
    "anchor_time",
    "anchor_tz",
    "transitions_paused",
    "debug_cycle_seconds",
})

async def update_config(self, updates: dict, *, conn: Connection | None = None) -> None:
    if not updates:
        return
    bad = set(updates) - _CONFIG_FIELDS
    if bad:
        raise ValueError(f"unknown config fields: {sorted(bad)}")
    _conn = self._get_connection(conn)
    set_clauses = []
    values: list[object] = []
    for idx, (field, value) in enumerate(updates.items(), start=1):
        set_clauses.append(f"{field} = ${idx}")
        values.append(value)
    set_clauses.append("updated_at = now()")
    query = f"UPDATE tournaments.config SET {', '.join(set_clauses)} WHERE id = 1"
    await _conn.execute(query, *values)
```

Apply the same allow-list pattern to the `set_global_config` test fixture.

---

### CR-02: Champion winner selection uses `MIN(user_id)` — arbitrary tiebreak on tied rank-1

**File:** `apps/api/migrations/0024_tournament_editions_overhaul.sql:271`

**Issue:** In `process_edition_transitions()`, the winner of each category is computed as:

```sql
MIN(ranked.user_id) FILTER (WHERE ranked.rank = 1)
INTO v_winner
FROM ranked;
```

`RANK()` assigns the same rank to all users with equal `(verified DESC, time ASC)`. If two users post identical verified times (which is possible — the schema has no unique constraint on `(cycle_id, time)`), they both get `rank = 1`, and `MIN(user_id)` silently picks the one with the numerically smallest Discord snowflake as the champion. This user may have registered their account years before the tied competitor. The champion role is then transferred to the wrong user, XP is granted to the wrong user, and the podium embed shows one co-winner but awards the role to the other.

The leaderboard endpoint (`fetch_leaderboard`) uses the same `RANK() OVER (ORDER BY verified DESC, time ASC)` window without a tiebreak column, so the tie is equally unresolved there, but the leaderboard is display-only whereas winner selection drives the role transfer and reward.

**Fix:** Add a stable secondary tiebreak on `inserted_at ASC` (first submission wins) to both `ranked` CTEs — the one in `process_edition_transitions()` and the one in `fetch_leaderboard`:

```sql
RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC, bpu.inserted_at ASC)::int AS rank
```

Add `bpu.inserted_at` to the `best_per_user` CTE `SELECT` list. Update `fetch_leaderboard` identically for consistency. No schema change required (`inserted_at` already exists on `tournaments.completions`).

---

### CR-03: Unguarded `assert` in bot slash command crashes on DM / User App context

**File:** `apps/bot/extensions/tournaments.py:767`

**Issue:** The `tournament_reroll` command body begins:

```python
assert isinstance(itx.user, discord.Member) and itx.guild
```

`assert` statements are optimized away under `python -O` and also raise `AssertionError` (not a `discord.app_commands.AppCommandError`) when the condition is false. If this command is somehow invoked outside a guild (e.g. via a User App integration or a DM context — which Discord allows if the application is configured with the `dm_permission` flag left at its default), the assert raises and discord.py's error handler receives an `AssertionError` it does not know how to surface cleanly. In production this produces a silent failure for the user and an unclassified Sentry event rather than a user-facing "This command must be used in a server" message.

The `@app_commands.guilds(...)` decorator restricts slash-command registration to the configured guild, but does NOT prevent invocation via User App contexts in newer Discord API versions.

**Fix:** Replace the assert with an explicit guard that raises a user-facing error:

```python
if not isinstance(itx.user, discord.Member) or not itx.guild:
    raise UserFacingError("This command must be used inside the server.")
```

---

## Warnings

### WR-01: `update_category` / `delete_category` cycle-lock check is not transactional — TOCTOU gap

**File:** `apps/api/services/tournament_service.py:238-258`, `275-287`

**Issue:** Both methods acquire a connection and check for an active cycle, then mutate the category on the **same connection but without a transaction**:

```python
async with self._pool.acquire() as conn:
    cycle_id = await self._tournament_repo.check_active_cycle_for_category(
        category_id, conn=conn
    )
    if cycle_id is not None:
        raise CategoryLockedError(...)
    row = await self._tournament_repo.update_category(category_id, updates, conn=conn)
```

The connection is not inside a `conn.transaction()` block. Between the `check_active_cycle_for_category` read and the `update_category` write, the pg_cron job could activate a new cycle for this category, making the lock check stale. The comment in the docstring claims "preventing TOCTOU races" but this is only true if the operations are transactional. Without `SERIALIZABLE` or at least `REPEATABLE READ` isolation with a transaction, two concurrent admin requests or a cron tick racing the web request can slip through the guard.

**Fix:** Wrap both operations in `conn.transaction()`:

```python
async with self._pool.acquire() as conn, conn.transaction():
    cycle_id = await self._tournament_repo.check_active_cycle_for_category(...)
    ...
```

The `bootstrap_edition` method correctly uses `async with self._pool.acquire() as conn, conn.transaction():`; the same pattern should be applied here.

---

### WR-02: `TournamentHandler._resolve_channels()` is never called — `announcement_channel` and `verification_channel` are uninitialized

**File:** `apps/bot/extensions/tournaments.py:282-295`, `803`

**Issue:** `TournamentHandler` defines `_resolve_channels()` as an async helper that sets `self.announcement_channel` and `self.verification_channel`, but this method is never called in `setup()` or anywhere else. The class declares these as class-level annotations (`announcement_channel: TextChannel`, `verification_channel: TextChannel`) without setting instance values. Any call to `_on_edition_rollover`, `_on_completion_created`, or `_on_verification_changed` will raise `AttributeError` at runtime because the channel attributes are never initialized.

Looking at the `BaseHandler` class (referenced but not in scope), it likely calls `_resolve_channels()` during its own setup. If `BaseHandler.__init__` or an `on_ready` lifecycle hook drives this call, it may work in production but there is no evidence in this file that `_resolve_channels()` is invoked. The `setup()` function at line 803 only instantiates the handler and adds cogs.

**Fix:** Verify that `BaseHandler` calls `_resolve_channels()` during startup (e.g. from `setup_hook` or `on_ready`). If not, add the call explicitly:

```python
async def setup(bot: core.Genji) -> None:
    handler = TournamentHandler(bot)
    await handler._resolve_channels()
    bot.tournaments = handler
    ...
```

Or ensure `BaseHandler.__init__` schedules a `_resolve_channels()` call before the first message can arrive.

---

### WR-03: `advance_past_ends_at` fixture applies a flat shift, not a time-until-boundary shift — intermittently unreliable on slow CI

**File:** `apps/api/tests/repository/tournaments/conftest.py:193-228`

**Issue:** The `advance_past_ends_at` fixture subtracts `seconds` unconditionally from the edition window, then checks if `ends_at` is still in the future and does a second shift if needed. However, the second shift computes `delta` as the remaining time-to-boundary PLUS `seconds`, which correctly forces the window past `now()`. But the first shift always subtracts exactly `seconds`, even if `ends_at` is 7 days away — so on a fresh test DB the first `UPDATE` leaves `ends_at` in the future, and the second code path fires. This means the fixture always applies **two** consecutive UPDATE statements for any edition not already near its boundary, and the `new_ends_at` returned from the first UPDATE is silently discarded when the second UPDATE fires.

The real risk is a race condition: between the two `conn.fetchrow` + `UPDATE` calls on the inner path (lines 211-227), another transaction could modify the edition, causing the second shift to compute a stale delta. The fixture leaks this possibility on a parallel (xdist) test run.

**Fix:** Consolidate into a single atomic query that moves `ends_at` to exactly `seconds` seconds before `now()`:

```sql
UPDATE tournaments.editions
SET started_at = now() - make_interval(secs => $2) - (ends_at - started_at),
    ends_at    = now() - make_interval(secs => $2)
WHERE id = $1
RETURNING ends_at
```

---

### WR-04: Outbox reward processing runs N×M DB round-trips inside a single long transaction

**File:** `apps/api/services/tournament_outbox_service.py:133-163`

**Issue:** Inside the single `async with pool.acquire() as conn, conn.transaction()` block, the poller iterates over every `event.results` entry and calls `award_cycle_end` (which issues multiple queries: streak fetch, participant fetch, XP ledger insert for each user) and `_reset_non_participant_streaks` (which fetches all tracked users and iterates over non-participants). For a tournament with N categories and M participants, this is O(N×M) async round-trips inside one transaction. The transaction holds the `FOR UPDATE SKIP LOCKED` row locks for the entire duration.

This is not a performance-only concern: a very large participant set (hundreds of users across multiple categories) could hold the row locks long enough that the next cron tick fires another `process_edition_transitions()` call while this transaction is still open. The advisory lock in the transition function protects against double-processing, but the outbox lock is held by the poller transaction, not the cron advisory lock. On a heavily loaded server the poller transaction timeout (if any) could cause the entire batch to roll back, leaving rows unpublished and rewards not granted.

**Fix:** Consider breaking the reward side effects out of the outbox transaction into a separate post-commit step (the existing comment at line 171 says "Transaction committed: publish the deferred...XP notifications" — extend this pattern to streaks and rewards as well, with idempotency via the existing ledger), or bound the transaction to only the publish + mark step and run rewards in a separate connection.

---

### WR-05: Stale deprecated types in `__all__` with no deprecation warnings at import time

**File:** `libs/sdk/src/genjishimada_sdk/tournaments.py:20-42`

**Issue:** `TournamentCyclesStartedEvent`, `TournamentCyclesCompletedEvent`, and `TournamentCategoryLifecycleResponse` are exported in `__all__` and documented as deprecated but carry no `DeprecationWarning` at import or use time. Any new consumer code that autocompletes from `genjishimada_sdk.tournaments` will find these types and may use them, leading to subtle bugs when the combined `TournamentRolloverEvent` is the correct type. The `TournamentXpGrantEvent` in `__all__` is also exported but there is no consumer in scope — it may be a remnant.

**Fix:** Add runtime deprecation warnings to the deprecated type constructors:

```python
import warnings

class TournamentCyclesStartedEvent(Struct):
    """...(deprecated)..."""
    def __init_subclass__(cls, **kw: object) -> None:
        warnings.warn(
            "TournamentCyclesStartedEvent is deprecated; use TournamentRolloverEvent",
            DeprecationWarning, stacklevel=2,
        )
        super().__init_subclass__(**kw)
```

Or at minimum remove them from `__all__` so they do not appear in public API surface discovery.

---

## Info

### IN-01: `next_grid_boundary()` does not handle the DST gap / ambiguous-time edge case

**File:** `apps/api/migrations/0024_tournament_editions_overhaul.sql:154`

**Issue:** The function computes the boundary as:

```sql
v_candidate := (v_anchor_day + p_tod) AT TIME ZONE p_tz;
```

`AT TIME ZONE` on a local timestamp during a DST gap (e.g. 02:30 America/New_York on the spring-forward night, which does not exist) returns the pre-gap UTC equivalent without raising an error. If an admin sets `anchor_time = '02:30'` in `America/New_York`, the function silently produces a UTC instant that maps to either 01:30 or 03:30 depending on PostgreSQL's internal resolution. The test suite only covers `00:00` anchor times so this edge case has no test coverage. The comment on the column (`anchor_time`) does not warn about gap-ambiguity.

This is unlikely to cause production issues (operators would choose round-hour boundaries) but warrants a note in the column comment and ideally a validation check in `is_valid_timezone` or the service layer that rejects anchor times known to fall in DST gaps.

---

### IN-02: `create_active_cycle` in the repository still uses `now()` for bootstrap path — comment mismatch

**File:** `apps/api/repository/tournaments_repository.py:588-598`

**Issue:** `create_active_cycle()` inserts with `started_at = now()`:

```sql
INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
VALUES ($1, $2, 'active', now())
```

The docstring says "Used by the bootstrap path", but the actual bootstrap path now uses `create_cycle_for_edition()` which accepts an explicit `started_at`. The `create_active_cycle` method appears to be dead code that was not removed during the migration to the edition model. Its continued presence with `now()` is a trap for future developers who might use it thinking it is the correct bootstrap entrypoint, re-introducing the drift bug.

**Fix:** Remove `create_active_cycle()` or add a loud deprecation warning and a comment that `create_cycle_for_edition()` is the correct method.

---

### IN-03: `_on_verification_changed` handler sends `content=` on a non-LayoutView `send` — inconsistency with CV2 pattern

**File:** `apps/bot/extensions/tournaments.py:477-483`

**Issue:** The `_on_verification_changed` handler posts using `channel.send(content=..., allowed_mentions=...)` (a plain text message), while the rest of the handler uses `channel.send(view=ui.LayoutView(...), allowed_mentions=...)`. This is not wrong per se — the MEMORY.md note about `content=` applies only to `LayoutView.send` overloads — but it is an inconsistency in the pattern. If Discord enforces Components V2 exclusively in this channel in the future (e.g. if the verification channel is a dedicated thread with Components V2 enabled), plain `content=` sends will break silently.

The `_on_completion_created` handler correctly uses `send(view=TournamentVerificationView(...))` with no `content=`. The verdict notification should similarly use a `LayoutView` with a `TextDisplay` for consistency.

**Fix:** Wrap the verdict notification in a minimal `LayoutView`:

```python
view = ui.LayoutView(timeout=None)
view.add_item(ui.Container(ui.TextDisplay(message), accent_color=color))
await self.verification_channel.send(view=view, allowed_mentions=AllowedMentions(...))
```

---

_Reviewed: 2026-06-01T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
