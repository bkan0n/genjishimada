# Phase 9: Bot Queue Consumers & Announcements - Research

**Researched:** 2026-05-30
**Domain:** discord.py queue consumers, announcement embeds, champion-role transfer, RabbitMQ cycle-scoped idempotency
**Confidence:** HIGH (all integration points verified against the actual codebase; only external Discord rate-limit tuning is MEDIUM)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Bot is consumer-only.** Never writes Postgres; all data comes from RabbitMQ events or HTTP calls to the API. `[CITED: 09-CONTEXT.md §30-35]`
- **Events consumed (Phase 7 outbox), idempotency key `tournament:{event_type}:{cycle_id}`:**
  - `api.tournament.cycle_started` → `TournamentCycleStartedEvent`: `cycle_id, category_id, map_id, map_code, map_name, started_at, ends_at`.
  - `api.tournament.cycle_completed` → `TournamentCycleCompletedEvent`: `cycle_id, category_id, standings: list[TournamentLeaderboardEntryResponse], winner_user_id: int | None`. Standings entries carry `rank, user_id, name, time, verified, completion`. `[VERIFIED: libs/sdk/src/genjishimada_sdk/tournaments.py]`
- **`champion_role_id` is per-category on `tournaments.categories`** — NOT in either event. Same for category `name`, map `difficulty`, map banner. `[VERIFIED: TournamentCategoryResponse]`
- **Architecture invariants:** no ORM; single-writer (only API writes Postgres); existing Litestar + asyncpg + msgspec + RabbitMQ patterns only — no new frameworks.
- **D-01:** New bot config key `channels.tournament.announcements`, initialized to existing `channels.updates.announcements` value (dev `1377808369997447254`). Single channel for both embeds.
- **D-02 (new-cycle embed):** map name, difficulty, category name, clickable workshop-code link, `ends_at`, map thumbnail (banner). Difficulty/category-name/thumbnail are fetched (see D-07).
- **D-03 (results embed):** Top 3 + winner highlight, @mention winner, **NO "XP awarded" line** (deliberate deviation from ROADMAP success criterion 2).
- **D-04:** Strip champion role from ALL current holders, then grant to new winner (self-healing — no "last winner" tracking).
- **D-05:** `winner_user_id is None` → strip from all current holders, leave vacant.
- **D-06:** Fold champion-transfer announcement into the results embed ("crowned Champion of {category}" line). One message per cycle.
- **D-07:** Fetch missing fields from EXISTING endpoints on event receipt:
  - Category name + `champion_role_id`: `GET /api/v3/tournaments/categories/{category_id}` → `TournamentCategoryResponse`.
  - Map difficulty + thumbnail/banner: full maps endpoint by code (`get_map(code=...)` → `MapModel`/`MapResponse` with `map_banner`, `difficulty`, `map_name`). **NOT `/maps/{code}/partial`.**
- **D-08:** Add a thin APIService tournament wrapper (e.g. `get_tournament_category(category_id)`) following the existing `Route(...)` + decoder pattern.

### Claude's Discretion
- Role-op staggering mechanism/interval to avoid Discord rate limits.
- Exact cycle-scoped idempotency key construction (must match the outbox key).
- APIService method names/signatures, embed field layout/styling, handler/class names.

### Deferred Ideas (OUT OF SCOPE)
- Per-category announcement channels.
- Separate champion celebration embed / DM to winner.
- "XP awarded" line in results embed.
- Full / top-10 leaderboard in announcements (Phase 10 slash commands).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DSC-01 | Automated new-cycle announcement with map details | `TournamentCycleStartedEvent` consumer → fetch category + map → post new-cycle embed (Pattern 1, 2). `[VERIFIED]` |
| DSC-02 | Automated cycle results announcement with standings | `TournamentCycleCompletedEvent` consumer → post Top-3 results embed (Pattern 1, 3). `[VERIFIED]` |
| DSC-03 | Automated champion role transfer announcements | Same consumer as DSC-02 strips+grants `champion_role_id` and folds a "crowned Champion" line into the results embed (Pattern 4, D-06). `[VERIFIED]` |
| RWD-03 | Discord champion role per category, transferred to cycle winner | `guild.get_role(champion_role_id)` strip-all-then-grant, staggered (Pattern 4). `[VERIFIED]` |
</phase_requirements>

## Summary

Phase 9 is almost entirely an exercise in *re-using existing, verified bot infrastructure* — there is essentially no new technology, no new dependency, and no new framework. The bot already has every primitive this phase needs: a `@queue_consumer` decorator with built-in cycle-scoped idempotency, a `BaseHandler` base class with async channel resolution, an `APIService` with a `Route(...)` + cached-`msgspec`-decoder pattern and a working `get_map(code=...)`, a config system decoded from TOML into `msgspec.Struct`s, and discord.py role/embed primitives already used elsewhere in the codebase. The work is to assemble these into a new `apps/bot/extensions/tournaments.py` extension hosting a `TournamentHandler(BaseHandler)` with two consumers.

