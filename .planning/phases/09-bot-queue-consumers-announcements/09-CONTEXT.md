# Phase 9: Bot Queue Consumers & Announcements - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

<domain>
## Phase Boundary

The Discord bot reacts to the tournament lifecycle events the API already publishes
(Phase 7 outbox → `api.tournament.cycle_started` / `api.tournament.cycle_completed`).
On those events it:
1. Posts a **new-cycle announcement embed** (DSC-01),
2. Posts a **cycle-results embed** with final standings (DSC-02), and
3. **Transfers the per-category Champion Discord role** from prior holder(s) to the new
   winner, announcing the transfer (DSC-03 / RWD-03), with role operations staggered to
   respect Discord rate limits.

**In scope:** two bot queue consumers, two announcement embeds (new-cycle + results),
champion role transfer logic, the bot config + APIService wiring needed to support them,
cycle-scoped idempotency on the consumers.

**Out of scope (later phases):** Discord slash commands (Phase 10), any DB writes from the
bot (architecturally forbidden), changes to how/when the API publishes the events (Phase 7
owns the outbox — this phase only *consumes*). XP grant delivery is already handled by the
existing `api.xp.grant` consumer (Phase 8 produces those grants); this phase does not touch
XP delivery.

</domain>

## Carrying Forward from Earlier Phases (locked — do not revisit)

- **Bot is consumer-only.** Never writes Postgres; all data comes from RabbitMQ events or
  HTTP calls to the API. Channels/roles resolve from the TOML config via a `BaseHandler`
  subclass (`_resolve_channels`). Consumers register with `@queue_consumer(...)`, which
  auto-declares the queue + its `.dlq` on startup (no `definitions.json` change needed).
- **Events the API publishes (Phase 7 outbox), idempotency key `tournament:{event_type}:{cycle_id}`:**
  - `api.tournament.cycle_started` → `TournamentCycleStartedEvent`:
    `cycle_id, category_id, map_id, map_code, map_name, started_at, ends_at`.
  - `api.tournament.cycle_completed` → `TournamentCycleCompletedEvent`:
    `cycle_id, category_id, standings: list[TournamentLeaderboardEntryResponse], winner_user_id: int | None`.
    `standings` entries carry `rank, user_id, name, time, verified, completion`.
- **`champion_role_id` is per-category on `tournaments.categories` (DB)** — NOT in either
  event. Same for category `name`, map `difficulty`, and map banner/thumbnail.
- **Architecture invariants:** no ORM; single-writer (only API writes Postgres); existing
  Litestar + asyncpg + msgspec + RabbitMQ patterns only — no new frameworks.

<decisions>
## Implementation Decisions

### Announcement channel routing
- **D-01:** Add a **dedicated tournament-announcement channel config key** to the bot config
  (new struct field + TOML entry, e.g. `channels.tournament.announcements`), but
  **initialize its value to the existing general-announcements channel ID**
  (`channels.updates.announcements`) for now. This gives a repointable knob — a future
  dedicated channel needs only a config change, no code change. Both the new-cycle embed and
  the results embed post to this single channel (not per-category).

### Embed content & format
- **D-02 (new-cycle embed):** Rich embed including **map name, difficulty, category name, a
  clickable workshop-code link, the cycle end time (`ends_at`), and a map thumbnail image**
  (the map banner). Difficulty + category name + thumbnail are NOT in the event and must be
  fetched (see D-06/D-07).
- **D-03 (results embed):** Show **Top 3 standings + winner highlight** (not top-10 / not
  full — keeps the embed compact and within Discord limits; full leaderboard is a Phase-10
  slash command concern). **@mention/ping the winner.** **No "XP awarded" line** — XP amounts
  are delivered as separate `api.xp.grant` events (Phase 8) and are not in the
  `cycle_completed` event; the user explicitly chose to omit XP from the announcement.
  (NOTE: ROADMAP success criterion 2 lists "XP awarded" — this is a deliberate deviation;
  planner/verifier should treat the XP line as intentionally out.)

### Champion role transfer behavior (DSC-03 / RWD-03)
- **D-04 (previous holder):** **Strip the category's champion role from ALL current holders**
  (query the guild for every member who has that role and remove it), then grant it to the
  new winner. Self-healing — tolerates manual role edits, multiple stale holders, and missed
  prior transfers. No need to track "last winner" explicitly.
