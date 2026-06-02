---
phase: 08-rewards-engine
reviewed: 2026-05-30T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - apps/api/migrations/0022_tournament_xp_grants.sql
  - apps/api/repository/tournaments_repository.py
  - apps/api/routes/v3/tournaments.py
  - apps/api/services/lootbox_service.py
  - apps/api/services/tournament_outbox_service.py
  - apps/api/services/tournament_reward_service.py
  - apps/api/services/tournament_service.py
  - libs/sdk/src/genjishimada_sdk/xp.py
findings:
  critical: 0
  warning: 6
  info: 4
  total: 10
  critical_resolved: 2
status: criticals_resolved
resolution_commit: be9f28d
---

# Phase 8: Code Review Report

**Reviewed:** 2026-05-30
**Depth:** standard
**Files Reviewed:** 8
**Status:** criticals_resolved (both BLOCKERs fixed in commit `be9f28d`)

> **Resolution (2026-05-30, commit `be9f28d`):**
> - **CR-02 resolved** — `LootboxService.grant_xp` now accepts a `pending_events` collector and DEFERS the `api.xp.grant` publish; `TournamentRewardService.award_participation`/`award_cycle_end` return the deferred events, and both call sites (`submit_completion`, `publish_pending_transitions`) publish via `publish_xp_events` only AFTER their transaction commits. No notification is sent for XP a rollback would erase. Idempotent `api.tournament.*` events keep their existing publish-before-mark contract.
> - **CR-01 resolved** — documented the `place == rank` (1-based) contract per decision A3 and added a warning when configured placement tiers match zero standings (surfaces a misconfigured `categories.placement_xp` instead of silently paying nothing).
> The 6 WARNING / 4 INFO findings below remain open as advisory follow-ups (none block the phase). Full API suite green (1676 passed) after the fix.

## Summary

Phase 8 wires tournament XP rewards (participation, placement, streak) into the existing
lootbox XP engine, guarded by a new `tournaments.xp_grants` ledger. The ledger-claim-then-grant
design is sound, and `conn` is threaded correctly through almost every repository call, so the
ledger claim and the `lootbox.xp` write genuinely share one transaction.

Two issues rise to BLOCKER. The most important is a **placement key mismatch**: the SDK
`PlacementXpTier` carries a `place` field but the standings entries are keyed by `rank`, and the
lookup dict is built on `place` then queried with `entry.rank`. Whether placement XP is ever paid
hinges entirely on whether `place` values stored in `placement_xp` happen to equal 1-based ranks —
the names diverge and nothing enforces it, so a config author who fills `place` with anything but
contiguous ranks (or who reasonably expects `place` to be a 0-based or label value) silently gets
zero placement payouts. The second BLOCKER is the **dual-write ordering inside `grant_xp`**: the
`XpGrantEvent` is published to RabbitMQ *before* the enclosing transaction commits, so a rollback
after publish tells the bot a user gained XP that was never persisted.

The remaining findings concern unbounded/negative grant amounts, a transaction-scope gap in
`_reset_non_participant_streaks`'s placement of work after publish, dynamic SQL identifier
interpolation in config/category updates, and several robustness gaps around ties and empty
standings.

## Structural Findings (fallow)

No structural pre-pass payload was supplied with this review.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Placement XP keyed on `place` but looked up by `rank` — payouts can silently vanish

**File:** `apps/api/services/tournament_reward_service.py:178-191`
**Issue:**
```python
placement_tiers = msgspec.convert(category["placement_xp"], list[PlacementXpTier])
placement_by_place = {tier.place: tier.xp for tier in placement_tiers}
for entry in event.standings:
    xp = placement_by_place.get(entry.rank)
```
The dict is built from `PlacementXpTier.place` (SDK field at `tournaments.py:46`) and queried with
`TournamentLeaderboardEntryResponse.rank` (SDK field at `tournaments.py:294`). The leaderboard's
`rank` is produced by `RANK() OVER (...)` (`tournaments_repository.py:1042`), which is 1-based and
**skips numbers after ties** (1,1,3,...). Placement XP is therefore only paid when an admin's stored
`place` values exactly coincide with these gap-containing SQL ranks. Nothing validates that
`place` is a 1-based rank, the field name implies a placement label rather than a leaderboard rank,
and there is no test asserting the two vocabularies are interchangeable. The realistic failure mode
is a configured tournament that finalizes and pays **no placement XP at all**, with no error — an
economic-correctness defect in the core feature of this phase.
**Fix:** Make the contract explicit. Either rename `PlacementXpTier.place` to `rank` and document
that it must match leaderboard ranks, or normalize in the service. Recommended — assign payouts by
sorted standing position rather than trusting two field names to align, and decide tie behavior
deliberately (see WR-05):
```python
placement_tiers = msgspec.convert(category["placement_xp"], list[PlacementXpTier])
placement_by_rank = {tier.place: tier.xp for tier in placement_tiers}  # place == leaderboard rank
# Add a regression test: a tie at rank 1 (ranks 1,1,3) pays both rank-1 entries
# and correctly skips/keys rank 2 vs 3 per the intended tie policy.
```