The single most important verified finding: **cycle-scoped idempotency is automatic and requires no extra construction.** The Phase-7 outbox publishes each event with `message_id=idempotency_key` where the key is `tournament:{event_type}:{cycle_id}` (`apps/api/services/tournament_outbox_service.py:136` + `apps/api/services/base.py:101`). The bot's `@queue_consumer(idempotent=True)` wrapper claims idempotency on `message.message_id` (`_queue_registry.py:107-116`) and deletes the claim on handler failure. So decorating both handlers with `idempotent=True` gives exactly the cycle-scoped dedupe the phase requires — the planner must NOT hand-roll a separate key.

The second key finding: **handler registration is by public attribute name.** `RabbitHandler._collect_queue_handlers` walks `dir(self.bot)`, skipping any attribute starting with `_`, and finds methods tagged `_queue_name` (`rabbit.py:151-163`). Therefore the `TournamentHandler` instance must be attached to the bot via a **public** property (e.g. `bot.tournaments`), exactly like `bot.completions = CompletionHandler(bot)` (`completions.py:1355`) with a `@property`/`@setter` pair on `core.Genji`. If it is attached under a `_`-prefixed name only, the consumers will silently never register.

**Primary recommendation:** Create `apps/bot/extensions/tournaments.py` with a `TournamentHandler(BaseHandler)` exposing two `@queue_consumer(..., idempotent=True)` methods; register it in `setup()` as `bot.tournaments = TournamentHandler(bot)`; add a `@property tournaments` to `core.Genji`; add a `Tournament(Base)` config struct + `[channels.tournament]` TOML block in both configs; and add a `get_tournament_category` wrapper to `APIService`. Strip-all-then-grant the champion role with a small `asyncio.sleep` between member edits.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Decode tournament events | Bot / RabbitHandler + `@queue_consumer` | — | Bot is the consumer; decoding is the decorator's job (`msgspec.json.decode`). `[VERIFIED]` |
| Cycle-scoped idempotency | Bot / `@queue_consumer(idempotent=True)` | API `public.idempotency_claims` | Claim/release runs in the bot via `bot.api.claim_idempotency`; the claim row lives in Postgres (written by the API). `[VERIFIED]` |
| Source missing embed data (category name, role id, map difficulty/banner) | API (read endpoints) | Bot (HTTP client) | Single-writer: bot must NOT read Postgres directly; it calls `GET /tournaments/categories/{id}` and `GET /maps?code=`. `[VERIFIED]` |
| Build & post embeds | Bot / `TournamentHandler` | — | Discord presentation is bot-only. `[VERIFIED]` |
| Champion role transfer | Bot / discord.py `Member.add_roles`/`remove_roles` | — | Roles are Discord state; bot owns it. API only stores `champion_role_id`. `[VERIFIED]` |
| Channel/guild resolution | Bot / `BaseHandler._resolve_channels` | TOML config | Resolved once after `wait_until_ready`, cached on the handler. `[VERIFIED]` |

## Standard Stack

