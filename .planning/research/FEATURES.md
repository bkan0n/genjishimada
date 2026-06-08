# Feature Landscape

**Domain:** Recurring tournament/competition system for a parkour speedrun community
**Researched:** 2026-05-29
**Confidence:** HIGH (strong PROJECT.md spec + established codebase patterns + domain research)

## Table Stakes

Features users expect. Missing = competition feels broken or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Automatic cycle transitions | A recurring tournament that requires manual reset every week is not recurring -- it is admin-dependent. Players expect the new round to start on time without human intervention. | Med | pg_cron precedent exists in store rotation and quest rotation. Same pattern: hourly check, advisory lock, `check_and_transition()` function. |
| Random map selection per category | The core promise: fresh challenge each cycle. Without random selection, it becomes admin curation (different product). | Med | Draw from maps matching category difficulty filter, exclude blacklisted (recently used). Weighted RNG not needed -- uniform random from eligible pool is fine for this use case. |
| Map blacklist / cooldown window | Without this, players see the same map two weeks in a row and engagement tanks. Every major map rotation system (Valorant, CS2, PUBG) enforces cooldown on recent selections. | Low | Configurable N-weeks exclusion window. Store `last_used_at` per map in tournament context. Simple `WHERE last_used_at < now() - interval` filter. |
| Per-cycle leaderboard | The entire point of competing. Players need to see standings during and after each cycle. Must show rank, player, time, verification tier. | Med | Separate `tournaments.completions` table, ranked by tier-then-time. Query is straightforward: `ORDER BY verification_tier DESC, time ASC`. |
| Completion submission with tier-then-time ranking | Fully verified runs must beat partially verified runs regardless of time. This incentivizes proper verification and is a stated requirement. Without it, partial-proof submissions with fast times dominate unfairly. | Med | New column or enum for verification tier in tournament completions. Ranking: `(tier DESC, time ASC)`. Cross-write to `core.completions` only when tournament time strictly beats existing best. |
| Cross-write to core completions | Tournament runs should count toward career stats when they represent personal bests. Without this, players feel tournament effort is "wasted" if it doesn't update their main profile. | Med | Atomic: insert tournament completion + conditionally insert/update core completion in same transaction. Must preserve "latest = fastest" invariant. The `tournament_completion_id` FK enables metadata linking. |
| Flat participation XP bonus | Rewarding showing up is table stakes for recurring engagement. Every successful recurring system (Duolingo streaks, daily login rewards, weekly challenges) rewards participation independently of placement. | Low | Fixed XP amount on first submission per cycle. Uses existing `api.xp.grant` queue. |
| Placement-based XP bonuses | Top finishers expect reward differentiation. Admin-configurable tiers (1st, 2nd-3rd, 4th-10th, etc.) with XP amounts. | Low | Awarded at cycle transition. Config stored in tournament settings. Batch XP grants via existing queue. |
| Discord champion role per category | Visible recognition is the primary social reward. A transferable role that the current winner holds until dethroned is standard for recurring competitions (seen in TournamentBot, custom Discord communities). | Med | Bot removes role from previous holder, assigns to new winner at cycle transition. One role per category. Handle edge cases: user left server, tie-breaking. |
| Discord announcements (new cycle + results) | Players need to know when a new map drops and who won the previous cycle. Without announcements, the tournament is invisible. | Med | RabbitMQ events: `api.tournament.cycle_started`, `api.tournament.cycle_completed`. Bot consumes and posts rich embeds to announcement channel. Follows existing newsfeed pattern. |
| Admin configuration endpoints | Admins need to set up categories, cycle frequency, XP amounts, and view/reroll upcoming maps via the API. | Med | CRUD for tournament config, categories, and cycle management. Admin-scoped endpoints under `/api/v3/tournaments/admin/`. |
| Pre-rolled next-cycle maps with reroll | Admins must be able to preview what is coming next and swap maps if the random selection picked something unsuitable (broken map, too recently played informally, etc.). | Low | Generate next maps at cycle transition time. Admin GET to view, POST to reroll specific category. Simple: delete + re-randomize from eligible pool. |
| Category-based difficulty grouping | Different skill levels need different competition brackets. Grouping Easy/Medium together and Hard/Very Hard together (or any admin-defined split) prevents beginners from competing against experts. | Low | Admin defines categories as lists of `DifficultyTop` values. Maps filtered by difficulty match. Existing `DIFFICULTY_RANGES_TOP` in SDK provides the foundation. |
| Per-category cycle frequency | Different brackets may need different cadences. Easy/Medium might run weekly while Hard/Very Hard runs biweekly because harder maps take longer to optimize. | Low | `cycle_frequency` field per category: `weekly` or `biweekly`. Transition function checks each category independently. |
| Tournament history / archive | Players want to see past results, their placement history, and previous winners. Without this, the tournament has no memory. | Low | All cycle data is naturally retained in the database. Query endpoint: `GET /api/v3/tournaments/cycles` with pagination, filter by category. |

