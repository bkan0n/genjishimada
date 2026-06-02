# Domain Pitfalls

**Domain:** Recurring tournament system for Genji Parkour
**Researched:** 2026-05-29
**Confidence:** HIGH (based on direct codebase analysis, existing pattern review, and ecosystem research)

## Critical Pitfalls

Mistakes that cause rewrites, data corruption, or major production incidents.

---

### Pitfall 1: Cross-Write Violates the Speed Enforcement Trigger

**What goes wrong:** The `core.completions` table has a PostgreSQL trigger (`core.enforce_speed_rules_nonlegacy_only()`) that rejects any INSERT where the new time is not strictly faster than the user's existing best. A tournament cross-write that attempts to insert a time that happens to be slower than the user's existing best in `core.completions` will be rejected by this trigger, even though the time is legitimately the best tournament time. The trigger fires on `BEFORE INSERT OR UPDATE OF time, completion, user_id, map_id, legacy` -- there is no way to skip it short of disabling the trigger or setting `legacy = TRUE`.

**Why it happens:** The cross-write design ("insert into `core.completions` only when tournament time is strictly faster than existing best") aligns conceptually with the trigger's intent, but the trigger checks against ALL non-legacy rows including unverified/pending ones. A tournament completion that is faster than the user's verified best but slower than a pending unverified submission will be rejected. The trigger does not know about tournament context.

**Consequences:**
- Tournament cross-writes fail silently or raise `CheckViolationError` (ERRCODE `23514`)
- Users who improved their time in a tournament see no update to their global leaderboard
- If wrapped in the same transaction as the tournament completion insert, the entire tournament submission could roll back

**Prevention:**
1. Execute the cross-write as a conditional INSERT in a separate transaction from the tournament completion insert -- never bundle them.
2. Use a CTE that queries the current best verified non-legacy time first:
   ```sql
   WITH current_best AS (
       SELECT MIN(time) AS best_time
       FROM core.completions
       WHERE user_id = $1 AND map_id = $2 AND legacy = FALSE
   )
   INSERT INTO core.completions (map_id, user_id, time, ...)
   SELECT $2, $1, $3, ...
   WHERE $3 < (SELECT best_time FROM current_best)
   ```
3. Alternatively, catch `CheckViolationError` from the trigger gracefully and log it as "cross-write skipped: not faster than existing best" rather than treating it as an error.
4. Set `tournament_completion_id` FK on the resulting `core.completions` row only when the cross-write succeeds.

**Detection:** In development, test the cross-write path with a user who has an existing faster time in `core.completions`. If the trigger raises an exception, you have this bug.

**Phase relevance:** The phase that implements tournament completion submission and cross-write logic. This is the single most dangerous integration point.

---

### Pitfall 2: pg_cron Cycle Transition Cannot Trigger Discord Announcements

**What goes wrong:** The existing pg_cron pattern (used for store rotation in migration `0013`) runs a PL/pgSQL function entirely inside PostgreSQL. It has no mechanism to call the API, publish to RabbitMQ, or trigger Discord bot actions. If you schedule tournament cycle transitions the same way, the database will transition the cycle (close leaderboard, select next maps, award placements) but the bot will never know it happened -- no announcements, no champion role transfers, no XP grants.

**Why it happens:** pg_cron executes SQL functions in the database process. It cannot make HTTP calls, publish AMQP messages, or interact with external services. The existing `store.check_and_rotate()` function works because it only needs to update database rows -- no external side effects are required. Tournament cycles need external side effects (Discord announcements, role changes, XP grants).

**Consequences:**
- Cycle transitions happen silently in the database with no Discord visibility
- Champion roles are never transferred
- Placement XP is never granted
- The community sees no announcement of new tournament maps
- Admins have no idea a transition occurred unless they query the database