This phase introduces **no new packages.** Everything is already a workspace dependency.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | git `master` (rev pinned in `apps/bot/pyproject.toml:25`) | Role add/remove, embed/LayoutView posting, guild/member access | Already the bot framework; `members=True` intent enabled (`core/genji.py:31`) so `guild.get_role`, `role.members`, `guild.get_member` all work from cache. `[VERIFIED]` |
| msgspec | `>=0.19.0` | Decode events + API responses | Already used by `@queue_consumer` and `APIService` cached decoders. `[VERIFIED]` |
| aio-pika | `>=9.5.5` | Queue declaration/consumption | `RabbitHandler` auto-declares the queue + `.dlq` on startup. `[VERIFIED]` |
| aiohttp | `>=3.12.14` | `APIService` HTTP client | Existing `Route` + `_request` machinery. `[VERIFIED]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio` (stdlib) | 3.13 | `await asyncio.sleep(...)` between role member-edits for stagger | Champion-role transfer loop only. `[VERIFIED]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `guild.get_role(id)` (cached) | `await guild.fetch_role(id)` / iterate `guild.roles` | `get_role` is O(1) cache lookup and matches the codebase's ID-based pattern (`completions.py:1159` `guild.get_role(...)`). Only fetch if cache miss is a real risk; not needed with role cache populated at startup. `[VERIFIED]` |
| `role.members` (cached enumeration of holders) | `guild.fetch_members()` async iterate | `role.members` is the cheap cached path and works because `members=True` intent is on. Use it for D-04 strip-all. `[VERIFIED]` |
| Classic `discord.Embed` | Components V2 `ui.LayoutView`/`ui.Container` | The bot already uses Components V2 LayoutViews heavily (`completions.py`, `base.py`). Either works; classic `Embed` is simpler for a one-shot announcement and supports `set_thumbnail(url=...)` directly for D-02's banner. **Recommendation: classic `discord.Embed`** for both announcements — simpler, no interactivity needed, native thumbnail support. `[ASSUMED]` (styling is explicit Claude's-discretion) |

**Installation:** None — no new dependencies.

## Package Legitimacy Audit

> Not applicable. Phase 9 installs **zero** external packages. All dependencies (discord.py, msgspec, aio-pika, aiohttp) are already present and locked in `uv.lock`. No registry verification or slopcheck needed.

## Architecture Patterns

### System Architecture Diagram

```
  Phase 7 outbox poller (API)
        │  publish_message(routing_key, data, idempotency_key="tournament:{event}:{cycle_id}")
        │  → message_id = idempotency_key   (base.py:101)
        ▼
  RabbitMQ  api.tournament.cycle_started        api.tournament.cycle_completed
        │                                             │
        ▼ (queue + .dlq auto-declared at startup, rabbit.py:84-96)
  RabbitHandler._collect_queue_handlers  ── walks dir(bot), finds @queue_consumer methods
        │   on PUBLIC bot attributes only (rabbit.py:151-163)
        ▼
  @queue_consumer(idempotent=True) wrapper (_queue_registry.py)
        │   1. skip if x-pytest-enabled header
        │   2. msgspec.json.decode(body → Event struct)
        │   3. claim_idempotency(message.message_id) → skip if already claimed
        │   4. call handler; on exception → delete claim (retry) → DLQ on repeated failure
        ▼
  TournamentHandler  (BaseHandler subclass; channel resolved in _resolve_channels)
        ├── cycle_started handler:
        │      ├─ api.get_tournament_category(category_id) → name            [NEW wrapper, D-08]
        │      ├─ api.get_map(code=event.map_code) → difficulty, map_banner  [D-07, EXISTING]
        │      └─ announce_channel.send(embed=new_cycle_embed)               [DSC-01]
        └── cycle_completed handler:
               ├─ api.get_tournament_category(category_id) → name, champion_role_id
               ├─ build Top-3 results embed (+ winner @mention, + "Champion" line)  [DSC-02/D-06]
               ├─ role = guild.get_role(champion_role_id)
               ├─ for holder in role.members: await holder.remove_roles(role); sleep [D-04/D-05]
               ├─ if winner_user_id: await winner.add_roles(role)                    [RWD-03]
               └─ announce_channel.send(embed=results_embed)                         [DSC-03]
```

### Recommended Project Structure
```
apps/bot/extensions/tournaments.py   # NEW: TournamentHandler + 2 consumers + setup()
apps/bot/extensions/api_service.py   # EDIT: add get_tournament_category wrapper
apps/bot/utilities/config.py         # EDIT: add Tournament(Base) struct + Channels.tournament field
apps/bot/configs/dev.toml            # EDIT: add [channels.tournament] announcements = <updates value>
apps/bot/configs/prod.toml           # EDIT: same
apps/bot/core/genji.py               # EDIT: add `_tournament_manager` attr + public `tournaments` property/setter
```

### Pattern 1: Channel-resolving queue-consumer handler (the template)
**What:** A `BaseHandler` subclass that resolves its channel(s) once after readiness and hosts `@queue_consumer` methods.
**When to use:** This is the exact shape `TournamentHandler` must take.
**Example:**
```python
# Source: apps/bot/extensions/completions.py:503-520 (CompletionHandler), VERIFIED
class TournamentHandler(BaseHandler):
    announcement_channel: TextChannel

    async def _resolve_channels(self) -> None:
        channel = self.bot.get_channel(self.bot.config.channels.tournament.announcements)
        assert isinstance(channel, TextChannel)
        self.announcement_channel = channel

    @queue_consumer("api.tournament.cycle_started", struct_type=TournamentCycleStartedEvent, idempotent=True)
    async def _on_cycle_started(self, event: TournamentCycleStartedEvent, _: AbstractIncomingMessage) -> None:
        ...

    @queue_consumer("api.tournament.cycle_completed", struct_type=TournamentCycleCompletedEvent, idempotent=True)
    async def _on_cycle_completed(self, event: TournamentCycleCompletedEvent, _: AbstractIncomingMessage) -> None:
        ...


async def setup(bot: Genji) -> None:
    bot.tournaments = TournamentHandler(bot)   # MUST be a PUBLIC bot attribute (see Pitfall 1)
