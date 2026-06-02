# Phase 10: Bot Slash Commands - Research

**Researched:** 2026-05-30
**Domain:** discord.py app_commands (slash commands, autocomplete, paginators) + one new Litestar GET endpoint, all on existing infrastructure
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Add a player-readable `GET` streak endpoint in THIS phase. `fetch_streak(user_id)` (`tournaments_repository.py:679`) and `TournamentStreakResponse` (`sdk/tournaments.py:380`) already exist — only a `TournamentService` method, a route handler, and a bot `APIService` wrapper are missing. Endpoint shape (e.g. `GET /tournaments/streaks/{user_id}`) is the planner's call; must require `tournaments:read`.
- **D-02:** Self-only. `/tournament streak` resolves the streak for the **invoking Discord user** (bot passes that id). No "look up another user" arg.
- **D-03:** Show **current_streak AND max_streak** (both on the struct).
- **D-04 (no streak record):** Treat as zero — show current 0 / max 0 with an encouraging line ("Submit in a cycle to start your streak!"), NOT an error.
- **D-05:** Player commands live under a single `/tournament` group (`info`, `leaderboard`, `streak`) — `app_commands.Group` / `GroupCog` scoped to the guild.
- **D-06:** Admin reroll is a SEPARATE flat top-level command `/tournament-reroll` — NOT a subcommand. Rationale: `default_member_permissions` applies at top-level command/group, so you cannot cleanly mix open player subcommands and a locked admin subcommand in one group. `/tournament-reroll` gets restricted `default_permissions` PLUS an inline role check.
- **D-07 (admin gate):** Reroll gated to **Mod OR Sensei** via inline role check (`itx.user.get_role(config.roles.admin.mod)` / `...admin.sensei`), raising `UserFacingError` on failure — the `moderator.py` pattern. Bot calls API with its own key, so this gate MUST be enforced bot-side (API scope alone won't restrict it).
- **D-08:** `info`, `leaderboard`, `reroll` each take a REQUIRED `category` argument. `streak` takes no category (self-only).
- **D-09:** The `category` arg uses dynamic autocomplete backed by the API's `list_categories` (`GET /tournaments/categories`) — categories are admin-created at runtime, so static `Choice` lists won't work.
- **D-10:** ALL command responses are ephemeral. Defer ephemerally at the start of each command.
- **D-11:** Reuse the Phase-9 `TournamentHandler` embed styling. `/tournament info` is a full rich card mirroring the Phase-9 new-cycle embed: map name, clickable workshop-code link, difficulty, category name, map thumbnail, time remaining.
- **D-12 (time remaining):** Render as relative + absolute Discord timestamps — `<t:{ends_at}:R>` together with `<t:{ends_at}:F>`. Auto-updating, localized per viewer, no custom duration formatting.
- **D-13 (leaderboard + paginator):** Paginate using the project's custom paginator (`utilities/paginator.py`) — NOT discord-ext-menus (explicit directive). Page size 10. Closest analog is `CompletionsLeaderboardPaginator` (`completions.py:915`). NOTE: `GET /cycles/{cycle_id}/leaderboard` returns the FULL list with no pagination params — so the lower-friction fit is `StaticPaginatorView` (in-memory). Planner may instead add page params + use `ApiPaginatorView`; either acceptable — leaning `StaticPaginatorView`.
- **D-14:** `/tournament-reroll` defaults to a random reroll (calls `POST /tournaments/categories/{category_id}/reroll`); reply shows the newly-selected map. No confirmation step.
- **D-15:** Optional explicit-map arg. `/tournament-reroll` takes an optional Overwatch `code` to explicitly choose a map — uses the choose-map endpoint (`PATCH /tournaments/categories/{category_id}/next-cycle`, the `choose_map` handler). `code` uses `transformers.CodeAllTransformer`.
- **D-16:** Friendly ephemeral messages for each empty/missing case (not bare generic errors): no active cycle ("No active cycle for {category} right now."), empty leaderboard ("No submissions yet — be the first!"), no streak record (see D-04), no pending next-cycle map to reroll ("No pending next-cycle map to reroll.").

### Claude's Discretion
- Exact API streak-endpoint path/signature (D-01) and the `APIService` wrapper names.
- `StaticPaginatorView` vs `ApiPaginatorView` for the leaderboard (D-13) — lean `StaticPaginatorView`.
- Whether the new slash-command Cog lives in the existing `apps/bot/extensions/tournaments.py` (extend `setup` to also add the command cog) or a sibling module — leaning "same file"; must still load before `rabbit.py` (auto-enforced by `EXTENSIONS` sort).
- Embed field layout/styling specifics, exact copy strings, autocomplete result limits.

### Deferred Ideas (OUT OF SCOPE)
- Command-name variants (`/tournament current`, `/tournament lb`, `/tournament-admin`).
- Streak lookup for other users (`user` arg).
- Live submission count on `/info`.
- Past-cycle / history browsing via slash command.
- Confirmation step before reroll.
- Autocomplete of eligible maps for the reroll code arg (use `CodeAllTransformer` instead).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADM-03 | Admin Discord slash commands for tournament actions | Satisfied by `/tournament-reroll` (D-06/07/14/15) using the existing `moderator.py` Mod/Sensei inline-gate pattern + `CodeAllTransformer`, calling existing `reroll_map` and `choose_map` API endpoints via new `APIService` wrappers. Roadmap criteria 1-3 (`/tournament info`, `leaderboard`, `streak`) are additional success criteria beyond ADM-03 and are covered by the new streak endpoint + autocomplete + paginator findings below. |
</phase_requirements>

## Summary

This phase is almost entirely **integration glue on top of fully-built infrastructure**. There are no new frameworks, no new packages, and no external dependencies. Every API endpoint the four commands call already exists (`list_categories`, `list_cycles`, `get_leaderboard`, `reroll_map`, `choose_map`) EXCEPT one player-readable streak GET, whose repository method (`fetch_streak`) and SDK struct (`TournamentStreakResponse`) already exist — only a `TournamentService.get_streak()` method, a controller route, and a bot `APIService` wrapper are missing. Every bot-side pattern needed (guild-scoped `Group`/`GroupCog`, the Mod/Sensei inline gate raising `UserFacingError`, `CodeAllTransformer`, the custom paginator, the Phase-9 embed styling) is already in the codebase and can be copied near-verbatim.

The two findings that most affect planning: **(1)** `app_commands.autocomplete` decorator is NOT used anywhere in this codebase — every existing autocomplete is implemented as a `Transformer.autocomplete()` method. D-09 explicitly asks for a `category` autocomplete backed by `list_categories`, so the planner must decide between writing a fresh `@app_commands.autocomplete`-decorated callback (idiomatic discord.py, but a new pattern here) or a new `CategoryTransformer` mirroring `transformers.UserTransformer` (matches existing conventions, returns the resolved category_id directly). The transformer route is recommended because the existing transformers already resolve a free-text autocomplete value into a typed id, which is exactly what the commands need. **(2)** `get_map(code=...)` returns a `MapModel` (subclass of `MapResponse` in `utilities/maps.py`), NOT `MapResponse` — it has a `.map_banner` property and `.difficulty`/`.map_name` fields, which is exactly what the Phase-9 embed already consumes (`tournaments.py:82`). Reuse that exact code path for `/tournament info`.

**Primary recommendation:** Add the streak endpoint mirroring `get_category` exactly (404→treat-as-zero handled bot-side per D-04, so the endpoint can simply 404 and the wrapper/cog maps that to a zero struct). Add six thin `APIService` wrappers following the `get_tournament_category` `Route(...)` pattern. Put the new command cog in `apps/bot/extensions/tournaments.py` and add it to the existing `setup()`. Use a `CategoryTransformer` for the autocomplete arg, `CodeAllTransformer` for the reroll code, `StaticPaginatorView` (page_size=10) for the leaderboard, and copy the Phase-9 embed builder for `/info`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Streak read business logic | API / Service (`TournamentService.get_streak`) | Repository (`fetch_streak`, exists) | Single-writer/single-reader rule: all DB reads go through the API service layer, never the bot. |
| Streak HTTP route + scope | API / Controller (`TournamentsController`) | — | Scope guard (`tournaments:read`) lives on the route `opt`. |
| Streak "not found → zero" UX | Bot / Cog | — | D-04 is a presentation decision; the endpoint stays a pure data read. Bot maps 404/None to a zero struct. |
| Category autocomplete | Bot / Transformer | API (`list_categories`) | discord.py owns autocomplete callbacks; the API owns the live category list. |
| Admin role gate (Mod/Sensei) | Bot / Cog (inline `get_role` check) | Discord (`default_member_permissions` as a first-line UI filter) | Bot uses its own API key, so audience restriction CANNOT be an API scope — it must be enforced bot-side (D-07). |
| Reroll / choose-map mutation | API / Service+Controller (exist) | Bot (wrapper + cog) | Bot never writes the DB; it calls the existing `tournaments:write` endpoints. |
| Active-cycle resolution | API (`list_cycles` filters) | Bot (composes leaderboard call) | Bot resolves the active cycle id via the existing filtered list, then calls leaderboard. |
| Leaderboard rendering + pagination | Bot / `StaticPaginatorView` | API (`get_leaderboard`, returns full list) | Pagination is a Discord UI concern; the full list already fits in memory (D-13). |
| Embed styling (`/info` rich card) | Bot / Cog (reuse Phase-9 builder) | API (`get_map`, `get_tournament_category`) | Embed look is owned by the bot; map metadata sourced from the API per Phase-9 D-07. |

## Standard Stack

No new packages. Everything below already exists in the workspace and is pinned in the existing lockfile.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| discord.py | master (git) | `app_commands` slash commands, `Group`/`GroupCog`, autocomplete, `Transform`, `LayoutView` paginators | [VERIFIED: CLAUDE.md tech stack + `apps/bot/pyproject.toml`] Already the bot framework; every analog command uses it. |
| msgspec | >=0.19.0 | Request/response struct (de)serialization across SDK/API/bot | [VERIFIED: CLAUDE.md] Project-wide serialization standard. |
| Litestar | >=2.16.0 | New streak GET route | [VERIFIED: CLAUDE.md] The API framework; the new route is one method on the existing `TournamentsController`. |
| aiohttp | >=3.12.14 | Bot→API HTTP transport (inside `APIService`) | [VERIFIED: CLAUDE.md] Existing `_request` transport. |

### Supporting (existing, reused)
| Component | Location | Purpose |
|-----------|----------|---------|
| `transformers.CodeAllTransformer` | `apps/bot/utilities/transformers.py:205` | Validated Overwatch-code arg for the optional reroll map (D-15). |
| `transformers.UserTransformer` | `apps/bot/utilities/transformers.py:~225` | Template for a new `CategoryTransformer` (D-09). |
| `StaticPaginatorView` (`PaginatorView` alias) | `apps/bot/utilities/paginator.py:318` | In-memory page-size-10 leaderboard (D-13). |
| `CompletionsLeaderboardPaginator` | `apps/bot/extensions/completions.py:915` | Rendering analog (`build_page_body`, `page_size=10`, `empty_message`) — but it is an `ApiPaginatorView`; for the static variant mirror `ModRecordManagementView` (`moderator.py:1855`). |
| `UserFacingError` | `apps/bot/utilities/errors.py` | Raised by the inline admin gate (D-07). |
| `BaseCog` | `apps/bot/utilities/base.py` | Base for the new command cog (simple `self.bot` reference). |
| Phase-9 embed builder | `apps/bot/extensions/tournaments.py:84-97` | Copy for `/tournament info` (D-11). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `StaticPaginatorView` (full list in memory) | `ApiPaginatorView` + add `limit`/`offset` to `get_leaderboard` | More work (API change + new params + offset math). Only worth it if cycles routinely exceed a few hundred entries. Leaning Static per D-13. |
| New `CategoryTransformer` | `@app_commands.autocomplete` callback on each command | The decorator is idiomatic discord.py but unused in this repo; a transformer matches the existing `UserTransformer` convention AND resolves the value straight to a `category_id`. Recommend the transformer. |
| Single `GroupCog` for `/tournament` | `app_commands.Group` class attribute on a `BaseCog` (the `moderator.py` style) | Both work. `GroupCog` (xp.py style) is cleaner for a flat 3-subcommand group; `Group`-attribute (moderator.py) is needed only when nesting groups. Recommend `GroupCog`. |

**Installation:** None — no new dependencies.

## Package Legitimacy Audit

Not applicable — this phase installs **zero** external packages. All code uses libraries already present in `uv.lock`. slopcheck/registry verification skipped (nothing to verify).

## Architecture Patterns

### System Architecture Diagram

```text
Discord user
   │  /tournament info|leaderboard|streak   /tournament-reroll [code]
   ▼
┌──────────────────────── Bot (discord.py app_commands) ───────────────────────┐
│  TournamentCommandCog (GroupCog "tournament")        TournamentRerollCommand   │
│   ├─ info(category*)        ┐                          (flat top-level cmd)     │
│   ├─ leaderboard(category*) ├─ defer(ephemeral=True)   ├─ default_member_perms  │
│   └─ streak()               ┘  (D-10)                  ├─ inline Mod/Sensei gate │
│        │                                               │   (D-07 → UserFacingError)
│        │  CategoryTransformer.autocomplete (D-09) ─────┤                         │
│        │      └─► api.list_categories()                │  code arg via           │
│        ▼                                               │  CodeAllTransformer(D-15)│
│   bot.api (APIService)  ── HTTP X-API-KEY ─────────────┴──► (single writer)      │
│      get_streak / list_cycles / get_leaderboard /                               │
│      reroll_next_cycle / choose_next_cycle / list_tournament_categories /       │
│      get_map(code=) ─► MapModel(.map_banner/.difficulty/.map_name)              │
└─────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
┌──────────────────────── API (Litestar v3, /api/v3/tournaments) ────────────────┐
│  TournamentsController                                                          │
│   GET  /categories                  → list_categories     (tournaments:read)    │
│   GET  /cycles?status=&category_id= → list_cycles         (tournaments:read)    │
│   GET  /cycles/{id}/leaderboard     → get_leaderboard     (tournaments:read)    │
│   POST /categories/{id}/reroll      → reroll_map          (tournaments:write)   │
│   PATCH/categories/{id}/next-cycle  → choose_map          (tournaments:write)   │
│   GET  /streaks/{user_id}  ◄── NEW  → get_streak          (tournaments:read)    │
│        │                                                                        │
│        ▼ TournamentService.get_streak(user_id)  ◄── NEW                         │
│             └─ repo.fetch_streak(user_id)  (EXISTS, :679)                        │
└─────────────────────────────────────┬─────────────────────────────────────────┘
                                       ▼
                              PostgreSQL  tournaments.streaks / .cycles / .completions
```

Trace `/tournament info Beginner`: defer ephemerally → `CategoryTransformer` resolves "Beginner" → `category_id` via `list_categories` → `list_cycles(status="active", category_id=id)` → take `cycles[0]` (or D-16 empty message) → `get_map(code=cycle.map_code)` → build Phase-9-style embed with `<t:ends_at:R>` + `:F` (D-12) → `edit_original_response`.

### Recommended Project Structure
```
apps/api/
├── routes/v3/tournaments.py    # + get_streak route (mirror get_category)
└── services/tournament_service.py  # + get_streak() method

apps/bot/extensions/
└── tournaments.py              # + TournamentCommandCog + /tournament-reroll; extend setup()

apps/bot/extensions/api_service.py  # + 6 wrappers (Route + response_model)
apps/bot/utilities/transformers.py  # + CategoryTransformer (mirror UserTransformer)
```

### Pattern 1: New streak GET route (mirror `get_category` exactly)
**What:** A read-only route on `TournamentsController` returning `TournamentStreakResponse`.
**When to use:** D-01.
**Example:**
```python
# Source: apps/api/routes/v3/tournaments.py (mirror get_category, lines 159-188)
@litestar.get(
    path="/streaks/{user_id:int}",
    summary="Get User Streak",
    description="Get a user's tournament participation streak.",
    opt={"required_scopes": {"tournaments:read"}},
)
async def get_streak(
    self,
    tournament_service: TournamentService,
    user_id: Annotated[int, Parameter(description="User ID")],
) -> TournamentStreakResponse:
    """Get a user's participation streak.

    Raises:
        CustomHTTPException: 404 if no streak record exists.
    """
    streak = await tournament_service.get_streak(user_id)
    if streak is None:
        raise CustomHTTPException(status_code=HTTP_404_NOT_FOUND, detail="No streak record for user.")
    return streak
```
```python
# Source: apps/api/services/tournament_service.py (mirror get_config, line 74)
async def get_streak(self, user_id: int) -> TournamentStreakResponse | None:
    """Get a user's participation streak, or None if no record exists."""
    row = await self._tournament_repo.fetch_streak(user_id)  # EXISTS (repo:679)
    if row is None:
        return None
    return msgspec.convert(row, TournamentStreakResponse)
```
> **D-04 design note for the planner:** keep the "no record → zero" UX in the BOT (the wrapper catches the 404 / the cog maps `None` to a zero struct). This keeps the endpoint a pure data read and is the lowest-friction split. ALTERNATIVE: the service could synthesize a zero `TournamentStreakResponse` (200, never 404) — also acceptable, but then `updated_at` must be fabricated; the bot-side mapping is cleaner. Recommend bot-side.

### Pattern 2: APIService wrappers (copy the `get_tournament_category` shape)
**What:** Thin methods returning `Response[T]` (= a coroutine; callers `await`). Note these methods are NOT `async def` — they return `self._request(...)`.
**Example:**
```python
# Source: apps/bot/extensions/api_service.py:1667 (get_tournament_category)
def get_tournament_streak(self, user_id: int) -> Response[TournamentStreakResponse]:
    r = Route("GET", "/tournaments/streaks/{user_id}", user_id=user_id)
    return self._request(r, response_model=TournamentStreakResponse)

def list_tournament_categories(self) -> Response[list[TournamentCategoryResponse]]:
    r = Route("GET", "/tournaments/categories")
    return self._request(r, response_model=list[TournamentCategoryResponse])

def list_tournament_cycles(
    self, *, status: str | None = None, category_id: int | None = None,
    limit: int = 20, offset: int = 0,
) -> Response[TournamentCycleListResponse]:
    r = Route("GET", "/tournaments/cycles")
    params = {"status": status, "category_id": category_id, "limit": limit, "offset": offset}
    return self._request(r, response_model=TournamentCycleListResponse, params=params)

def get_tournament_leaderboard(self, cycle_id: int) -> Response[list[TournamentLeaderboardEntryResponse]]:
    r = Route("GET", "/tournaments/cycles/{cycle_id}/leaderboard", cycle_id=cycle_id)
    return self._request(r, response_model=list[TournamentLeaderboardEntryResponse])

def reroll_next_cycle(self, category_id: int) -> Response[TournamentNextCycleResponse]:
    r = Route("POST", "/tournaments/categories/{category_id}/reroll", category_id=category_id)
    return self._request(r, response_model=TournamentNextCycleResponse)

def choose_next_cycle(self, category_id: int, data: TournamentChooseMapRequest) -> Response[TournamentNextCycleResponse]:
    r = Route("PATCH", "/tournaments/categories/{category_id}/next-cycle", category_id=category_id)
    return self._request(r, response_model=TournamentNextCycleResponse, data=data)
```
**Pitfall:** `Route` uses `url.format_map(...)`, so path placeholders MUST be passed as kwargs (`cycle_id=cycle_id`). Filters that are query params go through `params=`, which already skips `None` values and flattens lists (`_request`, lines 346-356). Confirmed: `get_map(code=...)` returns `MapModel` (`utilities/maps.py:106`, a `MapResponse` subclass) with `.map_banner`/`.difficulty`/`.map_name` — reuse the Phase-9 path (`tournaments.py:82`), NOT `/partial`.

### Pattern 3: `/tournament` player group as a guild-scoped `GroupCog`
**Example:**
```python
# Source: apps/bot/extensions/xp.py:219 (XPCog GroupCog) + map_submission.py:20 (guild scope)
class TournamentCommandCog(commands.GroupCog, group_name="tournament"):
    def __init__(self, bot: core.Genji) -> None:
        self.bot = bot

    @app_commands.command(name="info")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    async def info(
        self, itx: GenjiItx,
        category: app_commands.Transform[int, transformers.CategoryTransformer],
    ) -> None:
        await itx.response.defer(ephemeral=True)   # D-10
        ...
```
> Note: `xp.py`'s `XPCog` does NOT pass `guild_ids` on the group; other commands rely on `@app_commands.guilds(...)` per-command. For a `GroupCog`, set `app_commands.guilds(...)` on the cog or pass `guild_ids=` to the implicit group — the planner should mirror whichever the bot's tree-sync expects. Existing commands consistently use `@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID","0")))`.

### Pattern 4: `/tournament-reroll` flat command + inline Mod/Sensei gate (D-06/07/14/15)
**Example:**
```python
# Source: moderator.py:78-103 (gate) + map_search/xp command shells
@app_commands.command(name="tournament-reroll")
@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
@app_commands.default_permissions(manage_guild=True)   # first-line Discord UI filter (D-06)
async def tournament_reroll(
    self, itx: GenjiItx,
    category: app_commands.Transform[int, transformers.CategoryTransformer],
    code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer] | None = None,
) -> None:
    await itx.response.defer(ephemeral=True)
    assert isinstance(itx.user, discord.Member) and itx.guild
    is_mod = (
        itx.user.get_role(itx.client.config.roles.admin.mod) is not None
        or itx.user.get_role(itx.client.config.roles.admin.sensei) is not None
    )
    if not is_mod:                                      # D-07 (authoritative gate)
        raise UserFacingError("This command is for moderators only.")
    if code is None:
        result = await itx.client.api.reroll_next_cycle(category)            # D-14
    else:
        result = await itx.client.api.choose_next_cycle(category, TournamentChooseMapRequest(map_code=code))  # D-15
    # reply shows the newly-selected map (result is TournamentNextCycleResponse)
```
> `config.roles.admin.mod` / `.sensei` are `int` fields on the `Admin` config struct (`config.py:38-40`), populated from `[roles.admin]` in `apps/bot/configs/{dev,prod}.toml` (mod=…243, sensei=…244). `default_permissions`/`default_member_permissions` is NOT currently used anywhere in the codebase — it is a valid discord.py decorator but should be treated as a UI convenience only; the inline `get_role` check is the real gate. `[ASSUMED]` that `default_permissions(manage_guild=True)` is the desired Discord-side filter — the planner/user may choose a different permission flag.

### Pattern 5: Leaderboard with `StaticPaginatorView` (D-13)
**Example:**
```python
# Source: moderator.py:1855 (ModRecordManagementView extends PaginatorView=StaticPaginatorView)
#         + completions.py:944 (build_page_body rendering analog)
class TournamentLeaderboardPaginator(StaticPaginatorView[TournamentLeaderboardEntryResponse]):
    def __init__(self, title: str, entries: list[TournamentLeaderboardEntryResponse]) -> None:
        super().__init__(title, entries, page_size=10)   # builds pages in __init__, no .initialize()

    def build_page_body(self) -> Sequence[ui.Item]:
        lines = [f"`#{e.rank}` <@{e.user_id}> — {e.time:.2f}s" for e in self.get_current_page_data()]
        return [ui.TextDisplay("\n".join(lines))]
# usage:
view = TournamentLeaderboardPaginator(f"{category_name} — Leaderboard", entries)
await itx.edit_original_response(view=view)
view.original_interaction = itx
```
> `StaticPaginatorView.__init__` calls `rebuild_data` + `rebuild_components` immediately — unlike `ApiPaginatorView`, there is **no** `await view.initialize()` step. Empty list (D-16): the leaderboard is fetched, and if empty, short-circuit with a friendly ephemeral message BEFORE constructing the paginator (a 0-entry static view has zero pages and would crash on the `% len(self._pages)` modulo). DO NOT pass an empty list to the paginator.

### Pattern 6: `CategoryTransformer` for autocomplete (D-09)
**What:** A `Transformer` whose `autocomplete()` queries `list_categories` and `transform()` resolves the chosen name → `category_id`.
**Example:**
```python
# Source: transformers.py:225-274 (UserTransformer) — same shape
class CategoryTransformer(app_commands.Transformer):
    async def autocomplete(self, itx: GenjiItx, current: str) -> list[app_commands.Choice[str]]:
        categories = await itx.client.api.list_tournament_categories()
        cur = current.casefold()
        return [
            app_commands.Choice(name=c.name, value=str(c.id))
            for c in categories if cur in c.name.casefold()
        ][:25]   # Discord hard limit: 25 choices
    async def transform(self, itx: GenjiItx, value: str) -> int:
        if value.isdigit():
            return int(value)
        # fall back: resolve a free-typed name
        cats = await itx.client.api.list_tournament_categories()
        match = next((c for c in cats if c.name.casefold() == value.casefold()), None)
        if match is None:
            raise UserFacingError(f"Unknown category: {value}")
        return match.id
```

### Anti-Patterns to Avoid
- **Passing an empty list to `StaticPaginatorView`** — zero pages → modulo-by-zero on navigation. Short-circuit empty leaderboards first (D-16).
- **Relying on `default_member_permissions` as the security boundary** — it is a client-side UI hint; admins can be bypassed via API/other clients. The inline `get_role` check is the real gate (D-07).
- **Calling `get_map(...)/partial`** for `/info` map metadata — Phase-9 D-07 already standardized on `get_map(code=...)` → `MapModel.map_banner`. Use the same.
- **Bot writing to the DB or computing tournament state locally** — forbidden; resolve everything through the existing API endpoints.
- **`async def` on `APIService` wrapper methods** — the existing convention is sync methods returning `self._request(...)` (a coroutine the caller awaits). Match it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Relative/absolute time display | Custom "in 3 days" duration math | `discord.utils.format_dt(ends_at, "R")` + `"F"` (D-12) | Auto-updating, per-viewer localized, zero maintenance. Phase-9 already does this (`tournaments.py:93`). |
| Pagination buttons/state | Custom button view | `StaticPaginatorView` (D-13) | Wraparound, page counter, timeout, error routing all handled. |
| Map-code validation | Manual regex / lookup | `transformers.CodeAllTransformer` (D-15) | Existing validated transformer used by `moderator.py` map commands. |
| Category id resolution + autocomplete | Hardcoded choices | `CategoryTransformer` over `list_categories` (D-09) | Categories are admin-created at runtime; static `Choice` lists go stale. |
| Streak data access | New SQL | `repo.fetch_streak` (exists, :679) + new `get_streak` service method | Repo + struct already built in Phase 8. |
| Admin gate | New permission system | `moderator.py` inline `get_role(mod/sensei)` → `UserFacingError` | Established, audited pattern. |
| Embed styling | New embed layout | Copy Phase-9 new-cycle embed builder (`tournaments.py:84-97`) | D-11 wants unified look. |

**Key insight:** This phase should add ~1 endpoint, ~6 wrappers, ~1 transformer, ~1 cog, and ~1 paginator subclass — all by copying existing analogs. Almost nothing here is novel.

## Runtime State Inventory

Not a rename/refactor/migration phase — section omitted (purely additive feature work).

## Common Pitfalls

### Pitfall 1: Empty leaderboard crashes the static paginator
**What goes wrong:** Constructing `StaticPaginatorView` with `[]` yields zero pages; navigation/`%` math divides by zero.
**Why:** `rebuild_data` chunks an empty list into `[]`; index math assumes ≥1 page.
**How to avoid:** Fetch leaderboard, check `if not entries:` → send D-16 "No submissions yet — be the first!" ephemerally and return BEFORE building the view.
**Warning signs:** `ZeroDivisionError`/`IndexError` on `navigate_*`.

### Pitfall 2: Defer ordering with ephemeral (D-10)
**What goes wrong:** Sending a non-deferred response after a `defer`, or deferring non-ephemerally then trying ephemeral follow-ups.
**Why:** Discord locks ephemerality at the FIRST response (`defer`). All follow-ups inherit it.
**How to avoid:** `await itx.response.defer(ephemeral=True)` as the FIRST line of every command, then `itx.edit_original_response(...)` / `itx.followup.send(...)`. Matches `moderator.py:90`, `map_search.py:360`.

### Pitfall 3: Autocomplete 25-choice limit + per-keystroke API calls
**What goes wrong:** Returning >25 choices errors; one `list_categories` call per keystroke can hammer the API.
**How to avoid:** Slice `[:25]`. Category counts are tiny (admin-created), so per-keystroke calls are acceptable, but the planner may add a short cache if desired. Existing transformers (`UserTransformer`) call the API per keystroke without caching — consistent.

### Pitfall 4: Admin gate must be bot-side, not API scope (D-07)
**What goes wrong:** Assuming `tournaments:write` scope restricts who can reroll. The bot holds ONE API key with full scopes; every Discord user invoking the command would pass.
**How to avoid:** Enforce Mod/Sensei via `itx.user.get_role(...)` in the command body. `default_permissions` is only a UI filter.
**Warning signs:** Non-admins successfully rerolling in testing.

### Pitfall 5: Extension load order / command registration
**What goes wrong:** A new extension that registers queue consumers must load before `rabbit.py`; commands must be guild-scoped and synced.
**How to avoid:** Putting the cog in the existing `apps/bot/extensions/tournaments.py` and extending its `setup()` keeps it within the `EXTENSIONS` sort that loads everything before `rabbit.py` (auto-enforced, `extensions/__init__.py`). Guild-scope every command (`@app_commands.guilds(GUILD_ID)`) so the tree syncs to the dev/prod guild rather than waiting ~1h for global propagation.
**Warning signs:** Commands not appearing in the guild; consumers registering after rabbit starts.

### Pitfall 6: `Route` placeholder vs query-param confusion
**What goes wrong:** Putting `status`/`category_id` into the path template, or forgetting a path kwarg → `KeyError` from `format_map`.
**How to avoid:** Path ids as `Route(..., cycle_id=cycle_id)`; filters via `params={...}` (skips `None`, flattens lists). See `get_maps` (api_service.py:398).

### Pitfall 7: `setup()` extension already defines `bot.tournaments`
**What goes wrong:** Extending `tournaments.py`'s `setup()` and accidentally overwriting `bot.tournaments` (the handler) when adding the cog.
**How to avoid:** Keep `bot.tournaments = TournamentHandler(bot)` AND `await bot.add_cog(TournamentCommandCog(bot))` as separate lines — the cog is added, not assigned to the same attribute. Mirror `xp.py:247-248` (`bot.xp = XPHandler(bot); await bot.add_cog(XPCog(bot))`).

## Code Examples

### Time-remaining rendering (D-12)
```python
# Source: apps/bot/extensions/tournaments.py:93 (Phase-9 verified pattern)
embed.add_field(
    name="Ends",
    value=f"{discord.utils.format_dt(cycle.ends_at, 'R')} ({discord.utils.format_dt(cycle.ends_at, 'F')})",
    inline=False,
)
```
> NOTE: `TournamentCycleStartedEvent` carries `ends_at` (sdk:413), but the `list_cycles` response (`TournamentCycleWithWinnerResponse`, sdk:233) exposes `started_at`/`ended_at` — there is **no computed `ends_at`** on the active-cycle list response. See Open Question 1.

### Active-cycle resolution (D-16 empty handling)
```python
cycles = (await self.bot.api.list_tournament_cycles(status="active", category_id=category_id)).cycles
if not cycles:
    await itx.edit_original_response(content="No active cycle for that category right now.")  # D-16
    return
active = cycles[0]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `discord.ext.menus` paginators | Project `StaticPaginatorView`/`ApiPaginatorView` (`LayoutView`-based) | Existing | D-13 mandates the project paginator; do not import discord-ext-menus for this. |
| Static `Choice` enums for args | Runtime autocomplete via API | Existing (`transformers.py`) | Categories are dynamic; static lists go stale. |
| Manual duration strings | `discord.utils.format_dt` timestamps | Existing | Auto-updating, localized. |

**Deprecated/outdated:** `increment_page_index`/`decrement_page_index`/`skip_to_page_index` on the paginator are marked Deprecated — use `navigate_next`/`navigate_previous`/`navigate_to_page` (paginator.py:399-427). The base view machinery uses the navigate_* methods.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `default_permissions(manage_guild=True)` is the desired Discord-side UI filter for `/tournament-reroll` | Pattern 4 | Low — it is only a UI hint; the inline gate is authoritative. Planner/user may pick a different flag or omit it. |
| A2 | Bot-side mapping of "no streak record → zero struct" (endpoint 404s) is preferred over service-side synthesis | Pattern 1 | Low — both satisfy D-04; affects which layer fabricates `updated_at`. Confirm with planner. |
| A3 | A `CategoryTransformer` is preferred over an `@app_commands.autocomplete` callback for D-09 | Standard Stack / Pattern 6 | Low — both work; transformer matches repo convention and returns the id directly. |
| A4 | Per-keystroke `list_categories` calls (no cache) are acceptable | Pitfall 3 | Low — matches existing `UserTransformer` behavior; category count is tiny. |

## Open Questions (RESOLVED)

1. **Where does `/tournament info` get the cycle END time?**
   - **RESOLVED:** compute `ends_at = started_at + timedelta(days=7 if weekly else 14)` locally from the category's `cycle_frequency` — no API/SDK change (per 10-03 Task 1).
   - What we know: `TournamentCycleStartedEvent` has `ends_at` (sdk:413), but `list_cycles` → `TournamentCycleWithWinnerResponse` exposes only `started_at`/`ended_at` (sdk:233-262), with no computed `ends_at` for an ACTIVE cycle. Cycle end is derived from the category's `cycle_frequency` (weekly/biweekly) applied to `started_at`.
   - What's unclear: whether the bot should compute `ends_at = started_at + frequency` locally, or whether the API/SDK should expose `ends_at` on the active-cycle response.
   - Recommendation: **Flag to planner.** Cleanest is to compute `ends_at` from `started_at` + the category's `cycle_frequency` (the category is already fetched for the embed). A local computation keeps the API unchanged. If the planner prefers a server-side field, that is a small additive SDK/service change but expands scope. Either way, this needs an explicit decision — it is the one genuine gap in `/info`.

2. **Does the leaderboard render show player names or only `<@id>` mentions?**
   - **RESOLVED:** use `<@user_id>` numeric mentions only — mention-injection mitigation, matches Phase-9 (per 10-03 Task 1).
   - What we know: `TournamentLeaderboardEntryResponse` has both `name` and `user_id` (sdk:294-299). Phase-9 results embed used `<@user_id>` mentions; `CompletionsLeaderboardPaginator` uses `name`.
   - Recommendation: For an ephemeral leaderboard, `<@user_id>` renders nicely without ping noise (it is ephemeral; no one else sees it). Either is fine — minor styling call left to planner per D-13 discretion.

## Environment Availability

Skipped — no external dependencies. The phase uses only the running API (already required for all bot work), PostgreSQL (streak table seeded in Phase 1/8), and discord.py. No new tools/services/runtimes introduced.

## Validation Architecture

> nyquist_validation is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.3.5 + pytest-asyncio (mode auto) + pytest-databases[postgres] |
| Config file | `apps/api/pyproject.toml` (`addopts = "--testmon"`) |
| Quick run command | `uv run --directory apps/api pytest tests/<file> -v -p no:xdist` (single file) |
| Full suite command | `just test-api` |

> MEMORY note: multi-file runs need `--no-testmon` (testmon deselects when multiple files passed). Bot-side logic is tested under `apps/api/tests/bot/` by loading the bot module by file path with stubbed bot internals (see `test_tournaments_handler.py:44-73`). The new streak endpoint is tested as a Litestar integration test (mirror `test_tournaments_integration.py`).

### Phase Requirements → Test Map (highest-risk behaviors)
| Req / Criterion | Behavior | Test Type | Automated Command | File Exists? |
|------|----------|-----------|-------------------|-------------|
| ADM-03 / D-07 | Non-Mod/Sensei invoking `/tournament-reroll` is rejected (UserFacingError), no API write occurs | unit (bot) | `pytest tests/bot/test_tournament_commands.py -k reroll_gate -p no:xdist` | ❌ Wave 0 |
| ADM-03 / D-14/15 | Reroll with no code → `reroll_next_cycle`; with code → `choose_next_cycle(...)` | unit (bot) | `... -k reroll_dispatch` | ❌ Wave 0 |
| Crit 3 / D-04 | Streak-not-found returns zero (current 0 / max 0), not an error | unit (bot mapping) + integration (endpoint 404) | `... -k streak_zero`; `pytest tests/integration/test_tournaments_integration.py -k streak` | ❌ Wave 0 |
| D-01 | `GET /tournaments/streaks/{user_id}` requires `tournaments:read`; 401 without key, 404 when absent, 200 with data | integration | `pytest tests/integration/test_tournaments_integration.py -k streak -p no:xdist` | ❌ Wave 0 (extend existing file) |
| D-09 | Category autocomplete returns live categories, slices to ≤25, name→id resolves | unit (bot transformer) | `... -k category_transformer` | ❌ Wave 0 |
| Crit 2 / D-13 | Empty leaderboard → friendly message (no paginator); non-empty → 10-per-page boundaries correct | unit (bot) | `... -k leaderboard_empty`, `-k leaderboard_pagination` | ❌ Wave 0 |
| Crit 1 / D-16 | No active cycle → "No active cycle…" message, no get_map call | unit (bot) | `... -k info_no_active_cycle` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the single most-relevant `-k` selector above.
- **Per wave merge:** `pytest tests/bot/test_tournament_commands.py tests/integration/test_tournaments_integration.py --no-testmon -p no:xdist`.
- **Phase gate:** `just test-api` green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `apps/api/tests/bot/test_tournament_commands.py` — new file; bot-side cog/transformer/paginator logic via the path-load + stub pattern of `test_tournaments_handler.py`. Covers ADM-03 gate, reroll dispatch, streak-zero mapping, autocomplete, leaderboard empty/pagination, info empty.
- [ ] Extend `apps/api/tests/integration/test_tournaments_integration.py` — add `TestGetStreak` (200/404/401 + scope) mirroring `TestGetConfig`/`TestGetCategory`.
- [ ] Extend `apps/api/tests/services/test_tournament_service.py` — add `TestGetStreak` (returns struct on row; returns `None`/raises per chosen D-04 split) mirroring `TestGetLeaderboard`.
- Framework install: none — pytest infra already present.

## Security Domain

> security_enforcement absent in config → treated as enabled.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (API) | Existing `X-API-KEY` auth middleware on all `/api/v3` routes; new streak route inherits it. |
| V3 Session Management | no | No sessions involved in slash commands. |
| V4 Access Control | yes | **Two layers:** API scope (`tournaments:read`/`:write`) on routes; AND the authoritative Discord Mod/Sensei role check for `/tournament-reroll` (D-07) — because the bot holds one key with full scopes, the API scope alone does NOT restrict which Discord user acts. |
| V5 Input Validation | yes | `category` resolved via `CategoryTransformer` (validates against live list); `code` via `CodeAllTransformer` (validated Overwatch code); `user_id` is the invoker's id (self-only, D-02) — never user-supplied. msgspec validates request/response structs. |
| V6 Cryptography | no | No crypto in this phase. |

### Known Threat Patterns for discord.py slash commands + Litestar
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Privilege escalation via reroll command | Elevation of Privilege | Inline Mod/Sensei `get_role` gate (D-07), authoritative; `default_permissions` as defense-in-depth UI filter. |
| Mention/ping injection from free-text names | Tampering / Spoofing | Use `<@user_id>` numeric mentions only; never interpolate user `name` into a mention. (Phase-9 already does this; `tournaments.py:138-152`.) Leaderboards are ephemeral, further limiting blast radius. |
| IDOR on streak endpoint (read another user) | Information Disclosure | Self-only by design (D-02); bot passes the invoker's id. The endpoint itself takes a `user_id` and is `tournaments:read`-scoped — acceptable since streak data is non-sensitive (public competition stats), but worth noting the endpoint is technically capable of looking up any id. |
| API write from non-admin Discord user | Elevation of Privilege | Same as row 1 — bot-side gate is the boundary. |

## Sources

### Primary (HIGH confidence — read in this session)
- `apps/api/routes/v3/tournaments.py` — full controller; confirmed all 5 reused endpoints + the `get_category` mirror for the new streak route.
- `apps/api/services/tournament_service.py` — confirmed service method shape, `msgspec.convert`, DI provider.
- `apps/api/repository/tournaments_repository.py:655-697` — confirmed `fetch_streak` exists, returns `dict | None`.
- `libs/sdk/src/genjishimada_sdk/tournaments.py:160-438` — confirmed `TournamentStreakResponse`, `TournamentLeaderboardEntryResponse`, `TournamentCycleWithWinnerResponse` (no `ends_at`), `TournamentCycleStartedEvent` (has `ends_at`), `TournamentChooseMapRequest`.
- `apps/bot/extensions/api_service.py:160-580, 1667-1674` — `Route`, `_request`, `params` handling, `get_tournament_category` template, `get_map`→`MapModel`.
- `apps/bot/extensions/tournaments.py` (full) — Phase-9 embed builder, `setup()`, `bot.tournaments` assignment.
- `apps/bot/extensions/moderator.py:58-127, 355-368, 1855-1894` — `Group`, inline Mod/Sensei gate, `CodeAllTransformer`, `PaginatorView` usage, `setup()`.
- `apps/bot/extensions/xp.py:219-248` — `GroupCog` + `setup()` add-cog pattern.
- `apps/bot/extensions/map_search.py:311-396` — command shell, `guilds`, transformer args.
- `apps/bot/extensions/completions.py:915-965` — `CompletionsLeaderboardPaginator` rendering analog.
- `apps/bot/utilities/paginator.py:161-469` — `BasePaginatorView`, `StaticPaginatorView` (builds in `__init__`, no `.initialize()`), `ApiPaginatorView`.
- `apps/bot/utilities/transformers.py:35-287` — autocomplete-via-Transformer convention (no `@app_commands.autocomplete` in repo).
- `apps/bot/utilities/config.py:38-104` — `Admin` (mod/sensei), `Tournament` channel, `Config` structure.
- `apps/bot/configs/dev.toml` `[roles.admin]` — mod/sensei role ids.
- `apps/bot/core/genji.py` — `Genji.api`, `.config`, `.tournaments` attributes.
- `apps/api/tests/{bot/test_tournaments_handler.py, integration/test_tournaments_integration.py, services/test_tournament_service.py}` — test patterns (bot path-load, integration scope assertions, service unit tests).
- `.planning/config.json` — `nyquist_validation: true`, `security_enforcement` absent.

### Secondary (MEDIUM)
- discord.py `app_commands` semantics (defer ephemerality lock, 25-choice autocomplete limit, `default_permissions` as UI hint) — consistent with in-repo usage; no external doc fetch needed.

### Tertiary (LOW)
- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — everything verified present in the workspace; zero new packages.
- Architecture: HIGH — all reused endpoints and bot patterns read directly this session.
- Pitfalls: HIGH — derived from actual code (paginator modulo, defer ordering, single-key gate, load order).
- One genuine gap: `ends_at` source for `/info` (Open Question 1) — flagged, not blocking.

**Research date:** 2026-05-30
**Valid until:** 2026-06-29 (stable internal codebase; re-verify only if Phase 9 embed code or the paginator API changes)
