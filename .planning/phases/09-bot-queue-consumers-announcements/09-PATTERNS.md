# Phase 9: Bot Queue Consumers & Announcements - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 6 (1 new, 5 modified)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/bot/extensions/tournaments.py` (NEW) | bot extension / handler | event-driven (queue consumer) | `apps/bot/extensions/completions.py` (`CompletionHandler`) | exact |
| `apps/bot/extensions/api_service.py` (MODIFY) | HTTP client wrapper | request-response | same file, `claim_idempotency` / `get_upvotes_from_message_id` (get-by-id) | in-file precedent |
| `apps/bot/utilities/config.py` (MODIFY) | config struct | transform (TOML→struct) | same file, `Submission` / `Updates` (`Base` structs) | in-file precedent |
| `apps/bot/configs/dev.toml` (MODIFY) | config data | static config | same file, `[channels.updates]` block | in-file precedent |
| `apps/bot/configs/prod.toml` (MODIFY) | config data | static config | same file, `[channels.updates]` block | in-file precedent |
| `apps/bot/core/genji.py` (MODIFY) | bot core wiring | request-response (property accessor) | same file, `completions` / `xp` `@property`+`@setter` pairs | in-file precedent |

## Pattern Assignments

### `apps/bot/extensions/tournaments.py` (NEW — handler, event-driven)

**Analog:** `apps/bot/extensions/completions.py` — `CompletionHandler(BaseHandler)` (lines 503-520) + `setup()` (lines 1353-1356). Base class: `apps/bot/utilities/base.py` `BaseHandler` (lines 167-222).

**Handler skeleton + channel resolution** (copy shape from `completions.py:503-520`):
```python
class CompletionHandler(BaseHandler):
    submission_channel: TextChannel
    ...
    async def _resolve_channels(self) -> None:
        submission_channel = self.bot.get_channel(self.bot.config.channels.submission.completions)
        assert isinstance(submission_channel, TextChannel)
        self.submission_channel = submission_channel
```
New code resolves ONE channel: `self.bot.get_channel(self.bot.config.channels.tournament.announcements)`.
`BaseHandler.__init__` already creates `_set_attrs_task` calling `_ensure_guild_and_channel`, which sets `self.guild` (base.py:206-208) then calls the subclass `_resolve_channels` — so `self.guild` is available for role ops without extra work.

**Queue consumer decorator** (copy from `completions.py:522-523`, add `idempotent=True`):
```python
@queue_consumer("api.completion.autoverification.failed", struct_type=FailedAutoverifyEvent)
async def _process_autoverification_failed(self, event: FailedAutoverifyEvent, _: AbstractIncomingMessage) -> None:
```
Two methods: `("api.tournament.cycle_started", struct_type=TournamentCycleStartedEvent, idempotent=True)` and `("api.tournament.cycle_completed", struct_type=TournamentCycleCompletedEvent, idempotent=True)`. Method bodies receive `(self, event, message)`.

**Idempotency — DO NOT hand-roll** (`_queue_registry.py:96-128`): the wrapper decodes the body, then if `idempotent=True` claims on `message.message_id` via `bot.api.claim_idempotency(ClaimCreateRequest(message.message_id))`, returns early if `not res.claimed`, and on handler exception calls `api.delete_claimed_idempotency(claim_data)` before re-raising. The outbox sets `message_id = "tournament:{event_type}:{cycle_id}"` — so `idempotent=True` alone gives cycle-scoped dedupe. Just set the flag.

**Role transfer primitive** (`information_pages.py:411-418` + `guild.get_role`):
```python
async def add_remove_roles(self, member: Member) -> bool:
    if self.role in member.roles:
        await member.remove_roles(self.role)
        return False
    else:
        await member.add_roles(self.role)
        return True
```
Strip-all-then-grant (D-04/D-05): `role = self.guild.get_role(category.champion_role_id)`; guard `if role is not None`; `for holder in list(role.members): await holder.remove_roles(role, reason=...); await asyncio.sleep(_ROLE_OP_DELAY)`; then if `event.winner_user_id is not None`, `winner = self.guild.get_member(event.winner_user_id)` (guard None — Pitfall 3) and `await winner.add_roles(role, reason=...)`. `_set_guild_and_role` in `information_pages.py:402-409` confirms the `guild.get_role(role_id)` + assert pattern.

**Data sourcing on receipt** (D-07):
- `category = await self.bot.api.get_tournament_category(event.category_id)` → `TournamentCategoryResponse` (`.name`, `.champion_role_id`). NEW wrapper (see below).
- `map_data = await self.bot.api.get_map(code=event.map_code)` → `MapModel` (`api_service.py:487-577`). `MapModel` (extends `MapResponse`, `utilities/maps.py:106`) carries `.difficulty`, `.map_name`, and `.map_banner: str | None` (maps.py:213). NOTE: `get_map` raises `ValueError("No maps were found.")` on miss (api_service.py:577) — let it propagate to DLQ, do not post a broken embed.