```

### Pattern 2: Sourcing missing data on event receipt (D-07)
**What:** Fetch category name/role-id and map difficulty/banner via HTTP, since they are not in the event.
**Example:**
```python
# Source: D-07 + apps/bot/extensions/api_service.py:487 get_map (VERIFIED)
category = await self.bot.api.get_tournament_category(event.category_id)  # NEW wrapper, D-08
map_data = await self.bot.api.get_map(code=event.map_code)               # EXISTING; → map_banner, difficulty
# Do NOT use get_partial_map / /maps/{code}/partial — no banner field (D-07, user directive).
```

### Pattern 3: New `APIService.get_tournament_category` wrapper (D-08)
**What:** A thin async method mirroring the existing `Route(...)` + `_request(response_model=...)` style.
**Example:**
```python
# Source: pattern from api_service.py:1666 claim_idempotency / 937 get-by-id routes (VERIFIED)
async def get_tournament_category(self, category_id: int) -> TournamentCategoryResponse:
    r = Route("GET", "/tournaments/categories/{category_id}", category_id=category_id)
    return await self._request(r, response_model=TournamentCategoryResponse)
```
Route exists and returns `TournamentCategoryResponse` with scope `tournaments:read` (`apps/api/routes/v3/tournaments.py:160-190`). `[VERIFIED]`

### Pattern 4: Champion role strip-all-then-grant with stagger (D-04/D-05/RWD-03)
**What:** Self-healing transfer — remove role from every current holder, then grant to winner (or leave vacant).
**Example:**
```python
# Source: member.remove_roles/add_roles (information_pages.py:411-417) + guild.get_role (completions.py:1159), VERIFIED
role = self.guild.get_role(category.champion_role_id)        # int ID from TournamentCategoryResponse
if role is not None:
    for holder in list(role.members):                        # cached; members intent ON
        await holder.remove_roles(role, reason=f"Tournament {category.name} cycle {event.cycle_id} reset")
        await asyncio.sleep(_ROLE_OP_DELAY)                  # stagger (see Pitfall 2)
    if event.winner_user_id is not None:
        winner = self.guild.get_member(event.winner_user_id)
        if winner is not None:
            await winner.add_roles(role, reason=f"Champion of {category.name}, cycle {event.cycle_id}")
    # winner_user_id is None (D-05): leave vacant — nothing more to do.
```

### Anti-Patterns to Avoid
- **Constructing a separate idempotency key.** The wrapper already claims on `message.message_id`, which the outbox sets to `tournament:{event_type}:{cycle_id}`. Do not invent your own key or pass one — just set `idempotent=True`. `[VERIFIED]`
- **Attaching the handler under a private (`_`-prefixed) attribute only.** `_collect_queue_handlers` skips `_`-prefixed attrs → consumers never register. `[VERIFIED rabbit.py:152]`
- **Bot reading Postgres directly.** Forbidden by architecture; use the API. `[CITED: CLAUDE.md]`
- **Editing `definitions.json` to declare the new queues.** Not needed — `RabbitHandler._set_up_queues` declares each registered consumer's queue + DLQ at startup. `[VERIFIED rabbit.py:84-96]`
- **Using `/maps/{code}/partial`.** Partial response has no banner field (D-07 user directive). Use `get_map(code=...)`. `[CITED: 09-CONTEXT.md D-07]`
- **`get_map` raises `ValueError("No maps were found.")`** if the code isn't found — handle/let it propagate to DLQ rather than posting a broken embed (`api_service.py:577`). `[VERIFIED]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Duplicate-announcement dedupe | Custom seen-cycle set or DB flag | `@queue_consumer(idempotent=True)` (claims on `message.message_id` = the outbox key) | Already cycle-scoped, claim row in Postgres, auto-released on failure for retry. `[VERIFIED]` |
| Queue + DLQ declaration | Manual `channel.declare_queue` / `definitions.json` edit | Register the handler; `RabbitHandler` declares both at startup | Auto-declared from the `_queue_name` metadata. `[VERIFIED]` |
| 429 retry/backoff on role ops | Custom retry loop reading `Retry-After` | discord.py's built-in HTTP layer (auto-queues + waits `retry_after`) | The library handles 429s transparently; you only add a courtesy stagger. `[CITED: discord.com/developers/docs/topics/rate-limits]` |
| Channel/guild lookup | Re-resolving per event | `BaseHandler._resolve_channels` (cached after `wait_until_ready`) | Resolved once; reused for every event. `[VERIFIED]` |
| Response decoding | `json.loads` + manual struct build | `Route` + `_request(response_model=...)` cached `msgspec` decoder | Existing typed path. `[VERIFIED]` |

**Key insight:** Nearly every "hard" part of this phase already exists and is verified in the codebase. The risk is *not* missing infrastructure — it is wiring the new handler in incorrectly (public-attribute registration, config struct shape) or hand-rolling something the framework already does (idempotency, DLQ, 429 handling).

## Runtime State Inventory

This is a feature-addition phase (new extension + config + API wrapper), not a rename/refactor/migration. The Runtime State Inventory section does not apply. However, two adjacent runtime concerns are worth flagging for the planner:

