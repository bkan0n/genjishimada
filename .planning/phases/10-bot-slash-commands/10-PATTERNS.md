# Phase 10: Bot Slash Commands - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 5 files / 9 new-or-extended symbols
**Analogs found:** 9 / 9 (all symbols have a concrete in-repo analog)

## File Classification

| New/Modified File (symbol) | Role | Data Flow | Closest Analog | Match Quality |
|----------------------------|------|-----------|----------------|---------------|
| `apps/api/routes/v3/tournaments.py` → `get_streak` route | controller (route) | request-response (read) | `get_category` route, same file (`tournaments.py:159-188`) | exact |
| `apps/api/services/tournament_service.py` → `get_streak()` | service | CRUD (read) | `get_config()` same file (`tournament_service.py:74-81`) | exact |
| `apps/bot/extensions/api_service.py` → 6 wrappers | utility (HTTP client) | request-response | `get_tournament_category` (`api_service.py:1667-1674`) | exact |
| `apps/bot/extensions/tournaments.py` → `TournamentCommandCog` (GroupCog) | route/cog (slash commands) | request-response | `XPCog` (`xp.py:218-238`) | exact |
| `apps/bot/extensions/tournaments.py` → `/tournament-reroll` + Mod/Sensei gate | route/cog (slash command) | request-response | `ModeratorCog.edit_map` gate (`moderator.py:78-107`) | exact |
| `apps/bot/extensions/tournaments.py` → `/info` embed | component (embed builder) | transform | Phase-9 `_on_cycle_started` (`tournaments.py:84-98`) | exact (reuse) |
| `apps/bot/utilities/transformers.py` → `CategoryTransformer` | utility (transformer) | request-response | `UserTransformer` (`transformers.py:219-252`) | exact |
| `apps/bot/extensions/tournaments.py` → `TournamentLeaderboardPaginator` | component (view) | transform (in-memory paging) | `StaticPaginatorView` ctor (`paginator.py:318-340`) + `CompletionsLeaderboardPaginator.build_page_body` (`completions.py:944-965`) | role-match (rendering analog is `ApiPaginatorView`; base ctor is the structural analog) |
| `apps/bot/extensions/tournaments.py` → `setup()` extension | config (wiring) | event-driven (load) | `xp.py` `setup()` (`xp.py:241-248`) | exact |

## Pattern Assignments

### `apps/api/routes/v3/tournaments.py` — `get_streak` route (controller, request-response)

**Analog:** `get_category` (same file, `tournaments.py:159-188`) — VERIFIED present.

**Decorator + scope + path pattern** (copy verbatim, swap path/types):
```python
@litestar.get(
    path="/categories/{category_id:int}",
    summary="Get Tournament Category",
    description="Get a single tournament category by ID.",
    opt={"required_scopes": {"tournaments:read"}},
)
async def get_category(
    self,
    tournament_service: TournamentService,
    category_id: Annotated[int, Parameter(description="Category ID")],
) -> TournamentCategoryResponse:
    try:
        return await tournament_service.get_category(category_id)
    except CategoryNotFoundError as e:
        raise CustomHTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
```

**Apply to `get_streak`:** path `/streaks/{user_id:int}`, scope `{"tournaments:read"}`, return `TournamentStreakResponse`. Per RESEARCH D-04/A2 the recommended split keeps the endpoint a pure read that **404s when absent** (bot maps to zero). The service returns `None` → route raises `CustomHTTPException(HTTP_404_NOT_FOUND, ...)`. `HTTP_404_NOT_FOUND` and `CustomHTTPException` are already imported (`tournaments.py:28,49`). Add `TournamentStreakResponse` to the SDK import block (`tournaments.py:8-20`).

### `apps/api/services/tournament_service.py` — `get_streak()` (service, CRUD-read)

**Analog:** `get_config()` (same file, `tournament_service.py:74-81`) — VERIFIED present.

```python
async def get_config(self) -> TournamentConfigResponse:
    config = await self._tournament_repo.fetch_config()
    return msgspec.convert(config, TournamentConfigResponse)
```

**Apply to `get_streak(self, user_id: int) -> TournamentStreakResponse | None`:** call `self._tournament_repo.fetch_streak(user_id)` (EXISTS, `tournaments_repository.py:679`, returns `dict | None`); if `None` return `None`, else `msgspec.convert(row, TournamentStreakResponse)`. `msgspec` already imported (`tournament_service.py:9`); `self._tournament_repo` already on `__init__` (`tournament_service.py:71`). Add `TournamentStreakResponse` to the SDK import block (`tournament_service.py:11-24`).