## Differentiators

Features that set this tournament apart. Not expected, but increase engagement significantly.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Weekly participation streak | Streak mechanics increase retention by ~34% (Duolingo data). Players maintain streaks by submitting in at least one category per cycle. Creates loss aversion -- missing one week breaks the streak. | Med | Track per-user: `current_streak`, `longest_streak`, `last_participated_cycle_id`. Increment at cycle transition if user has any submission. Reset to 0 if they missed. |
| Streak-based XP bonuses | Multiplying engagement rewards with consistency rewards compounds retention. 5-week streak = bonus XP is a powerful hook. | Low | Configurable thresholds: `[(streak_length, bonus_xp)]`. Awarded at cycle transition alongside placement XP. Depends on streak tracking. |
| "Set during Tournament X" badges on core completions | When a player's personal best was set during a tournament, it shows in their career profile. Social proof that tournaments produce elite runs. | Low | The `tournament_completion_id` FK on `core.completions` enables this. Display logic in existing completion response -- add optional tournament metadata field. |
| Tournament-specific Discord thread per cycle | Each cycle gets a dedicated Discord thread where participants can discuss strategies, share clips, and celebrate. Builds micro-community around each cycle. | Med | Bot creates thread in tournament channel at cycle start. Pins leaderboard message and updates it periodically or on submission. |
| Live leaderboard updates in Discord | As players submit runs, the leaderboard embed in Discord updates (or a new message posts showing the lead change). Creates excitement and urgency. | High | Requires bot to consume `api.tournament.submission` events and edit/post leaderboard messages. Throttling needed to avoid Discord rate limits. Consider updating on a schedule (every 5-10 min) rather than per-submission. |
| Personal best tracking within tournament context | Show players their improvement across tournaments: "Your time on Hard maps has improved 12% over 8 weeks." Progress visualization. | Med | Aggregate query across `tournaments.completions` for a user. API endpoint for personal tournament stats. |
| Category-specific all-time records | Track who holds the fastest-ever tournament run per category. Separate from per-cycle leaderboard -- this is the "hall of fame." | Low | Materialized view or query: `MIN(time) GROUP BY category` across all cycles with `verification_tier = 'full'`. |
| Configurable announcement channel per category | Different categories post to different channels, so Easy/Medium updates go to a casual channel while Hard/VH go to a competitive channel. | Low | `announcement_channel_id` field per category config. Bot reads from category config when posting. |
| Countdown to cycle end | Display remaining time until the current cycle closes. Creates urgency for last-minute submissions. | Low | Computed from `cycle_end_at` timestamp. Discord embed field or bot command `/tournament time-left`. No persistent state needed. |

## Anti-Features