### CR-02: `XpGrantEvent` published before the enclosing transaction commits (dual-write rollback gap)

**File:** `apps/api/services/lootbox_service.py:415-443`, `apps/api/services/tournament_reward_service.py:104-111`
**Issue:** `grant_xp` performs the `lootbox.xp` upsert on the caller's `conn` (good), then calls
`self.publish_message(...)` **inside the still-open transaction**. `publish_message`
(`services/base.py:90-108`) publishes to RabbitMQ immediately. Because the participation path runs
inside `submit_completion`'s `conn.transaction()` (`tournament_service.py:497`) and the
placement/streak paths run inside the outbox `conn.transaction()`
(`tournament_outbox_service.py:105`), any rollback **after** the publish (e.g. a later
`advance_streak` FK error, a `cross_write_to_core` failure, or the outbox `mark_transition_published`
failing) leaves the bot having received an `XpGrantEvent` carrying `new_amount` for XP that was
rolled back and never persisted. The ledger row that was supposed to guard the grant is also rolled
back, so the next replay re-claims and re-publishes — double-notifying. The docstring claims the
publish "degrades gracefully," but it does not address rollback-after-publish, which is the actual
economic hazard. This is the classic transactional-outbox inversion: the side-effecting publish must
not precede commit.
**Fix:** Do not publish from within the grant transaction. Defer the event. Either (a) write the
`XpGrantEvent` to a transactional outbox row in the same `conn` and let the existing poller publish
it after commit, or (b) collect events in the caller and publish them only after
`conn.transaction()` exits successfully. Minimal version:
```python
# grant_xp: do the ledger claim + lootbox.xp write on conn, RETURN the event,
# and let the caller publish AFTER the transaction block commits.
# Never call publish_message while conn's transaction is open.
```

## Warnings

### WR-01: XP grant `amount` is unbounded and unsigned-unchecked — negative/overflow grants possible

**File:** `apps/api/migrations/0022_tournament_xp_grants.sql:22`, `apps/api/services/tournament_reward_service.py:141-148,184-191,210-217`
**Issue:** `amount int NOT NULL` has no `CHECK (amount > 0)`. `participation_xp`, `placement_xp[].xp`,
and `streak_xp[].xp` flow straight from admin-supplied category config into the grant with no
validation. A negative `xp` value silently subtracts XP (the `upsert_user_xp` add is unchecked), and
a value near `int` bounds can overflow `floor($2 * $3)::bigint` after the multiplier. For an economic
ledger this should be constrained.
**Fix:** Add `CHECK (amount > 0)` to `tournaments.xp_grants` and validate `xp >= 0` (and a sane upper
bound) on `PlacementXpTier`/`StreakXpTier`/`participation_xp` at the SDK or service layer.

### WR-02: `update_config` / `update_category` interpolate column names directly into SQL

**File:** `apps/api/repository/tournaments_repository.py:74-78, 215-225`
**Issue:** Both build `set_clauses.append(f"{field} = ${idx}")` from `updates.keys()`. Values use
positional params (safe), but the **column identifiers are f-string-interpolated**. Today the keys
come from a fixed allowlist in the service layer, so this is not currently exploitable, but it
violates the project's "never use f-string interpolation in SQL" convention and is one careless
caller away from injection. The pattern is fragile because the safety lives in a different file than
the query.
**Fix:** Validate `field` against an explicit allowlist set inside the repository method before
interpolating, e.g. `if field not in _ALLOWED_CONFIG_COLUMNS: raise ...`, so the repository does not
trust its caller.

### WR-03: Non-participant streak reset sweep runs unbounded inside the outbox transaction