| Concern | Finding | Action |
|---------|---------|--------|
| New RabbitMQ queues at runtime | `api.tournament.cycle_started`/`cycle_completed` + their `.dlq` are auto-declared by the bot at startup once the consumers register. No infra/`definitions.json` change. | None — verified `rabbit.py:84-96`. |
| Idempotency-claim rows | Each consumed event writes a claim row (`tournament:{event}:{cycle_id}`) to `public.idempotency_claims` via the API. Deleted on handler failure. | None — existing table, existing endpoints. |
| Bot API-key scope | The category/maps endpoints require `tournaments:read` / map read scopes. The bot calls the API with `X-API-KEY` (`api_service.py:185`). Could not confirm in migrations that the bot's key carries `tournaments:read` (no seed found); the codebase grants superusers a scope bypass (`migrations/0005_api_keys_perms.sql:3` `is_superuser`). | **Open Question 1** — verify the bot key is superuser or has `tournaments:read` before relying on the category fetch. |

## Common Pitfalls

### Pitfall 1: Handler registered under a private attribute → consumers silently never fire
**What goes wrong:** Both consumers decode/idempotency-wrap correctly but no messages are ever delivered; queues fill and eventually DLQ.
**Why it happens:** `_collect_queue_handlers` iterates `dir(self.bot)` and `continue`s on any `attr_name.startswith("_")` (`rabbit.py:151-152`). Existing handlers are exposed via **public** `@property` names (`bot.completions`, `bot.xp`, etc.).
**How to avoid:** In `setup()` do `bot.tournaments = TournamentHandler(bot)` and add a public `tournaments` `@property`/`@setter` pair to `core.Genji` (mirror the `completions` property at `genji.py:132-138`). Internal storage may be `_tournament_manager`, but the accessor must be public.
**Warning signs:** Startup log "Queues to consume (resolved)" does not list the two `api.tournament.*` queues.

### Pitfall 2: Bursting the per-guild member-edit rate-limit bucket on simultaneous category transitions
**What goes wrong:** When multiple categories finalize in the same poller tick (Phase-7 outbox can emit several `cycle_completed` events back-to-back), strip-all-then-grant may issue many `PATCH /guilds/{id}/members/{id}/roles/{id}` calls in a burst, tripping 429s.
**Why it happens:** `add_roles`/`remove_roles` on members in the same guild share a per-guild route bucket; Discord enforces per-route + a 50 req/s global limit. discord.py *will* auto-wait on a 429, but bursting still degrades latency and risks the global limit.
**How to avoid:** Insert a small `await asyncio.sleep(_ROLE_OP_DELAY)` between each member edit (and optionally between categories). A conservative `_ROLE_OP_DELAY` of **~1.0s** keeps well under limits for the realistically small number of category champions (1 per category, a handful of stale holders). discord.py's built-in 429 handling is the safety net; the sleep is the courtesy throttle the success criterion 4 asks for. `[CITED: discord.com/developers/docs/topics/rate-limits]` `[ASSUMED: exact interval]`
**Warning signs:** discord.py logs "We are being rate limited" / `RateLimited` warnings during cycle completion.

### Pitfall 3: `winner_user_id` / holder member not in cache
**What goes wrong:** `guild.get_member(winner_user_id)` returns `None` (member left, or not cached) and the role grant is skipped silently.
**Why it happens:** `get_member` is a cache lookup; an uncached/left member returns `None`.
**How to avoid:** Guard the `add_roles` with a `None` check (as in Pattern 4). With `members=True` intent the cache should be complete, but a member who left between submission and finalization will legitimately be absent — log `[!]` and continue (the role simply stays vacant). Do NOT crash the handler (would DLQ a valid event).
**Warning signs:** Champion role not granted despite a non-null `winner_user_id`.

### Pitfall 4: Config struct mismatch with TOML (`forbid_unknown_fields=True`)
**What goes wrong:** Adding the TOML `[channels.tournament]` block without the matching `Tournament(Base)` struct field (or vice-versa) makes `msgspec.toml.decode` raise at bot startup.
**Why it happens:** `config.py` structs subclass `Base(msgspec.Struct, forbid_unknown_fields=True)` (`config.py:8`), so TOML keys and struct fields must match exactly.
**How to avoid:** Add `class Tournament(Base): announcements: int` and `tournament: Tournament` on `Channels`, AND the `[channels.tournament]` block in BOTH `dev.toml` and `prod.toml`, in the same change.
**Warning signs:** `msgspec.ValidationError` / unknown-field error at startup.

### Pitfall 5: Posting the embed before the role transfer fails-mid-loop, or vice-versa (partial side effects on retry)
**What goes wrong:** If the handler posts the announcement, then the role grant raises and the message is re-delivered, the announcement could double-post; or roles get half-transferred.
**Why it happens:** The idempotency claim is deleted on *any* handler exception to allow retry — so a failure after a successful `channel.send` will, on retry, re-run `channel.send`.
**How to avoid:** Order operations so the *idempotent/cheap-to-retry* and *side-effect-light* work happens last, OR make the announcement post tolerant of re-runs. Practical guidance for the planner: do the **role transfer first, then post the single results embed last** so a role-op failure retries before any message is sent; a duplicate role grant/strip is naturally idempotent (re-stripping/re-granting the same role is a no-op-ish), whereas a duplicate `channel.send` is visible spam. Accept that a failure *after* the final `channel.send` will re-post on retry — keep the final send as the last statement to minimize that window. `[ASSUMED: ordering is planner's call]`