Features to explicitly NOT build. These waste effort, add complexity, or actively harm the product.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Seasons / time-boxed tournaments | Adds massive complexity (season leaderboards, season rewards, season transitions). The core value is a perpetual cycle, not episodic content. Seasons can be added later if the perpetual cycle proves engagement. | Run perpetual cycles. If seasonal analysis is wanted later, it is a read-only reporting layer over existing cycle data. |
| Manual/admin-triggered cycle transitions | Creates single point of failure (admin forgets, is busy, is asleep). Destroys the "recurring" promise. Every cron-based rotation in this codebase (store, quests) is automatic for this reason. | pg_cron automatic transitions only. Admin can configure schedule, not trigger transitions. |
| Mid-cycle category changes | Changing rules while a competition is in progress is unfair and confusing. Players submitted runs under one ruleset; changing it invalidates their effort. | Lock category configuration during active cycles. Allow changes only between cycles. |
| Bracket/elimination format | This is a time-trial competition, not a head-to-head bracket tournament. Bracket formats are for 1v1 games. Applying them here adds complexity with zero value. | Use leaderboard-based ranking (tier-then-time). Everyone competes against the clock, not each other directly. |
| ELO / skill rating system | Over-engineering for a community parkour competition. ELO is designed for 1v1 matchmaking with uncertain outcomes. In time trials, the outcome is deterministic (faster = better). ELO adds nothing. | Use placement history and streak data for "skill" signals. Raw times and rankings tell the full story. |
| Multiple simultaneous tournaments | Running parallel tournaments splits community attention and complicates everything (which leaderboard? which champion role?). One tournament with multiple categories is the right model. | Single tournament system with multiple difficulty categories. Categories provide the segmentation. |
| Custom tournament creation by users | Turns a curated competitive experience into a chaotic free-for-all. Community members creating random tournaments dilutes the official competition and fragments engagement. | Admin-only tournament configuration. Community members participate, not organize. |
| Real-time anti-cheat / run validation | The existing verification pipeline handles proof validation. Building tournament-specific anti-cheat is a rabbit hole with diminishing returns for a community of trust. | Use existing verification flow. Tier-then-time ranking already incentivizes full verification. |
| Mobile/web UI for tournament management | API + Discord bot is the established pattern. Building a separate management UI is scope creep that delays the core feature. | Admin manages via API endpoints and Discord slash commands. Web UI can come later as a frontend project. |
| Notification spam (every submission, every leaderboard change) | Bombarding users with notifications on every submission kills engagement through fatigue. | Announce cycle start, cycle results, and champion changes only. Optional: weekly digest of standings. |
| Map voting by players | Epochtal uses community voting for map selection, but this adds significant complexity and creates popularity bias (same "fun" maps get voted in repeatedly). Random selection is simpler and ensures variety. | Random selection from eligible pool. Admin reroll covers the edge case of unsuitable picks. |

## Feature Dependencies

```
Category Configuration --> Map Selection (maps selected per category)
Map Selection --> Cycle Transition (next maps must exist before transition)
Cycle Transition --> Leaderboard Finalization (standings frozen at transition)
Cycle Transition --> Placement XP Awards (requires final standings)
Cycle Transition --> Champion Role Transfer (requires final standings)
Cycle Transition --> Discord Announcements (results + new maps)
Cycle Transition --> Streak Tracking (check participation, update streaks)

Completion Submission --> Per-Cycle Leaderboard (submissions populate standings)
Completion Submission --> Cross-Write to Core (conditional insert on submission)
Completion Submission --> Participation XP (first submission triggers XP)

Tournament Config (admin) --> Category Configuration
Category Configuration --> Per-Category Cycle Frequency

Streak Tracking --> Streak XP Bonuses (streak length determines bonus)

Pre-rolled Maps --> Admin Reroll (admin can swap pre-rolled maps)

tournament_completion_id FK --> "Set during Tournament" Badges (metadata linking)
```

**Critical path:** Tournament Config --> Categories --> Map Selection --> Cycle Transition --> Leaderboard + Announcements. Everything else hangs off this spine.

## MVP Recommendation

**Phase 1 -- Core Loop (must work end-to-end):**
1. Tournament and category configuration (admin API)
2. Map selection with blacklist/cooldown
3. Completion submission with tier-then-time ranking
4. Per-cycle leaderboard
5. Automatic cycle transitions via pg_cron

**Phase 2 -- Rewards and Recognition:**
1. Cross-write to core completions
2. Participation XP and placement XP
3. Champion role transfer
4. Discord announcements (cycle start + results)

**Phase 3 -- Engagement and Polish:**
1. Streak tracking and streak XP bonuses
2. Pre-rolled maps with admin reroll
3. Tournament history/archive endpoint
4. "Set during Tournament" badge metadata

**Defer indefinitely:**
- Seasons/time-boxed tournaments: Add only if perpetual cycle proves insufficient
- Live leaderboard updates in Discord: Nice-to-have, high complexity for marginal engagement lift
- Personal tournament stats/trends: Reporting layer, not core functionality

## Sources

- Epochtal (epochtal.p2r3.com) -- Weekly Portal 2 speedrun competition with community-driven map curation
- StriveCloud gaming community tournament software analysis
- Duolingo gamification case study -- streak retention data (14% boost at day 14, 34% overall retention increase)
- Valorant/CS2/PUBG map rotation and cooldown systems
- Existing Genji codebase: store rotation (pg_cron + advisory locks), quest rotation, completion submission pipeline, XP grant system, newsfeed announcements
- Discord tournament bot ecosystem (TournamentBot, Tourney Bot, BattleBot)