### `apps/bot/extensions/api_service.py` — 6 new wrappers (utility, request-response)

**Analog:** `get_tournament_category` (`api_service.py:1667-1674`) — VERIFIED present.

```python
def get_tournament_category(self, category_id: int) -> Response[TournamentCategoryResponse]:
    r = Route("GET", "/tournaments/categories/{category_id}", category_id=category_id)
    return self._request(r, response_model=TournamentCategoryResponse)
```

**Key conventions to copy (confirmed against neighbours `api_service.py:1642-1699`):**
- Methods are **sync `def`** returning `self._request(...)` — NOT `async def` (caller awaits the returned coroutine). E.g. `force_deny_playtest` (`api_service.py:1652`).
- Path placeholders passed as **kwargs** to `Route(...)` (`thread_id=thread_id`); `Route` runs `url.format_map`.
- Body via `data=`, response shape via `response_model=`. Mutations with a body use `data=...` (e.g. `approve_playtest`, `api_service.py:1642-1645`).

**Wrappers to add (signatures per RESEARCH Pattern 2):**
| Wrapper | Method + path | response_model |
|---------|---------------|----------------|
| `get_tournament_streak(user_id)` | `GET /tournaments/streaks/{user_id}` | `TournamentStreakResponse` |
| `list_tournament_categories()` | `GET /tournaments/categories` | `list[TournamentCategoryResponse]` |
| `list_tournament_cycles(*, status, category_id, limit, offset)` | `GET /tournaments/cycles` (filters via `params=`) | `TournamentCycleListResponse` |
| `get_tournament_leaderboard(cycle_id)` | `GET /tournaments/cycles/{cycle_id}/leaderboard` | `list[TournamentLeaderboardEntryResponse]` |
| `reroll_next_cycle(category_id)` | `POST /tournaments/categories/{category_id}/reroll` | `TournamentNextCycleResponse` |
| `choose_next_cycle(category_id, data)` | `PATCH /tournaments/categories/{category_id}/next-cycle` (`data=`) | `TournamentNextCycleResponse` |

**Query-param pitfall:** filters (`status`, `category_id`, `limit`, `offset`) go through `params={...}`, NOT the path. `_request` already skips `None` params and flattens lists — see `get_maps` (`api_service.py:398`). Verify exact reroll/choose-map HTTP verbs against the live controller before finalizing (RESEARCH lists `POST` for reroll, `PATCH` for next-cycle; CONTEXT D-15 once says `POST` for next-cycle — controller is authoritative).

### `apps/bot/extensions/tournaments.py` — `TournamentCommandCog` `/tournament` group (cog, request-response)

**Analog:** `XPCog` (`xp.py:218-238`) — VERIFIED present.

```python
@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
class XPCog(commands.GroupCog, group_name="xp"):
    def __init__(self, bot: core.Genji) -> None:
        self.bot = bot

    @app_commands.command(name="grant")
    async def _command_grant_xp(
        self, itx: GenjiItx,
        user: app_commands.Transform[int, transformers.UserTransformer],
        amount: app_commands.Range[int, 1],
        reason: str | None = None,
    ) -> None:
        ...
        await itx.response.send_message(..., ephemeral=True)
```

**Apply:** `class TournamentCommandCog(commands.GroupCog, group_name="tournament")` decorated with `@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID","0")))`. Three `@app_commands.command` subcommands: `info(category: Transform[int, CategoryTransformer])`, `leaderboard(category: ...)`, `streak()` (no args — self-only, D-02). First line of every command body: `await itx.response.defer(ephemeral=True)` (D-10) — matches `moderator.py:90`. `streak` passes `itx.user.id` to `api.get_tournament_streak(...)`; map 404/`None` → zero display (D-04).

### `apps/bot/extensions/tournaments.py` — `/tournament-reroll` flat command + Mod/Sensei gate (cog, request-response)

**Analog:** `ModeratorCog.edit_map` (`moderator.py:78-107`) — VERIFIED present (the authoritative gate pattern).

```python
await itx.response.defer(ephemeral=True)
assert isinstance(itx.user, discord.Member) and itx.guild
is_mod = (
    itx.user.get_role(itx.client.config.roles.admin.mod) is not None
    or itx.user.get_role(itx.client.config.roles.admin.sensei) is not None
)
if not is_mod:
    raise UserFacingError("This command is for moderators only. Use `/suggest-edit` instead.")
```

**Plus the `CodeAllTransformer` arg** (`moderator.py:82`): `code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer]`.