## Code Examples

### Reading a config channel ID (D-01)
```python
# Source: apps/bot/extensions/completions.py:510 (VERIFIED)
channel = self.bot.get_channel(self.bot.config.channels.tournament.announcements)
assert isinstance(channel, TextChannel)
```

### Config struct + TOML (D-01)
```python
# apps/bot/utilities/config.py  — add:
class Tournament(Base):
    announcements: int

class Channels(Base):
    updates: Updates
    information: Information
    submission: Submission
    help: Help
    admin: AdminChannel
    tournament: Tournament   # NEW
```
```toml
# apps/bot/configs/dev.toml  AND prod.toml — add (value = existing announcements channel, D-01):
[channels.tournament]
announcements = 1377808369997447254   # dev: same as [channels.updates].announcements
```

### Public property on the bot (Pitfall 1 fix)
```python
# Source: pattern from apps/bot/core/genji.py:132-138 (VERIFIED)
@property
def tournaments(self) -> TournamentHandler:
    return self._tournament_manager

@tournaments.setter
def tournaments(self, service: TournamentHandler) -> None:
    self._tournament_manager = service
```

### New-cycle embed (DSC-01 / D-02) — classic Embed with thumbnail
```python
# Source: discord.Embed API (CITED: discordpy.readthedocs.io); fields per D-02
import discord
embed = discord.Embed(
    title=f"New Tournament Cycle: {category.name}",
    description=f"**Map:** [{event.map_name}](https://workshop.codes/{event.map_code}) (`{event.map_code}`)",
    color=discord.Color.blurple(),
)
embed.add_field(name="Difficulty", value=map_data.difficulty, inline=True)
embed.add_field(name="Category", value=category.name, inline=True)
embed.add_field(name="Ends", value=discord.utils.format_dt(event.ends_at, "R"), inline=False)
if map_data.map_banner:
    embed.set_thumbnail(url=map_data.map_banner)
await self.announcement_channel.send(embed=embed)
```
> Note: confirm the actual workshop-code link format used elsewhere in the repo; `discord.utils.format_dt(..., "R")` is already used in `base.py:50`. `[VERIFIED: format_dt usage]` `[ASSUMED: workshop URL format]`

### Results embed with Top 3 + winner mention + champion line (DSC-02/03, D-03/D-06)
```python
# fields per D-03/D-06; @mention via <@user_id>
top3 = event.standings[:3]
lines = [f"`#{e.rank}` <@{e.user_id}> — {e.time:.2f}s" for e in top3]
embed = discord.Embed(title=f"{category.name} — Cycle Results", color=discord.Color.gold())
embed.add_field(name="Podium", value="\n".join(lines) or "No submissions", inline=False)
if event.winner_user_id is not None:
    embed.add_field(name="Champion", value=f"<@{event.winner_user_id}> crowned Champion of {category.name}!", inline=False)
    content = f"<@{event.winner_user_id}>"            # ping the winner (D-03)
else:
    content = None
await self.announcement_channel.send(content=content, embed=embed)   # NO "XP awarded" line (D-03)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual idempotency keys per consumer | `@queue_consumer(idempotent=True)` claims on `message.message_id` | Established codebase pattern | Phase 9 just sets the flag; outbox already sets `message_id` to the cycle-scoped key. |
| `handle_db_exceptions` decorator | Three-tier domain exception hierarchy | Per CLAUDE.md (API-side, N/A to bot) | Not relevant to this consumer-only phase. |
| classic `Embed` everywhere | Components V2 `ui.LayoutView` for interactive UIs | discord.py master | For non-interactive announcements, classic `Embed` remains valid and simpler. |

**Deprecated/outdated:** None relevant. No deprecated discord.py APIs are in scope (`add_roles`/`remove_roles`/`get_role`/`get_member` are all current and used in-repo).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `_ROLE_OP_DELAY ≈ 1.0s` is a safe stagger interval | Pitfall 2 | Too low → occasional 429 (auto-handled by discord.py, low impact); too high → slow transitions. Tunable. |
| A2 | Classic `discord.Embed` (not Components V2) is the right presentation choice | Standard Stack / Code Examples | Cosmetic only; explicitly Claude's discretion (CONTEXT). |
| A3 | Workshop-code link format is `https://workshop.codes/{code}` | New-cycle embed example | Wrong URL → dead link in embed; verify against existing repo usage before locking. |
| A4 | Role-transfer-first, embed-last ordering best balances retry safety | Pitfall 5 | Sub-optimal ordering → duplicate message on a narrow failure window; planner's call. |
| A5 | `map_data.map_banner` is non-null for tournament-eligible maps | New-cycle embed | Null banner → `set_thumbnail` guard already handles it (no thumbnail). Low risk. |