**Logging** (CLAUDE.md + `completions.py:524`): `log = getLogger(__name__)` at module level; `%s` formatting; markers `[→]/[✓]/[x]/[!]`. Existing: `log.debug("[x] [RabbitMQ] Processing failed autoverify message")`.

**`setup()` registration** (copy from `completions.py:1353-1355`):
```python
async def setup(bot: Genji) -> None:
    bot.completions = CompletionHandler(bot)
```
New: `bot.tournaments = TournamentHandler(bot)`. Attribute MUST be PUBLIC (see Shared Patterns: Handler Registration). No cog needed unless slash commands are added (out of scope — Phase 10).

---

### `apps/bot/extensions/api_service.py` (MODIFY — HTTP client, request-response)

**Analog (in-file):** get-by-id route wrappers at lines 1661-1674.

**Route + `_request` pattern** (`api_service.py:1661-1669`):
```python
def get_upvotes_from_message_id(self, message_id: int) -> Response[int]:
    """Get upvotes count."""
    r = Route("GET", "/completions/upvoting/{message_id}", message_id=message_id)
    return self._request(r, response_model=int)

def claim_idempotency(self, data: ClaimCreateRequest) -> Response[ClaimResponse]:
    """Claim an idempotency key for a queue message action."""
    r = Route("POST", "/internal/idempotency/claim")
    return self._request(r, response_model=ClaimResponse, data=data)
```
`Route` (lines 159-175) formats path params via `url.format_map`. `_request(route, response_model=...)` (lines 311-379) decodes via cached `get_decoder(response_model)`; raises `APIHTTPError` on non-2xx.

**New method to add** (D-08):
```python
def get_tournament_category(self, category_id: int) -> Response[TournamentCategoryResponse]:
    """Get a tournament category by ID."""
    r = Route("GET", "/tournaments/categories/{category_id}", category_id=category_id)
    return self._request(r, response_model=TournamentCategoryResponse)
```
Route is verified: `apps/api/routes/v3/tournaments.py:159-188` `GET /categories/{category_id:int}` → `TournamentCategoryResponse`, scope `tournaments:read` (see Open Question on bot key scope). Add SDK import to the `from genjishimada_sdk.tournaments import ...` block alongside the existing per-domain import groups (api_service.py:29-109). Note: existing wrappers are mostly **sync** methods returning `Response[T]` (a coroutine alias) — `get_map` is the `async def` exception. Match the sync-return style of the get-by-id wrappers (`get_upvotes_from_message_id`) for consistency, OR `async def` if awaiting inside; planner's call — both call `self._request` identically.

---

### `apps/bot/utilities/config.py` (MODIFY — config struct, TOML→struct transform)

**Analog (in-file):** `Submission`/`Updates` structs (lines 53-94) and `Channels` aggregator (lines 89-94).

**Existing structs** (config.py:53-94):
```python
class Updates(Base):
    announcements: int
    newsfeed: int
    ...

class Channels(Base):
    updates: Updates
    information: Information
    submission: Submission
    help: Help
    admin: AdminChannel
```
All structs subclass `Base(msgspec.Struct, forbid_unknown_fields=True)` (line 8) — TOML keys and struct fields MUST match exactly (Pitfall 4).

**Changes to add** (D-01):
```python
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

---

### `apps/bot/configs/dev.toml` + `apps/bot/configs/prod.toml` (MODIFY — config data)

**Analog (in-file):** `[channels.updates]` block.
- dev.toml:32-33 → `[channels.updates]` / `announcements = 1377808369997447254`
- prod.toml:32-33 → `[channels.updates]` / `announcements = 975820285343301674`

**Add to BOTH files** (D-01 — value = existing announcements channel ID per environment):
```toml
# dev.toml
[channels.tournament]
announcements = 1377808369997447254   # same as [channels.updates].announcements (dev)
```
```toml
# prod.toml
[channels.tournament]
announcements = 975820285343301674    # same as [channels.updates].announcements (prod)
```
Must land in the SAME change as the `Tournament` struct (Pitfall 4: `forbid_unknown_fields=True` fails startup if struct/TOML diverge).

---

### `apps/bot/core/genji.py` (MODIFY — bot core wiring, property accessor)

**Analog (in-file):** `completions`/`xp` property+setter pairs (lines 131-147) and class attr declarations (lines 43-44).

**Existing pattern** (genji.py:131-138):
```python
@property
def completions(self) -> CompletionHandler:
    """Return the CompletionHandler service."""
    return self._completions_manager

@completions.setter
def completions(self, service: CompletionHandler) -> None:
    self._completions_manager = service
```
Class-level type declaration at lines 43-44: `_completions_manager: CompletionHandler`. Import at line 11: `from extensions.completions import CompletionHandler`.

**Changes to add** (Pitfall 1 — property MUST be public so `_collect_queue_handlers` finds it):
```python
# import (mirror line 11):
from extensions.tournaments import TournamentHandler

# class attr (mirror lines 43-44):
_tournament_manager: TournamentHandler

# property pair (mirror lines 131-138):
@property
def tournaments(self) -> TournamentHandler:
    return self._tournament_manager

@tournaments.setter
def tournaments(self, service: TournamentHandler) -> None:
    self._tournament_manager = service
