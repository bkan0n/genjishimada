# Phase 10: Bot Slash Commands - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Discord slash commands that let **players** view tournament state and let **admins**
act on the next cycle — all reading/writing **through the existing HTTP API** via
`apps/bot/extensions/api_service.py` wrappers (the bot is consumer-only and never touches
the DB). Four commands deliver the four ROADMAP success criteria:

1. **`/tournament info <category>`** — active cycle info (map, time remaining, category) — criterion 1.
2. **`/tournament leaderboard <category>`** — current cycle leaderboard, paginated — criterion 2.
3. **`/tournament streak`** — the invoking user's participation streak — criterion 3.
4. **`/tournament-reroll <category> [code]`** — admin reroll of a category's next-cycle map — criterion 4 (ADM-03).

**In scope:** the four slash commands; a new **`GET` streak endpoint** in the API (the only
backing endpoint missing) + the matching `TournamentService` method; the bot-side
`APIService` wrappers needed (streak, list cycles, leaderboard, reroll, choose-map,
list categories for autocomplete); reuse of the Phase-9 tournament embed styling; pagination
via the project's custom paginator.

**Out of scope (other phases / forbidden):** any DB writes from the bot (architecturally
forbidden — all mutation goes through the API); changes to how the API publishes events
(Phase 7 owns the outbox); new tournament *capabilities* beyond viewing state + reroll;
season/history browsing UIs; web/mobile UI. Command-name bikeshedding was offered and the
user deferred to the defaults listed above.

</domain>

<decisions>
## Implementation Decisions

### Streak command + its backing endpoint
- **D-01:** **Add a player-readable `GET` streak endpoint in THIS phase.** The repo method
  `fetch_streak(user_id)` (`apps/api/repository/tournaments_repository.py:679`) and the SDK
  struct `TournamentStreakResponse` (`libs/sdk/src/genjishimada_sdk/tournaments.py:380`)
  **already exist** — only a `TournamentService` method, a route handler, and a bot
  `APIService` wrapper are missing. Endpoint shape (e.g. `GET /tournaments/streaks/{user_id}`)
  is the planner's call; it must require `tournaments:read` to match the controller's pattern.