## Open Questions

1. **Does the bot's API key carry `tournaments:read` scope (or superuser bypass)?**
   - What we know: category/maps read routes require `tournaments:read` / map read scopes; the bot authenticates with `X-API-KEY`; superusers bypass scope checks (`migrations/0005`).
   - What's unclear: No migration seeds the bot key's scopes in the repo; the production key may already be superuser.
   - Recommendation: Verify the bot key is superuser or add `tournaments:read` to it before relying on `get_tournament_category`. A failing fetch will raise `APIHTTPError` and DLQ the event — surface this in a verification step.

2. **Exact workshop-code link format.**
   - What we know: `event.map_code` is the Overwatch workshop code.
   - What's unclear: whether the community links to `workshop.codes/{code}` or another host.
   - Recommendation: Grep existing embeds/newsfeed for an established code-link format; match it.

3. **Should the new-cycle handler tolerate `get_map` raising `ValueError`?**
   - What we know: `get_map(code=...)` raises `ValueError("No maps were found.")` on miss (`api_service.py:577`).
   - Recommendation: If the map is guaranteed to exist (cycle was created from a real map), letting it propagate (→ retry → DLQ alert) is acceptable; planner should decide between fail-loud vs. degraded embed.

## Environment Availability

> External dependencies are services the bot already connects to in normal operation. No new tooling.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| RabbitMQ | Event consumption | ✓ (runtime infra) | per infra | — |
| Genji API (`/tournaments/categories/{id}`, `/maps`) | D-07 data sourcing | ✓ (endpoints exist) | v3 | — |
| Discord gateway (members intent) | Role ops, guild/member cache | ✓ (`members=True`, `core/genji.py:31`) | discord.py master | — |
| `public.idempotency_claims` table + claim endpoints | Idempotent consumers | ✓ (existing) | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None (pending Open Question 1 on key scope).

## Validation Architecture