```

## Shared Patterns

### Handler Registration (public-attribute requirement) — CRITICAL
**Source:** `apps/bot/extensions/rabbit.py:141-165` (`_collect_queue_handlers`)
**Apply to:** `tournaments.py` `setup()` + `genji.py` property
```python
for attr_name in dir(self.bot):
    if attr_name.startswith("_"):
        continue
    instance = getattr(self.bot, attr_name, None)
    ...
    queue_name = getattr(func, "_queue_name", None)
```
`dir(self.bot)` is scanned and `_`-prefixed attrs are skipped. The `TournamentHandler` MUST be reachable via a public attr (`bot.tournaments`). Storing only under `_tournament_manager` without the public `@property` → consumers silently never register (queues fill, then DLQ). Mirror `bot.completions`.

### Queue + DLQ auto-declaration — DO NOT edit definitions.json
**Source:** `apps/bot/extensions/rabbit.py:65-104` (`_set_up_queues`)
**Apply to:** both new consumers
```python
queue = await channel.declare_queue(queue_name, durable=True, arguments={
    "x-dead-letter-exchange": "",
    "x-dead-letter-routing-key": queue_name + self._dlq_suffix,
})
await channel.declare_queue(queue_name + self._dlq_suffix, durable=True)
```
Every registered consumer's queue + its `.dlq` is declared at startup. No `infra/rabbitmq/definitions.json` edit needed for `api.tournament.cycle_started`/`cycle_completed`.

### Extension load order
**Source:** `apps/bot/extensions/__init__.py:7-9`
```python
EXTENSIONS = sorted(<modules>, key=lambda name: name != "extensions.rabbit")
```
`extensions.rabbit` sorts last so all handlers register before queue collection. `tournaments.py` is auto-discovered; no manual list edit required, and it loads before `rabbit`.

### Idempotency claim/release
**Source:** `apps/bot/extensions/_queue_registry.py:96-128`
**Apply to:** both consumers (`idempotent=True`)
```python
event = msgspec.json.decode(message.body, type=struct_type)
if not idempotent:
    await fn(self, event, message); return
...
if message.message_id:
    claim_data = ClaimCreateRequest(message.message_id)
    res = await api.claim_idempotency(claim_data)
    if not res.claimed:
        return  # duplicate
try:
    await fn(self, event, message)
except Exception:
    if claim_data is not None:
        await api.delete_claimed_idempotency(claim_data)  # release on failure
    raise
```
Cycle-scoped key is supplied by the outbox (`message_id`); do not construct a separate key.

### Mention safety (security)
**Source:** RESEARCH §449-453 (`discord.AllowedMentions`)
**Apply to:** results embed `channel.send`
Ping the winner via numeric `<@{event.winner_user_id}>` (never the free-text `standings[].name`), and pass `allowed_mentions=discord.AllowedMentions(users=[winner], everyone=False, roles=False)` to prevent `@everyone`/role-mention injection through any text field.

### SDK struct contracts (consumed — read-only, defined Phase 7)
**Source:** `libs/sdk/src/genjishimada_sdk/tournaments.py`
- `TournamentCycleStartedEvent` (lines 403-422): `cycle_id, category_id, map_id, map_code: str, map_name: str, started_at: dt.datetime, ends_at: dt.datetime`
- `TournamentCycleCompletedEvent` (lines 425-438): `cycle_id, category_id, standings: list[TournamentLeaderboardEntryResponse], winner_user_id: int | None`
- `TournamentLeaderboardEntryResponse` (lines 282-299): `rank: int, user_id: int, name: str, time: float, verified: bool, completion: bool`
- `TournamentCategoryResponse` (lines 96-120): `id, name: str, ..., champion_role_id: int | None`

## No Analog Found

None. Every file has a strong in-codebase precedent; Phase 9 introduces no new technology.

## Open Items for Planner (from RESEARCH, not pattern gaps)
- **Bot API-key scope:** `GET /tournaments/categories/{id}` requires `tournaments:read`; verify the bot key is superuser or carries the scope (RESEARCH Open Question 1). A failing fetch raises `APIHTTPError` → DLQ.
- **Workshop-code URL format** for the new-cycle embed link (RESEARCH Open Question 2 / Assumption A3) — grep existing embeds before locking `https://workshop.codes/{code}`.
- **`_ROLE_OP_DELAY`** stagger interval (~1.0s assumed; Claude's discretion).
- **Operation ordering:** role transfer first, embed send last to minimize duplicate-post window on retry (RESEARCH Pitfall 5).
- **Embed style:** classic `discord.Embed` (with `set_thumbnail(url=map_data.map_banner)`) vs Components V2 — Claude's discretion.

## Metadata

**Analog search scope:** `apps/bot/extensions/` (completions, _queue_registry, rabbit, information_pages, api_service, __init__), `apps/bot/utilities/` (config, base, maps), `apps/bot/core/genji.py`, `apps/api/routes/v3/tournaments.py`, `libs/sdk/src/genjishimada_sdk/tournaments.py`
**Files scanned:** ~12
**Pattern extraction date:** 2026-05-30