**Apply:** a **flat top-level** `@app_commands.command(name="tournament-reroll")` (NOT under the group — D-06) `@app_commands.guilds(...)`, optionally `@app_commands.default_permissions(manage_guild=True)` as a UI hint (A1 — NOT the security boundary). Args: required `category: Transform[int, CategoryTransformer]`, optional `code: Transform[OverwatchCode, transformers.CodeAllTransformer] | None = None`. Copy the inline gate verbatim (the gate is authoritative because the bot holds one full-scope API key — Pitfall 4 / V4). Dispatch: `code is None` → `api.reroll_next_cycle(category)` (D-14); else `api.choose_next_cycle(category, TournamentChooseMapRequest(...))` (D-15). Reply shows the returned `TournamentNextCycleResponse` map.

### `apps/bot/extensions/tournaments.py` — `/tournament info` embed (component, reuse)

**Analog:** `TournamentHandler._on_cycle_started` (`tournaments.py:84-98`) — VERIFIED present. Reuse this exact builder shape:

```python
embed = discord.Embed(title=f"New Tournament Cycle: {category.name}", description=(...), color=discord.Color.blurple())
embed.add_field(name="Difficulty", value=str(map_data.difficulty), inline=True)
embed.add_field(name="Category", value=category.name, inline=True)
embed.add_field(name="Ends", value=discord.utils.format_dt(event.ends_at, "R"), inline=False)
if map_data.map_banner:
    embed.set_thumbnail(url=map_data.map_banner)
```

**Apply (D-11/D-12):** same field layout. Source map metadata via `api.get_map(code=...)` → `MapModel` (`.difficulty`, `.map_name`, `.map_banner`) — same path Phase-9 uses; do NOT use `/partial`. Time field renders **relative + absolute**: `f"{format_dt(ends_at,'R')} ({format_dt(ends_at,'F')})"` (Phase-9 only used `'R'`; this phase adds `'F'`). The `_WORKSHOP_URL.format(code=...)` link constant already exists in the module. **Open Question 1 (carry into planning):** the active-cycle `list_cycles` response (`TournamentCycleWithWinnerResponse`) has NO `ends_at`; compute `ends_at = started_at + category.cycle_frequency` locally (category is already fetched) OR add a server field — planner decision, NOT blocking.

### `apps/bot/utilities/transformers.py` — `CategoryTransformer` (utility)

**Analog:** `UserTransformer` (`transformers.py:219-252`) — VERIFIED present. Same two-method shape (`transform` + `autocomplete`):

```python
class UserTransformer(app_commands.Transformer):
    async def transform(self, itx: GenjiItx, value: str) -> int:
        if value.isdigit():
            return int(value)
        else:
            autocompleted_value = await self.autocomplete(itx, value)
            if autocompleted_value:
                return int(autocompleted_value[0].value)
        raise ValueError("This shouldn't happen?")

    async def autocomplete(self, itx: GenjiItx, current: str) -> list[app_commands.Choice[str]]:
        users = await itx.client.api.get_autocomplete_users(current)
        return [app_commands.Choice(name=names[:100], value=str(user_id)) for user_id, names in users]
```

**Apply (D-09):** `autocomplete` calls `itx.client.api.list_tournament_categories()`, filters by casefold substring, returns `Choice(name=c.name, value=str(c.id))` sliced `[:25]` (Discord hard limit — Pitfall 3). `transform` returns the resolved `category_id: int` (digit fast-path, else name→id lookup; raise `UserFacingError` on miss). Note: existing transformers call the API per keystroke without caching — consistent (A4).

### `apps/bot/extensions/tournaments.py` — `TournamentLeaderboardPaginator` (component / view)

**Structural analog (ctor):** `StaticPaginatorView` (`paginator.py:318-340`) — VERIFIED. **Rendering analog (`build_page_body`, `page_size=10`, `empty_message`):** `CompletionsLeaderboardPaginator` (`completions.py:915-965`) — VERIFIED, but note it extends `ApiPaginatorView` (uses a `fetch_func`), whereas D-13 leans **`StaticPaginatorView`** (full list already returned by the endpoint).

```python
# StaticPaginatorView ctor builds pages immediately — NO await view.initialize() step:
super().__init__(title, data, page_size=page_size)  # paginator.py:338-340 calls rebuild_data + rebuild_components
```
```python
# build_page_body rendering shape (from completions.py:944) — adapt to leaderboard entries:
def build_page_body(self) -> Sequence[ui.Item]:
    lines = [f"`#{e.rank}` <@{e.user_id}> — {e.time:.2f}s" for e in self.get_current_page_data()]
    return [ui.TextDisplay("\n".join(lines))]