> `workflow.nyquist_validation: true` (config.json) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=8.3.5` + pytest-asyncio (auto mode) |
| Config file | `apps/api/pyproject.toml` (API tests); **bot has no dedicated pytest config in scope** |
| Quick run command | `uv run --directory apps/api pytest <path> -p no:xdist` (per MEMORY.md) |
| Full suite command | `just test-api` |

**Important constraint (MEMORY.md):** the bot package has its API tests under `apps/api/tests`; the bot itself is lightly tested. Multi-file targeted runs need `--no-testmon`. Single-file runs are fine. Paths are relative to `apps/api`.

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DSC-01 | cycle_started consumer decodes event, fetches category+map, posts embed | unit (mock `bot.api`, mock channel) | `uv run --directory apps/api pytest tests/bot/test_tournaments_handler.py -k cycle_started -p no:xdist` | ❌ Wave 0 |
| DSC-02 | cycle_completed consumer posts Top-3 results embed (no XP line) | unit | `... -k results_embed ...` | ❌ Wave 0 |
| DSC-03/RWD-03 | strip-all-then-grant champion role; vacant when winner None | unit (mock `guild.get_role`, fake `role.members`, mock member `add/remove_roles`) | `... -k champion_role ...` | ❌ Wave 0 |
| Idempotency | `@queue_consumer(idempotent=True)` skips duplicate `message_id`; releases claim on failure | unit (mock `bot.api.claim_idempotency`) | `... -k idempotency ...` | ❌ Wave 0 |
| Config | `Tournament` struct decodes `[channels.tournament]` from both TOMLs | unit | `... -k config_tournament ...` | ❌ Wave 0 |

> Note: bot consumers are normally testable via direct handler invocation with mocked `self.bot.api`, mocked `self.announcement_channel`, and a fabricated event struct — the `@queue_consumer` wrapper's pytest-header short-circuit is for the live RabbitMQ path; unit tests call the underlying logic directly. Prefer testing the handler body with injected fakes.

### Sampling Rate
- **Per task commit:** the single new test file for the task's behavior (`pytest <file> -p no:xdist`).
- **Per wave merge:** `just test-api` (full suite; watch for the two known flaky/pre-existing failures in MEMORY.md — `test_difficulty_exact_filter`, the category-filter xdist flake — these are NOT regressions).
- **Phase gate:** full suite green (modulo the documented pre-existing failures) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `apps/api/tests/bot/test_tournaments_handler.py` (or the bot's test location) — covers DSC-01/02/03, RWD-03, idempotency. Confirm where bot unit tests live; none exist for handlers yet.
- [ ] `apps/api/tests/bot/test_config_tournament.py` — TOML→struct decode for the new channel block.
- [ ] Shared fakes/fixtures: a fake guild/role/member trio and a mock `APIService` returning `TournamentCategoryResponse` + `MapModel`.
- Framework install: none — pytest already present.

## Security Domain

> `security_enforcement` not set in config.json — treat as enabled. This phase is consumer-only with no user-supplied input surface, so the ASVS footprint is narrow.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Bot↔API auth is the existing `X-API-KEY`; unchanged here. |
| V3 Session Management | no | N/A (no sessions). |
| V4 Access Control | yes (minor) | Champion-role grant uses `champion_role_id` straight from the trusted API category record — bot does not let users specify a role. Ensure the role is a *managed champion role*, never an admin/mod role (the value originates from admin-configured category data, not user input). |
| V5 Input Validation | yes | All inbound data is `msgspec`-decoded into typed structs (`@queue_consumer`) and typed API responses — strong typing is the validation. No string interpolation into SQL (bot does no SQL). |
| V6 Cryptography | no | None. |

### Known Threat Patterns for discord.py bot consumer
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mention injection via standings `name` | Spoofing/Tampering | Use `<@user_id>` (numeric ID) mentions, NOT the free-text `name`, for the winner ping (Pattern: results embed uses `event.winner_user_id`). Set `allowed_mentions` to ping only the intended user to avoid `@everyone`/role-mention abuse if any field could contain raw text. `[ASSUMED]` |
| Privileged role escalation | Elevation of Privilege | `champion_role_id` comes from admin-configured `tournaments.categories`, not from the event/user; bot never grants an arbitrary role. Verify role hierarchy (bot's top role must be above the champion role for `add_roles`/`remove_roles` to succeed). `[VERIFIED: role source]` |
| Duplicate announcements (DoS-via-spam on retry) | DoS | Cycle-scoped idempotency + order side effects last (Pitfall 5). `[VERIFIED]` |

**Recommendation:** When sending the results embed, pass `allowed_mentions=discord.AllowedMentions(users=[winner], everyone=False, roles=False)` to guarantee only the winner is pinged and no role/`@everyone` mention can be injected through any text field. `[CITED: discordpy.readthedocs.io AllowedMentions]`

## Sources

### Primary (HIGH confidence)
- `apps/bot/extensions/_queue_registry.py` — `@queue_consumer` decorator, idempotency claim on `message.message_id`, claim-release on failure.
- `apps/api/services/tournament_outbox_service.py:41-136` — `_EVENT_ROUTING`, `idempotency_key=f"tournament:{event_type}:{cycle_id}"`.
- `apps/api/services/base.py:75-101` — `message_id=idempotency_key or str(job_id)` (proves message_id == outbox key).
- `apps/bot/extensions/rabbit.py:65-96, 141-163` — startup queue+DLQ declaration; `_collect_queue_handlers` public-attr scan.
- `apps/bot/extensions/completions.py:503-520, 1353-1355` — `CompletionHandler(BaseHandler)` + `_resolve_channels` + `setup()` registration template.
- `apps/bot/utilities/base.py:167-222` — `BaseHandler` guild/channel resolution.
- `apps/bot/extensions/api_service.py:159-176, 311-379, 487-577, 1666-1671` — `Route`, `_request`, `get_map`, `claim_idempotency`.
- `apps/bot/utilities/config.py` — `Base(forbid_unknown_fields=True)`, `Channels`/`Updates` structs.
- `apps/bot/configs/dev.toml` — `[channels.updates].announcements = 1377808369997447254`.
- `apps/api/routes/v3/tournaments.py:160-190` — `GET /tournaments/categories/{id}` → `TournamentCategoryResponse`.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — event + response struct definitions.
- `apps/bot/core/genji.py:25-46, 132-165` — intents (`members=True`), public-property service pattern.

### Secondary (MEDIUM confidence)
- [Discord Rate Limits](https://discord.com/developers/docs/topics/rate-limits) — per-route buckets, 50 req/s global, `Retry-After`/`X-RateLimit-Bucket` semantics (informs stagger).
- [discord.py API Reference](https://discordpy.readthedocs.io/en/stable/api.html) — `Embed`, `Member.add_roles`/`remove_roles`, `AllowedMentions`, `utils.format_dt`.

### Tertiary (LOW confidence)
- [Discord Bot Rate Limiting Guide 2026](https://space-node.net/blog/discord-bot-rate-limiting-guide-2026) — general queueing/backoff guidance (unverified third-party; used only to corroborate that the library auto-handles 429s).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all primitives verified in-repo.
- Architecture / integration points: HIGH — every wiring step (idempotency, registration, config, APIService, role ops) traced to specific verified lines.
- Pitfalls: HIGH — derived from actual codebase mechanics (`dir(self.bot)` scan, `forbid_unknown_fields`, claim-release-on-failure).
- Rate-limit stagger interval: MEDIUM — discord.py auto-handles 429s; exact interval is a tunable assumption (A1).

**Research date:** 2026-05-30
**Valid until:** 2026-06-29 (stable internal codebase; revisit if discord.py master introduces breaking role/embed API changes).