- **D-02:** **Self-only.** `/tournament streak` resolves the streak for the **invoking Discord
  user** (the bot passes that user's id to the endpoint). No "look up another user" arg.
- **D-03:** Show **current_streak AND max_streak** (both already on the struct).
- **D-04 (no streak record):** **Treat as zero** — show current 0 / max 0 with an
  encouraging line ("Submit in a cycle to start your streak!"), NOT an error.

### Command structure & admin gating
- **D-05:** **Player commands live under a single `/tournament` group** (`info`, `leaderboard`,
  `streak`) — `app_commands.Group` / `GroupCog` scoped to the guild (matches `moderator.py`'s
  `app_commands.Group` and `xp.py`'s `GroupCog`).
- **D-06:** **Admin reroll is a SEPARATE flat top-level command `/tournament-reroll`** — NOT a
  subcommand of `/tournament`. Rationale (user): Discord's `default_member_permissions` applies
  at the top-level command/group, so you cannot cleanly mix open player subcommands and a
  locked admin subcommand in one group. `/tournament-reroll` gets restricted
  `default_permissions` **plus** an inline role check.
- **D-07 (admin gate):** Reroll is gated to **Mod OR Sensei** via an inline role check
  (`itx.user.get_role(config.roles.admin.mod)` or `...admin.sensei`), raising `UserFacingError`
  on failure — the exact pattern `moderator.py` uses. The bot calls the API with its own
  API key, so this gate MUST be enforced bot-side (API scope alone won't restrict it).

### Category selection
- **D-08:** **`info`, `leaderboard`, and `reroll` each take a REQUIRED `category` argument**
  (one cycle shown/acted-on per invocation). `streak` takes no category (self-only).
- **D-09:** **The `category` arg uses dynamic autocomplete** (`app_commands.autocomplete`)
  backed by the API's `list_categories` (`GET /tournaments/categories`) — categories are
  admin-created at runtime, so static `Choice` lists won't work.

### Output format
- **D-10:** **ALL command responses are ephemeral** (visible only to the invoker). Defer
  ephemerally at the start of each command.
- **D-11:** **Reuse the Phase-9 `TournamentHandler` embed styling** (colors, thumbnail,
  field layout from `apps/bot/extensions/tournaments.py`) so commands and announcements feel
  unified. `/tournament info` is a **full rich card** mirroring the Phase-9 **new-cycle embed**:
  map name, clickable workshop-code link, difficulty, category name, map thumbnail, and time
  remaining.
- **D-12 (time remaining):** Render as **relative + absolute** Discord timestamps —
  `<t:{ends_at}:R>` ("in 3 days") together with `<t:{ends_at}:F>` (absolute). Auto-updating,
  localized per viewer, no custom duration formatting.
- **D-13 (leaderboard depth + paginator):** Leaderboard **paginates using the project's custom
  paginator** in `apps/bot/utilities/paginator.py` — **NOT discord-ext-menus** (explicit user
  directive). Page size 10. The closest rendering analog is
  `CompletionsLeaderboardPaginator` (`apps/bot/extensions/completions.py:915`), an
  `ApiPaginatorView` leaderboard. **NOTE:** the existing `GET /cycles/{cycle_id}/leaderboard`
  returns the **full** `list[TournamentLeaderboardEntryResponse]` with no pagination params —
  so the lower-friction fit is `StaticPaginatorView` (in-memory pagination of the full list,
  no API change). The planner may instead add page params to the endpoint and use
  `ApiPaginatorView`; either is acceptable — leaning `StaticPaginatorView`.

### Reroll behavior
- **D-14:** **`/tournament-reroll` defaults to a random reroll** of the category's next-cycle
  map (calls the reroll endpoint, `POST /tournaments/categories/{category_id}/reroll`), and
  **reply shows the newly-selected map**. No confirmation step (reroll is itself repeatable).
- **D-15:** **Optional explicit-map arg.** `/tournament-reroll` takes an **optional Overwatch
  `code`** to explicitly choose a specific map instead of rolling randomly — uses the
  **choose-map endpoint** (`POST /tournaments/categories/{category_id}/next-cycle`, the
  `choose_map` handler). This is **intentionally slightly broader** than criterion 4's bare
  "reroll" — the user asked for it. The `code` arg uses the existing
  `transformers.CodeAllTransformer` (like `moderator.py`'s map-edit commands) for validation.

### Empty / error states
- **D-16:** **Friendly ephemeral messages** for each empty/missing case (not bare generic
  errors): no active cycle for {category} ("No active cycle for {category} right now."),
  empty leaderboard ("No submissions yet — be the first!"), no streak record (see D-04,
  treat as zero), no pending next-cycle map to reroll ("No pending next-cycle map to reroll.").

### Active-cycle resolution (implementation note)
- `/tournament info` and `/tournament leaderboard` are scoped to the category's **current
  cycle**. Resolve it via `GET /tournaments/cycles?status=active&category_id={id}` (the
  `list_cycles` endpoint supports `status` + `category_id` filters), then use that cycle's id
  for the leaderboard call. Exact wrapper signatures are the planner's call.

### Claude's Discretion (defer to research/planning)
- Exact API streak-endpoint path/signature (D-01) and the `APIService` wrapper names.
- `StaticPaginatorView` vs `ApiPaginatorView` for the leaderboard (D-13) — lean
  `StaticPaginatorView` since the endpoint returns the full list.
- Whether the new slash-command Cog lives **in the existing
  `apps/bot/extensions/tournaments.py`** (extend `setup` to also add the command cog
  alongside `TournamentHandler`) or a sibling module — leaning "same file" to keep tournament
  bot code together; must still load before `rabbit.py` (auto-enforced by `EXTENSIONS` sort).
- Embed field layout/styling specifics, exact copy strings, autocomplete result limits.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` — Phase 10 goal + 4 success criteria (authoritative scope).
- `.planning/REQUIREMENTS.md` — **ADM-03** (admin Discord slash commands for tournament
  actions) — the requirement this phase covers. Criteria 1-3 (player commands) are roadmap
  success criteria beyond ADM-03.

### Existing slash-command patterns (closest analogs — read first)
- `apps/bot/extensions/moderator.py:58-118` — `app_commands.Group` with `guild_ids`, nested
  groups, and the **inline Mod/Sensei role-check → `UserFacingError`** admin-gating pattern
  (D-07); also `app_commands.Transform[..., transformers.CodeAllTransformer]` map-code arg
  (D-15).
- `apps/bot/extensions/xp.py:219` — `class XPCog(commands.GroupCog, group_name="xp")` —
  GroupCog alternative for the `/tournament` player group (D-05).
- `apps/bot/extensions/map_search.py:312-421` — `@app_commands.command`, `@app_commands.choices`,
  `@app_commands.describe`, `@app_commands.rename`, and **autocomplete** usage (D-09 reference).
- `apps/bot/extensions/map_submission.py:19-90` — simple `@app_commands.command` +
  `@app_commands.guilds(...)` structure.

### Custom paginator (D-13 — use THIS, not discord-ext-menus)
- `apps/bot/utilities/paginator.py` — `BasePaginatorView` (161), `StaticPaginatorView` (318,
  in-memory), `ApiPaginatorView` (443, API-paged); `PaginatorView = StaticPaginatorView` (619).
- `apps/bot/extensions/completions.py:915` — `CompletionsLeaderboardPaginator(ApiPaginatorView[...])`
  — direct rendering analog for a paginated leaderboard (`build_page_body`, `page_size=10`,
  `empty_message`).

### Phase-9 embed styling to reuse (D-11)
- `apps/bot/extensions/tournaments.py:57` — `TournamentHandler(BaseHandler)`: new-cycle +
  results embed builders, thumbnail/field layout, channel resolution. The slash-command Cog
  should match this look and may share/extend `setup` (line 231).
- `.planning/phases/09-bot-queue-consumers-announcements/09-CONTEXT.md` — D-02 (new-cycle embed
  fields), D-07 (sourcing map difficulty/thumbnail via `get_map(code=...)` → `MapResponse`,
  NOT `/partial`), and the deferral of "full/top-10 leaderboard" to this phase.

### Bot API client (must extend — only `get_tournament_category` exists today)
- `apps/bot/extensions/api_service.py:1667` — `get_tournament_category(category_id)` (the
  single existing tournament wrapper); follow its `Route(...)` + msgspec-decoder pattern to add
  wrappers for: streak (D-01), `list_cycles` (active-cycle resolution), `get_leaderboard`,
  `reroll`, `choose_map`, and `list_categories` (autocomplete).
- `apps/bot/extensions/api_service.py` `get_map(code=...)` → `MapResponse` (has `map_banner`,
  `difficulty`, `map_name`) — for `/info` map metadata (per Phase-9 D-07; NOT `/partial`).

### API endpoints the commands call
- `apps/api/routes/v3/tournaments.py` — `TournamentsController` (path `/tournaments`,
  `tags=["Tournaments"]`). Relevant routes:
  - `GET /tournaments/categories` (`list_categories`, `tournaments:read`) — autocomplete source (D-09).
  - `GET /tournaments/cycles?status=&category_id=` (`list_cycles`, `tournaments:read`) — active-cycle resolution.
  - `GET /tournaments/cycles/{cycle_id}/leaderboard` (`get_leaderboard`, `tournaments:read`) —
    **returns full list, no pagination params** (informs D-13).
  - `POST /tournaments/categories/{category_id}/reroll` (`reroll_map`, `tournaments:write`) — D-14.
  - `POST /tournaments/categories/{category_id}/next-cycle` (`choose_map`, `tournaments:write`) — D-15.
  - **NEW** streak read endpoint to be added here (D-01).

### Streak read infra that already exists (D-01)
- `apps/api/repository/tournaments_repository.py:679` — `fetch_streak(user_id)`
  (`SELECT * FROM tournaments.streaks WHERE user_id = $1`).
- `libs/sdk/src/genjishimada_sdk/tournaments.py:380` — `TournamentStreakResponse`
  (`user_id`, `current_streak`, `max_streak`, `last_cycle_id`, ...).

### Extension load order
- `apps/bot/extensions/__init__.py` — `EXTENSIONS` sort guarantees everything loads before
  `rabbit.py`; a new/extended extension is auto-discovered.

### Conventions
- `.planning/codebase/CONVENTIONS.md`, `.planning/codebase/INTEGRATIONS.md` — slash-command,
  `UserFacingError`, msgspec, `%s`-style logging (`[→]/[✓]/[x]/[!]`), and APIService `Route`
  patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`app_commands.Group` / `GroupCog`** (`moderator.py`, `xp.py`) — the `/tournament` player
  group.
- **Inline Mod/Sensei role check → `UserFacingError`** (`moderator.py:94-103`) — admin gate for
  `/tournament-reroll`.
- **`transformers.CodeAllTransformer`** (`moderator.py` map commands) — validated Overwatch-code
  arg for the optional explicit reroll map (D-15).
- **Custom paginator** `apps/bot/utilities/paginator.py` + `CompletionsLeaderboardPaginator`
  (`completions.py:915`) — leaderboard pagination (D-13).
- **Phase-9 `TournamentHandler` embeds** (`tournaments.py`) — styling to reuse for `/info` and
  the leaderboard (D-11).
- **`fetch_streak` repo method + `TournamentStreakResponse` struct** — already exist; only the
  service/route/wrapper are missing (D-01).

### Established Patterns
- Bot is **consumer/HTTP-only**: every command reads/writes via `APIService` wrappers; the bot
  never touches Postgres.
- Slash commands defer (here: ephemerally), then `edit_original_response`/`followup`.
- `category` args use dynamic autocomplete from a live API list, not static `Choice`s.
- API mutations require `tournaments:write`, reads `tournaments:read`; bot uses its own API key,
  so audience restriction (admin-only) must be enforced **bot-side** via role check.

### Integration Points
- **New API streak endpoint** in `apps/api/routes/v3/tournaments.py` + `TournamentService`
  method (D-01).
- **New `APIService` wrappers** in `apps/bot/extensions/api_service.py` (streak, list_cycles,
  leaderboard, reroll, choose_map, list_categories).
- **New slash-command Cog** — likely added to `apps/bot/extensions/tournaments.py` (extend
  `setup` alongside `TournamentHandler`), or a sibling module; auto-loads before `rabbit.py`.

</code_context>

<specifics>
## Specific Ideas

- **User directive:** Leaderboard must paginate with **the project's own paginator**
  (`apps/bot/utilities/paginator.py`), **explicitly NOT discord-ext-menus**.
- **User directive:** Admin reroll cannot be a `/tournament` subcommand — Discord
  per-command permission limits force it to a **separate top-level `/tournament-reroll`**.
- **User directive:** Reroll should support an **optional explicit map code** (choose-map),
  not just random reroll.
- `/info` should be a rich card matching the Phase-9 new-cycle announcement; time shown as
  relative + absolute Discord timestamps.
- All responses ephemeral; empty states use friendly, specific copy.

</specifics>

<deferred>
## Deferred Ideas

- **Command-name variants** (`/tournament current` vs `info`, `/tournament lb`, `/tournament-admin`
  group) — user deferred to the defaults; revisit only if naming feedback arises.
- **Streak lookup for other users** (`user` arg) — considered in D-02, dropped in favor of
  self-only. Future enhancement if needed.
- **Live submission count on `/info`** — considered; dropped to avoid a new count field/endpoint.
- **Past-cycle / history browsing via slash command** — `list_cycles` could power a history
  view, but this phase is scoped to the **current** cycle. Future phase.
- **Confirmation step before reroll** — considered (D-14); dropped since reroll is repeatable.
- **Autocomplete of eligible maps for the reroll code arg** — considered (D-15); dropped in
  favor of `CodeAllTransformer` to avoid exposing an eligible-maps query to the bot. Revisit if
  admins want guided selection.

</deferred>

---

*Phase: 10-Bot Slash Commands*
*Context gathered: 2026-05-30*