```

**Apply (D-13):** `class TournamentLeaderboardPaginator(StaticPaginatorView[TournamentLeaderboardEntryResponse])`, `page_size=10`. Render `<@user_id>` numeric mentions (matches Phase-9 results embed `tournaments.py:134`; avoids name-injection ping risk — Security V5; OQ2 — `name` also available). **CRITICAL (Pitfall 1):** never pass an empty list to the static paginator (zero pages → modulo-by-zero on navigate). In the `leaderboard` command, fetch entries, and `if not entries:` send the D-16 friendly message ("No submissions yet — be the first!") and return BEFORE constructing the view. Usage after build: `await itx.edit_original_response(view=view); view.original_interaction = itx` (matches `moderator.py:106-107`).

### `apps/bot/extensions/tournaments.py` — `setup()` extension wiring (config)

**Analog:** `xp.py` `setup()` (`xp.py:241-248`) — VERIFIED present. Existing tournaments `setup()` (`tournaments.py:231-233`) only assigns `bot.tournaments`.

```python
# xp.py:247-248 — handler attr AND add_cog are SEPARATE lines:
bot.xp = XPHandler(bot)
await bot.add_cog(XPCog(bot))
```

**Apply (Pitfall 7):** extend the existing `setup()` — KEEP `bot.tournaments = TournamentHandler(bot)` and ADD `await bot.add_cog(TournamentCommandCog(bot))` as a separate line (the cog is added, never assigned over `bot.tournaments`). Staying in `tournaments.py` keeps the cog inside the `EXTENSIONS` sort that loads everything before `rabbit.py` (auto-enforced, `extensions/__init__.py`).

## Shared Patterns

### Ephemeral defer-first (all four commands)
**Source:** `moderator.py:90`, `map_search.py:360`
**Apply to:** every slash command in this phase
```python
await itx.response.defer(ephemeral=True)   # FIRST line — locks ephemerality (D-10, Pitfall 2)
```
Follow-ups use `itx.edit_original_response(...)` / `itx.followup.send(...)`.

### Bot-side authorization gate (reroll only)
**Source:** `moderator.py:92-99`
**Apply to:** `/tournament-reroll`
The bot holds one full-scope API key, so API scope (`tournaments:write`) does NOT restrict the Discord audience. The inline `itx.user.get_role(config.roles.admin.mod / .sensei)` check raising `UserFacingError` is the authoritative gate (D-07 / V4 / Pitfall 4). `config.roles.admin.mod` & `.sensei` are `int` fields on the `Admin` config struct (`config.py:38-40`).

### APIService wrapper convention
**Source:** `api_service.py:1642-1699`
**Apply to:** all 6 new wrappers
Sync `def` returning `self._request(...)`; path ids as `Route(...)` kwargs; body via `data=`; response via `response_model=`; query filters via `params=` (auto-skips `None`).

### Error handling (API side)
**Source:** `tournaments.py:182-188` (`get_category`), `tournament_service.py` translation layer; CLAUDE.md three-tier hierarchy
**Apply to:** `get_streak` route — translate the absent case to `CustomHTTPException(HTTP_404_NOT_FOUND, ...)`; let unexpected DB errors propagate to global handlers. msgspec validates request/response structs automatically.

### User-facing errors (bot side)
**Source:** `apps/bot/utilities/errors.py` `UserFacingError`, used `moderator.py:99`
**Apply to:** admin gate failure, unknown category in `CategoryTransformer.transform`, and (optionally) friendly empty-state copy (D-16: no active cycle / empty leaderboard / no pending reroll).

## No Analog Found

None. Every new symbol maps to a verified in-repo analog. The single structural caveat: the leaderboard rendering analog (`CompletionsLeaderboardPaginator`) is an `ApiPaginatorView` while the recommended base is `StaticPaginatorView` — both are in-repo; the planner composes the `StaticPaginatorView` ctor (`paginator.py:318`) with the `build_page_body` rendering shape (`completions.py:944`).

## Metadata

**Analog search scope:** `apps/api/routes/v3/tournaments.py`, `apps/api/services/tournament_service.py`, `apps/bot/extensions/{tournaments,api_service,moderator,xp,completions}.py`, `apps/bot/utilities/{transformers,paginator}.py`
**Files scanned (read this session):** 8
**Pattern extraction date:** 2026-05-30
**Open items for planner:** (1) `ends_at` source for `/info` active cycle — compute locally vs server field (RESEARCH OQ1, not blocking); (2) reroll/next-cycle HTTP verbs — confirm against live controller; (3) leaderboard `<@id>` vs `name` rendering (OQ2, minor).