**File:** `apps/api/services/tournament_outbox_service.py:117, 130-157`
**Issue:** `_reset_non_participant_streaks` iterates **every tracked user** (`fetch_all_streak_user_ids`
has no WHERE clause by design) and issues one `advance_streak` UPDATE per non-participant, all inside
the single outbox `conn.transaction()` that also holds `FOR UPDATE SKIP LOCKED` locks on the
pending-transition rows and performs the publishes. As the streak roster grows this transaction holds
row locks and an open transaction for an unbounded number of round-trips, and any single
`advance_streak` failure rolls back the entire batch (including already-granted ledger claims for the
cycle), forcing a full replay. There is also a correctness subtlety: this sweep stamps
`last_cycle_id = cycle_id` for non-participants of *this* category's cycle, but a user who is a
participant in a *different* category finalizing in the same poll batch could be reset here before
their own category's `award_cycle_end` advances them — ordering within the batch is creation-time,
not category-aware.
**Fix:** Confirm the cross-category ordering is safe (the `last_cycle_id IS DISTINCT FROM` guard
helps only within one category's cycle_id). Consider batching the reset in a single set-based UPDATE
(`UPDATE ... WHERE user_id <> ALL($participants)`) instead of a Python loop, and/or moving the sweep
out of the publish transaction so a reset failure does not roll back successful grants.

### WR-04: `claim_xp_grant` FK violation aborts the whole outbox/submit transaction

**File:** `apps/api/repository/tournaments_repository.py:874-879`, `apps/api/services/tournament_reward_service.py:88-94`
**Issue:** `claim_xp_grant` inserts into `tournaments.xp_grants` which FK-references `core.users(id)`.
If a standings entry or participant references a `user_id` that no longer exists in `core.users`
(deleted account between cycle snapshot and finalization), the insert raises `RepoFKError`, which
propagates out of `award_cycle_end` and aborts the entire outbox transaction — blocking *all* other
users' placement/streak grants for that cycle and forcing perpetual replay failure on every poll.
**Fix:** Decide the policy for a missing user explicitly: either skip that user's grant
(catch `RepoFKError` per-entry and continue) or ensure standings cannot contain deleted users. A
single bad entry should not poison the whole cycle's rewards.

### WR-05: Tie handling at placement is undefined / under-tested

**File:** `apps/api/services/tournament_reward_service.py:180-191`
**Issue:** With `RANK()` producing `1,1,3,...` on a tie, two rank-1 entries both receive the rank-1
payout (intended per the docstring), but the rank-2 tier is then **never paid to anyone** because no
entry has rank 2. Whether the prize pool "skips" the consumed rank is a deliberate economic policy,
but there is no comment or test pinning it down, and combined with CR-01's key mismatch the actual
behavior is unverified.
**Fix:** Add a docstring note and an integration test for the tie case (e.g. ranks `1,1,3` with a
3-tier `place` config) asserting exactly which users are paid which amounts.

### WR-06: `participation_xp` truthiness check rejects a legitimately configured 0 but also any falsy DB value

**File:** `apps/api/services/tournament_reward_service.py:137-139`, `tournament_reward_service.py:207-208`
**Issue:** `if not participation_xp: return` and `if not bonus: continue` treat `0` as "no reward,"
which is the intended no-op, but the same idiom silently swallows the case where the value arrives as
`None` (e.g. a NULL column or a missing dict key) — masking a config/data bug as a silent skip rather
than surfacing it. `placement` uses `if not xp: continue` likewise. For an economic path, distinguish
"configured zero" from "missing."
**Fix:** Use explicit comparisons: `if participation_xp is None or participation_xp <= 0: return` and
similarly for `bonus`/`xp`, logging a warning when a tier value is unexpectedly `None`.

## Info

### IN-01: `grant_user_xp` / request-path `grant_xp` still acquire no connection, so publish-before-commit (CR-02) is moot there but the helper is dual-purpose

**File:** `apps/api/services/lootbox_service.py:445-464`
**Issue:** `grant_user_xp` calls `grant_xp` with no `conn`, so `upsert_user_xp` autocommits and the
subsequent publish is post-commit — safe. The same `grant_xp` body is unsafe only when a `conn` is
passed (tournament paths). The mixed contract makes CR-02 easy to miss.
**Fix:** Once CR-02 is fixed (defer publish), document that `grant_xp` never publishes within a
caller transaction, removing the foot-gun.

### IN-02: f-string in `log.warning` violates `%s`-style logging convention

**File:** `apps/api/services/lootbox_service.py:368`
**Issue:** `log.warning(f"No reward found for rarity={rarity}, key_type={key_type}")` uses an f-string;
CLAUDE.md mandates `%s`-style (`log.warning("No reward found for rarity=%s, key_type=%s", rarity, key_type)`).
(Pre-existing in this file but in a reviewed region.)
**Fix:** `log.warning("No reward found for rarity=%s, key_type=%s", rarity, key_type)`.

### IN-03: `amount` parameter `type: XP_TYPES` shadows builtin `type`

**File:** `apps/api/services/lootbox_service.py:389`
**Issue:** Parameter named `type` (suppressed with `# noqa: A002`). Acknowledged via noqa, but it
forces the awkward `type=type` call sites and reduces readability.
**Fix:** Consider `xp_type: XP_TYPES` for new code; non-blocking given the existing suppression.

### IN-04: `_reset_non_participant_streaks` `conn` typed as `object`

**File:** `apps/api/services/tournament_outbox_service.py:134`
**Issue:** The helper types `conn: object` and every repo call needs `# type: ignore[arg-type]`,
defeating the type checker on a transaction-critical path. The other services type it as
`Connection`.
**Fix:** Type as `asyncpg.Connection` under `TYPE_CHECKING` for consistency and to drop the ignores.

---

_Reviewed: 2026-05-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