**Prevention:**
The cycle transition must be a two-phase operation:
1. **pg_cron triggers a lightweight DB state change:** Insert a row into a `tournaments.pending_transitions` table (or set a `transition_due` flag on the cycle record) at the scheduled time.
2. **API-side polling or bot-side polling picks up the pending transition:** Either:
   - The API has a periodic background task (Litestar's `on_app_init` or a startup background task) that polls for pending transitions, executes the full transition logic, and publishes RabbitMQ events.
   - Or (better) pg_cron calls `pg_notify('tournament_cycle_transition', cycle_id::text)` and the API listens on that NOTIFY channel via asyncpg's `add_listener`, then executes the transition.
   - Or (simplest) skip pg_cron entirely and use a bot-side `discord.ext.tasks.loop()` that polls an API endpoint like `GET /api/v3/tournaments/pending-transitions` every minute.

**Detection:** Test by scheduling a cycle transition 2 minutes in the future and verifying that Discord announcements actually appear. If only the database changes, you have this bug.

**Phase relevance:** The phase that implements automatic cycle transitions. Must be designed alongside the announcement system, not after.

---

### Pitfall 3: Race Condition During Cycle Transition Window

**What goes wrong:** During the brief window between "cycle ends" and "transition completes," users can submit completions that get assigned to the wrong cycle or to no cycle at all. If the transition process takes 5-30 seconds (querying leaderboards, calculating placements, inserting next cycle, pre-rolling maps), concurrent tournament submissions during that window can reference a cycle that is being finalized or a cycle that does not yet exist.

**Why it happens:** The transition is not atomic from the user's perspective. The database may have a `status = 'active'` cycle that is being processed for finalization. Without explicit locking, a concurrent submission INSERT can succeed against the old cycle, potentially altering placement results after they have been calculated.

**Consequences:**
- A completion submitted during transition modifies the leaderboard after placements were calculated, making the announced placements wrong
- A user gets credit for a completion on a cycle that has already ended
- XP grants for placements may be incorrect
- The "champion" role may go to the wrong user

**Prevention:**
1. Use a cycle status state machine: `pending` -> `active` -> `finalizing` -> `completed`. The submission endpoint must reject submissions when status is `finalizing` or `completed`.
2. Acquire an advisory lock during the transition:
   ```sql
   SELECT pg_try_advisory_lock(hash_of_tournament_id)
   ```
   The submission path should also attempt this lock and fail fast if held.
3. Simpler alternative: add a `submissions_close_at` timestamp that is 1-5 minutes before the actual transition time. This creates a clean cutoff visible to users.
4. Calculate placements as a snapshot query with a `WHERE inserted_at < transition_timestamp` filter, making late submissions irrelevant to the finalized results.

**Detection:** Load-test the transition by submitting completions in a tight loop while triggering a transition. Check whether any completion's `cycle_id` or placement data is inconsistent.

**Phase relevance:** Must be addressed in the same phase as cycle transition implementation. Cannot be deferred.

---

### Pitfall 4: Discord Role Transfer Rate Limiting on Champion Role

**What goes wrong:** Transferring the Champion role involves removing it from the previous champion and adding it to the new champion. If there are multiple categories (e.g., Easy/Medium and Hard/Very Hard), that is at minimum 4 role operations (2 removes + 2 adds). Discord's rate limit for role modifications is approximately 10 updates per 10 seconds per guild. If a transition also triggers XP grants (which cause rank-up role changes via the existing `_update_xp_roles_for_user` flow), the total role operations can spike well beyond the rate limit, resulting in 429 errors and potentially a temporary CloudFlare IP ban.

**Why it happens:** The existing XP handler (`apps/bot/extensions/xp.py`) already performs role edits during XP grants. Tournament transitions fire multiple XP grants (participation + placement for many users) and champion role transfers simultaneously. Each triggers independent role modification API calls to Discord with no coordination between them.

**Consequences:**
- 429 rate limit responses cascade into delayed or failed role updates
- In severe cases, Discord issues a temporary IP ban, causing the entire bot to go offline
- Champion role appears to "stick" on the old champion for minutes
- Users receive confusing role update DMs out of order

**Prevention:**
1. Serialize all role operations during a transition through a single queue. Do not fire champion role transfers in parallel with XP role changes.
2. Process role changes with explicit `asyncio.sleep(1.0)` delays between each `member.edit(roles=...)` call.
3. Use the existing pattern from `_grant_skill_rank_roles`: batch all role adds/removes for a single member into one `member.edit(roles=new_roles)` call rather than individual `add_roles`/`remove_roles` calls.
4. Defer XP grant messages (participation + placement) to a staggered schedule -- e.g., process 5 users per second rather than all at once.
5. Consider processing champion role transfers first (highest visibility), then staggering XP grants over the next 1-2 minutes.

**Detection:** Watch for 429 errors in bot logs during test transitions with more than 10 participants.

**Phase relevance:** The phase implementing cycle result announcements and champion role transfers.

---

## Moderate Pitfalls

### Pitfall 5: Map Blacklist Window Creates an Exhaustion Deadlock

**What goes wrong:** If the blacklist window (N weeks) is too large relative to the eligible map pool for a category, the random selection can find zero eligible maps. For example, if a category covers "Hard" difficulty maps and there are only 15 eligible (non-archived, non-hidden, approved) Hard maps, a 10-week blacklist window with weekly cycles means 10 maps are blacklisted at any time -- leaving only 5 to choose from. After a few more cycles, there may be 0 eligible maps.

**Why it happens:** The blacklist window is configured globally or per-category without validation against the actual pool size. Admins may set an aggressive exclusion window without realizing how small certain difficulty pools are.

**Prevention:**
1. At map selection time, validate: `eligible_count > 0`. If not, log a warning and fall back to the map with the oldest last-used date (least recently used).
2. Add an admin-facing validation endpoint that returns "pool health" metrics: total maps, currently blacklisted, eligible for next cycle.
3. Enforce a constraint: `blacklist_window * maps_per_cycle_per_category < eligible_pool_size * 0.8`. Reject configuration changes that violate this.
4. When the pool is exhausted, allow reuse of the oldest blacklisted map with a clear admin notification rather than failing silently.

**Detection:** Query the map pool for each category with the blacklist applied. If any category has fewer than 3 eligible maps, the system is at risk.

**Phase relevance:** The phase implementing map selection and blacklisting logic.

---

### Pitfall 6: tournament_completion_id FK Creates a Coupling Nightmare

**What goes wrong:** Adding a `tournament_completion_id` FK column to `core.completions` means the core completions table now depends on the tournaments schema. If the tournament system is ever removed or refactored, the FK constraint prevents dropping or restructuring `tournaments.completions`. It also means every migration touching `core.completions` must now consider the tournament FK. Existing queries that join `core.completions` with other tables gain an extra nullable column that could confuse developers or leak tournament metadata into non-tournament contexts.

**Why it happens:** The FK approach is chosen for convenience ("Set during Tournament X" badges) but creates a bidirectional dependency between what should be a subsidiary domain (tournaments) and the core domain (completions).

**Consequences:**
- Core completions queries return tournament metadata unintentionally
- Dropping/refactoring the tournament system requires a migration on the core table
- The `core.completions` trigger must be aware of the new FK column (though it currently ignores columns not in its trigger list, adding new FKs could interact with future trigger changes)

**Prevention:**
1. Use a link table instead: `tournaments.completion_links (tournament_completion_id INT, core_completion_id INT)`. This keeps the dependency one-directional (tournaments references core, never the reverse).
2. The link table approach means `core.completions` schema remains untouched -- zero risk to existing queries and triggers.
3. Badge queries ("Was this completion set during a tournament?") become a simple LEFT JOIN to the link table rather than a nullable column check.

**Detection:** Review the migration that adds the FK. If it alters `core.completions`, flag it for architectural review.

**Phase relevance:** The phase implementing the database schema (should be the first phase). Getting this wrong requires a migration to fix.

---

### Pitfall 7: Streak Tracking Across Missed Cycles Becomes Ambiguous

**What goes wrong:** The spec says "weekly participation streak maintained by submitting in at least one category per cycle." But if categories have different cycle frequencies (weekly vs. biweekly), the streak definition becomes ambiguous. Did the user "miss" a cycle if they submitted in the weekly category but not the biweekly one? What happens during weeks where the biweekly category has no active cycle?

**Why it happens:** Per-category cycle frequency creates a non-uniform timeline. A streak that spans "every cycle" cannot be defined globally when different categories cycle at different rates.

**Consequences:**
- Users lose streaks they believe they maintained because the system counted a biweekly non-submission week as a miss
- Admin confusion about what "streak" means in configuration
- Edge cases around cycle frequency changes mid-streak (e.g., admin switches category from weekly to biweekly)

**Prevention:**
1. Define the streak as: "submitted in at least one category that had an active cycle during this period." The streak checks per-cycle, not per-category.
2. Store streaks as a count + last_participated_cycle_id, not as a continuous timestamp range.
3. When evaluating whether a streak broke, only count cycles where the user was eligible to participate (i.e., cycles that actually ran).
4. Document the streak rules clearly in both code comments and user-facing descriptions.
5. Consider simplifying to a single global cycle frequency in v1 and deferring per-category frequency to a later iteration.

**Detection:** Unit test with a user who submits weekly but has a biweekly category. Verify streak continuity.

**Phase relevance:** The phase implementing XP bonuses and streaks. Can be deferred to after the core cycle mechanism works.

---

### Pitfall 8: Pre-Rolled Maps Visible to Admins Create Fairness Concerns

**What goes wrong:** If admins can see next-cycle maps before the cycle starts, and admins are also tournament participants, they gain an unfair advantage by practicing those maps ahead of time. Even with good intentions, the perception of unfairness damages community trust.

**Why it happens:** The pre-roll feature is designed for operational convenience (review/reroll inappropriate maps) but creates an information asymmetry when admins also compete.

**Consequences:**
- Community members accuse admins of insider trading on map selection
- Admin tournament wins are questioned
- Discord drama and community fragmentation

**Prevention:**
1. Track who viewed pre-rolled maps via an audit log (`tournaments.map_preview_log`).
2. Consider excluding admin users who viewed pre-rolled maps from that cycle's leaderboard (automated disqualification).
3. Alternative: limit pre-roll visibility to a dedicated "tournament moderator" role that is explicitly not a participant.
4. Display a disclaimer on tournament results if any participant had pre-roll access.
5. Simplest approach: do not show pre-rolled maps to admins at all. Allow only reroll (without seeing the current selection) and explicit override (manual map choice, which is logged and visible to the community).

**Detection:** Community feedback and Discord moderation logs. This is a social pitfall, not a technical one.

**Phase relevance:** The phase implementing admin tournament management endpoints.

---

## Minor Pitfalls

### Pitfall 9: Map Archival/Deletion During Active Tournament Cycle

**What goes wrong:** If a map that is currently the active tournament map gets archived, hidden, or deleted (via existing admin tools), the tournament cycle references a map that no longer appears in normal queries. Users attempting to submit completions for that tournament map may get "map not found" errors.

**Prevention:**
1. Add a check in the map archive/delete flow: if the map is currently active in a tournament cycle, block the operation with a clear error message.
2. Add a `core.maps` query in the tournament map selection that only selects maps with `archived = FALSE AND hidden = FALSE AND playtesting = 'Approved'`.
3. If a map must be removed urgently during an active cycle, provide an admin "replace tournament map" endpoint that swaps it and announces the change.

**Phase relevance:** The phase implementing map selection. Add the guard in the existing map archive endpoint.

---

### Pitfall 10: Idempotency Key Collisions on Tournament Events

**What goes wrong:** The existing `BaseService.publish_message()` requires idempotency keys for most queues. Tournament events need carefully scoped idempotency keys. Using something like `tournament:completion:{user_id}` without the cycle ID means a user's submission in cycle 2 could collide with their cycle 1 submission key, causing the cycle 2 message to be silently dropped.

**Prevention:**
1. Always include the cycle ID in tournament idempotency keys: `tournament:completion:{cycle_id}:{user_id}:{completion_id}`.
2. For cycle transition events: `tournament:transition:{cycle_id}`.
3. For XP grant events from tournaments: `tournament:xp:{cycle_id}:{user_id}:{xp_type}`.
4. Review which tournament queues belong in `IGNORE_IDEMPOTENCY` (in `apps/api/services/base.py`) -- tournament XP grants likely should NOT be idempotent since the same user can receive XP for different cycles.

**Phase relevance:** Every phase that publishes RabbitMQ messages for tournament events.

---

### Pitfall 11: Tier-Then-Time Ranking Logic Gets Wrong at Boundary

**What goes wrong:** The ranking system specifies "fully verified > partial; within same tier, fastest wins." But the existing verification pipeline is asynchronous -- a completion may be submitted and ranked as "unverified" and then later verified, changing its tier. If the leaderboard is computed at cycle end, a completion verified 1 second before the deadline ranks above one that was faster but verified 1 second after the deadline.

**Prevention:**
1. Define a verification cutoff: completions must be verified by cycle end to count as "verified tier." Clearly communicate this to users.
2. Alternatively, extend a grace period (e.g., 24 hours after cycle end) for pending verifications to complete before finalizing placements.
3. Consider using the auto-verify flow (OCR) to minimize the window where completions are unverified. Tournament submissions with screenshots could be prioritized in the verification queue.

**Phase relevance:** The phase implementing tournament leaderboard calculation and cycle finalization.

---

### Pitfall 12: Bot Offline During Cycle Transition

**What goes wrong:** If the bot is offline (deployment, crash, Discord outage) when a cycle transition triggers, the RabbitMQ messages for announcements/role transfers queue up. When the bot comes back online, it processes all queued messages at once -- potentially announcing stale results or transferring roles for a cycle that has already been superseded by another transition.

**Prevention:**
1. Include a `transition_timestamp` in all transition event messages. The bot handler should check: if `transition_timestamp` is more than X hours old, skip the announcement (or send an abbreviated "catch-up" announcement).
2. The existing `RabbitHandler` startup drain mechanism will process queued messages, but add a staleness check in the tournament consumer handler.
3. For champion role transfers, always query the database for the current champion rather than trusting the message payload -- the message may be stale if multiple transitions occurred while the bot was down.

**Phase relevance:** The phase implementing bot-side tournament event consumers.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Database schema design | Pitfall 6 (FK coupling) | Use link table instead of adding FK to `core.completions` |
| Tournament completion submission | Pitfall 1 (speed trigger), Pitfall 3 (race condition) | Separate transactions, catch `CheckViolationError`, cycle status state machine |
| Map selection & blacklisting | Pitfall 5 (pool exhaustion), Pitfall 9 (map archival) | Pool size validation, archive guards |
| Automatic cycle transitions | Pitfall 2 (pg_cron gap), Pitfall 3 (race window), Pitfall 12 (bot offline) | Use NOTIFY/LISTEN or bot polling, advisory locks, staleness checks |
| Champion roles & XP grants | Pitfall 4 (rate limiting), Pitfall 10 (idempotency) | Staggered role updates, cycle-scoped idempotency keys |
| Streaks & participation tracking | Pitfall 7 (ambiguous streaks) | Define streak per-cycle not per-category, or use single global frequency |
| Admin management endpoints | Pitfall 8 (fairness), Pitfall 9 (map archival) | Audit logging, role separation, archive guards |
| Leaderboard finalization | Pitfall 11 (verification timing) | Verification cutoff or grace period |
| Bot event consumers | Pitfall 12 (stale messages) | Staleness checks, database-as-source-of-truth for roles |

## Sources

- Direct codebase analysis: `apps/api/migrations/0001_init.sql` (completions table, speed trigger), `0010`, `0012`, `0017` (trigger revisions), `0013` (pg_cron store rotation pattern)
- `apps/api/services/completions_service.py` and `apps/api/repository/completions_repository.py` (cross-write integration surface)
- `apps/bot/extensions/xp.py` (role management pattern, rate limit exposure)
- `apps/bot/extensions/completions.py` (skill role batch update pattern)
- `apps/bot/extensions/rabbit.py` (message consumption, DLQ, startup drain)
- `apps/api/services/base.py` (idempotency enforcement, `IGNORE_IDEMPOTENCY` set)
- `infra/postgres/Dockerfile` (pg_cron availability)
- [Discord Rate Limit Documentation](https://discord.com/developers/docs/topics/rate-limits)
- [Discord.js role race condition issue #7879](https://github.com/discordjs/discord.js/issues/7879)
- [Discord Bot Rate Limiting Guide](https://space-node.net/blog/discord-bot-rate-limiting-guide-2026)
- [PostgreSQL Advisory Locks for concurrent task prevention](https://www.the-art-of-web.com/sql/advisory-locking/)
- [pg_cron repository](https://github.com/citusdata/pg_cron)
- [Epochtal - Portal 2 weekly speedrun competition](https://epochtal.p2r3.com/) (real-world weekly cycle tournament pattern)
- [MCSR Ranked weekly race](https://mcsrranked.com/) (weekly seed rotation precedent)