- **D-05 (no winner):** When `winner_user_id is None` (cycle completed with no submissions):
  **strip the role from all current holders and leave it vacant** (grant to no one). Fresh
  slate each cycle; the role sits empty until next cycle has a winner.
- **D-06 (champion announcement):** **Fold the champion-transfer announcement into the
  results embed** — add a "crowned Champion of {category}" line/field rather than posting a
  separate champion embed or DMing the winner. One message per cycle satisfies DSC-03.

### Sourcing missing embed data
- **D-07:** The bot **fetches missing fields from EXISTING API endpoints on event receipt**
  (consumer-only pattern preserved — no event-struct extension, no Phase-7 outbox changes):
  - **Category name + `champion_role_id`:** `GET /api/v3/tournaments/categories/{category_id}`
    → `TournamentCategoryResponse` (already exposes `name` and `champion_role_id`).
  - **Map difficulty + thumbnail/banner:** **use the full maps endpoint by code** —
    `GET /api/v3/maps?code={map_code}` (the `get_map(code=...)` APIService wrapper →
    `MapResponse`, which carries `difficulty`, `map_name`, `category`, and
    **`map_banner`** as the thumbnail). **Do NOT use `/maps/{code}/partial`** — the partial
    response has no banner/image field. (User directive.)
- **D-08:** The bot's `APIService` currently has **no tournament methods** — Phase 9 adds the
  thin wrapper(s) needed (e.g. a `get_tournament_category(category_id)` method) following the
  existing `Route(...)` + decoder pattern in `apps/bot/extensions/api_service.py`.

### Claude's Discretion (defer to research/planning)
- **Role-op staggering** (success criterion 4): exact mechanism/interval for staggering
  `add_roles`/`remove_roles` across simultaneous category transitions to avoid rate limits
  (e.g. `asyncio.sleep` between ops) — implementation detail.
- **Idempotency** (success criterion 5): consumers use `@queue_consumer(idempotent=True)`
  with a cycle-scoped claim key consistent with the outbox key
  `tournament:{event_type}:{cycle_id}` — exact key construction is planner's call.
- Exact APIService method names/signatures, embed field layout/styling, and handler/class
  names.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` §212-225 — Phase 9 goal + 5 success criteria (authoritative scope).
  NOTE the deliberate deviation on criterion 2 ("XP awarded") per D-03.
- `.planning/REQUIREMENTS.md` — DSC-01, DSC-02, DSC-03, RWD-03 (the four requirements this
  phase covers).

### Events consumed (contract — produced by Phase 7, do not modify here)
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — `TournamentCycleStartedEvent`,
  `TournamentCycleCompletedEvent`, `TournamentLeaderboardEntryResponse`,
  `TournamentCategoryResponse` (has `name`, `champion_role_id`), `MapCategory`/difficulty types.
- `apps/api/services/tournament_outbox_service.py` — `_EVENT_ROUTING` maps
  `cycle_started`→`api.tournament.cycle_started`, `cycle_completed`→`api.tournament.cycle_completed`;
  publishes with idempotency key `tournament:{event_type}:{cycle_id}`. Confirms the queue
  names + key Phase 9 must match for cycle-scoped idempotency.

### Bot consumer / announcement / role patterns (closest analogs — read first)
- `apps/bot/extensions/_queue_registry.py` — `@queue_consumer(queue, struct_type=..., idempotent=...)`
  decorator; idempotent path uses `bot.api.claim_idempotency` and deletes the claim on failure.
- `apps/bot/extensions/rabbit.py` §85-96 — startup queue + DLQ declaration; how registered
  consumers' queues get declared (no `definitions.json` edit required).
- `apps/bot/extensions/completions.py` §503-520 — `CompletionHandler(BaseHandler)` +
  `_resolve_channels()`: the template for a channel-resolving handler that consumes queues
  and posts embeds. Also shows reading channel IDs from `self.bot.config.channels.*`.
- `apps/bot/extensions/information_pages.py` §413-417 — `member.add_roles` / `member.remove_roles`
  usage (role add/remove primitive for the champion transfer).
- `apps/bot/extensions/events.py` §75-121 — role lookup via `discord.utils.get(guild.roles, ...)`
  and add patterns.

### Config (must extend)
- `apps/bot/utilities/config.py` — `Channels`/`Updates` structs; add the new
  `channels.tournament.announcements` field (D-01).
- `apps/bot/configs/dev.toml` + `apps/bot/configs/prod.toml` — add the new channel entry,
  initialized to the existing announcements channel ID (D-01).

### API endpoints the bot will call (D-07)
- `apps/api/routes/v3/tournaments.py` §160-190 — `GET /tournaments/categories/{category_id}`
  → `TournamentCategoryResponse` (category name + `champion_role_id`).
- `apps/bot/extensions/api_service.py` §397-465 (`get_maps`) / §487-575 (`get_map`) — full
  maps fetch by `code` → `MapResponse` (`difficulty`, `map_name`, `map_banner`). USE THIS,
  not `get_partial_map`/`/partial` (§710-719). Add tournament-category wrapper here (D-08).
- `libs/sdk/src/genjishimada_sdk/maps.py` §397+ — `MapResponse` fields incl. `map_banner`
  (thumbnail source), `difficulty`, `category`.

### Prior phase context
- `.planning/phases/07-automatic-cycle-transitions/07-CONTEXT.md` — D-08/D-09/D-11 (outbox
  payload shapes, at-least-once delivery, "downstream cycle-scoped idempotency handles
  duplicates" — this is that downstream).
- `.planning/phases/08-rewards-engine/08-CONTEXT.md` — XP grants flow via `api.xp.grant`
  (why XP is not in `cycle_completed`, informing D-03).

### Conventions
- `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/INTEGRATIONS.md` — queue
  consumer conventions, `%s`-style logging with `[→]/[✓]/[x]/[!]` markers, msgspec structs,
  BaseHandler channel-resolution pattern.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CompletionHandler(BaseHandler)` (`completions.py`) — copy-adapt for a
  `TournamentHandler` that resolves the announcement channel + guild and hosts the two
  `@queue_consumer` methods.
- `@queue_consumer` decorator (`_queue_registry.py`) — register both consumers; use
  `idempotent=True` for cycle-scoped dedupe.
- `member.add_roles` / `member.remove_roles` + `discord.utils.get(guild.roles, id=...)` —
  champion role transfer primitives.
- `APIService.get_map(code=...)` (→ `MapResponse` with `map_banner`/`difficulty`) for map
  metadata; add a `get_tournament_category(category_id)` wrapper for category name +
  `champion_role_id`.

### Established Patterns
- Consumers auto-declare their queue + `.dlq` on startup via `rabbit.py` — no
  `definitions.json` change.
- Channel/role IDs come from TOML config decoded into `Config` msgspec structs; handlers
  cache resolved channels in `_resolve_channels`.
- Idempotent consumers claim via `bot.api.claim_idempotency` and release the claim on
  handler failure to allow retry.
- Logging uses `log = getLogger(__name__)`, `%s` formatting, `[→]/[✓]/[x]/[!]` markers.

### Integration Points
- New bot extension (e.g. `apps/bot/extensions/tournaments.py`) with a `TournamentHandler`
  + two queue consumers. Must load before `rabbit.py` (enforced by `EXTENSIONS` sort).
- `apps/bot/utilities/config.py` + both TOML configs — new tournament announcement channel.
- `apps/bot/extensions/api_service.py` — new tournament-category fetch wrapper.

</code_context>

<specifics>
## Specific Ideas

- **User directive:** Use the **full maps endpoint by code** (`get_map(code=...)` →
  `MapResponse`, includes `map_banner` thumbnail) for map info — explicitly **NOT** the
  `/maps/{code}/partial` endpoint.
- **User directive:** Channel config should be a **dedicated tournament setting** but point
  to the **general announcements channel value** for now.
- New-cycle embed should be visually rich (thumbnail included); results embed kept compact
  (podium-style top 3) and pings the winner.

</specifics>

<deferred>
## Deferred Ideas

- **Per-category announcement channels** — considered for D-01; deferred in favor of a single
  repointable channel key. Revisit if categories need separate channels later.
- **Separate champion celebration embed / DM to the new champion** — considered for D-06;
  folded into the results embed instead. A standalone champion post or winner DM could be a
  future enhancement.
- **"XP awarded" in the results embed** — explicitly dropped (D-03); would require sourcing
  XP amounts (separate `api.xp.grant` events or an extended event). Revisit only if a future
  requirement needs it.
- **Full / top-10 leaderboard in announcements** — Phase 10 slash commands cover detailed
  leaderboard viewing.

None of these block Phase 9 — discussion stayed within the consumer/announcement scope.

</deferred>

---

*Phase: 9-Bot Queue Consumers & Announcements*
*Context gathered: 2026-05-30*
