---
phase: quick-260531-wbe
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/services/tournament_outbox_service.py
  - apps/api/tests/repository/tournaments/test_outbox_poller.py
  - apps/bot/extensions/tournaments.py
autonomous: true
requirements: [TOURN-CV2-ANNOUNCE, TOURN-BATCH-CYCLES]

must_haves:
  truths:
    - "A multi-category rotation produces exactly ONE cycle-started announcement and ONE cycle-completed results announcement (not one per category)."
    - "The combined started card shows a per-category section for every category that rotated, each with map link, difficulty, and ends-at."
    - "The combined results card transfers every category's champion role FIRST, then posts one gold card with a per-category podium and crowns all winners in a single ping."
    - "Per-cycle XP grants, streak advancement, and non-participant streak resets are still applied once per cycle (unchanged invariant)."
    - "/tournament info, /tournament streak, and /tournament-reroll render as CV2 LayoutViews; the announcement cards carry a static placeholder hero image; no map_banner appears on any tournament surface."
    - "Users are mentioned only by numeric <@id>; free-text entry.name / standings name is never interpolated into a mention; sends use AllowedMentions(everyone=False, roles=False) with an explicit winner allow-list."
  artifacts:
    - path: "libs/sdk/src/genjishimada_sdk/tournaments.py"
      provides: "TournamentCyclesStartedEvent / TournamentCyclesCompletedEvent batch structs"
      contains: "class TournamentCyclesStartedEvent"
    - path: "apps/api/services/tournament_outbox_service.py"
      provides: "Grouped publish of pending transitions on plural routing keys"
      contains: "api.tournament.cycles_started"
    - path: "apps/bot/extensions/tournaments.py"
      provides: "CV2 batch announcement consumers + CV2 command cards + static gallery image"
      contains: "_TOURNAMENT_GALLERY_IMAGE"
  key_links:
    - from: "apps/api/services/tournament_outbox_service.py"
      to: "apps/bot/extensions/tournaments.py"
      via: "RabbitMQ routing keys api.tournament.cycles_started / api.tournament.cycles_completed"
      pattern: "api\\.tournament\\.cycles_(started|completed)"
    - from: "apps/api/services/tournament_outbox_service.py"
      to: "genjishimada_sdk.tournaments.TournamentCyclesStartedEvent"
      via: "msgspec event struct published per (event_type, created_at) group"
      pattern: "TournamentCycles(Started|Completed)Event"
---

<objective>
Replace dated Discord embeds on tournament alert/announcement surfaces with Components V2 (LayoutView) cards, and batch the per-category cycle lifecycle events into ONE combined announcement each. A single pg_cron rotation (`tournaments.process_cycle_transitions()`, migration 0021) writes one `cycle_started` + one `cycle_completed` row per due category, all sharing the SAME transaction `created_at`. The outbox poller currently publishes each row separately; this plan groups rows by `(event_type, created_at)` and publishes ONE combined event per group on new plural routing keys, then renders one combined card per group on the bot.

Purpose: Stop spamming N separate announcements when several categories rotate together; modernise the rendering to CV2 cards with a static tournament hero image.

Output:
- Two new SDK batch structs reusing the existing single-cycle structs as list entries.
- A grouped publish loop in the outbox service (no SQL migration, no schema/pg_cron change).
- Two CV2 batch announcement consumers + three CV2 command cards on the bot.
- Updated outbox poller test asserting the new grouped routing/idempotency contract.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@./CLAUDE.md

<interfaces>
<!-- Extracted from the codebase. Executor uses these directly — no exploration needed. -->

Existing single-cycle SDK structs (libs/sdk/src/genjishimada_sdk/tournaments.py) — KEEP, they become per-entry types:
```python
class TournamentCycleStartedEvent(Struct):
    cycle_id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    started_at: dt.datetime
    ends_at: dt.datetime

class TournamentCycleCompletedEvent(Struct):
    cycle_id: int
    category_id: int
    standings: list[TournamentLeaderboardEntryResponse]
    winner_user_id: int | None

class TournamentLeaderboardEntryResponse(Struct):
    rank: int
    user_id: int
    name: str
    time: float
    verified: bool
    completion: bool
```

Outbox poller (apps/api/services/tournament_outbox_service.py) — current per-row loop in `publish_pending_transitions`:
- `_EVENT_ROUTING: dict[str, tuple[str, type[msgspec.Struct]]]` maps `cycle_started`/`cycle_completed` to singular routing key + single struct.
- `_build_event(row)` → `(routing_key, event)` via `msgspec.convert(row["payload"], struct_type)`.
- For each `cycle_completed` row: `pending_xp_events += await reward_service.award_cycle_end(event, conn=conn)` then `await _reset_non_participant_streaks(repository, event, conn=conn)`. AFTER commit: `await reward_service.publish_xp_events(pending_xp_events)`. THIS PER-CYCLE BEHAVIOR IS A CRITICAL INVARIANT.
- Publish-before-mark inside one `async with pool.acquire() as conn, conn.transaction():` (at-least-once).
- `repository.fetch_unpublished_transitions` already does `SELECT *` → row dicts already expose `created_at`. NO repository change required.

CV2 idiom already in this same bot file (TournamentVerificationView._rebuild_components):
```python
container = ui.Container(
    ui.TextDisplay(details),
    ui.Separator(),
    ui.MediaGallery(MediaGalleryItem(self.event.screenshot)),
    ui.ActionRow(...),
)
self.add_item(container)
```
Imports already present in tournaments.py: `from discord import AllowedMentions, ButtonStyle, MediaGalleryItem, TextChannel, app_commands, ui`.

Bot helpers reused unchanged:
- `self.bot.api.get_tournament_category(category_id) -> TournamentCategoryResponse` (has `.name`, `.champion_role_id`, `.cycle_frequency`).
- `self.bot.api.get_map(code=...) -> ` map data with `.difficulty` (and old `.map_banner` — to be DROPPED from tournament surfaces).
- `_WORKSHOP_URL = "https://workshop.codes/{code}"`, `_PODIUM_SIZE = 3`.
- `_transfer_champion_role(entry, category)` — per-cycle signature UNCHANGED; `entry` is a `TournamentCycleCompletedEvent`.

Existing outbox test (apps/api/tests/repository/tournaments/test_outbox_poller.py) currently asserts SINGULAR keys (`tournament:cycle_started:{cycle_id}`, routing `api.tournament.cycle_started`). It MUST be updated to the new grouped contract.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add batch SDK structs</name>
  <files>libs/sdk/src/genjishimada_sdk/tournaments.py</files>
  <behavior>
    - `msgspec.json.decode(b'{"cycles":[<one valid started entry>]}', type=TournamentCyclesStartedEvent)` yields a struct whose `.cycles[0]` is a `TournamentCycleStartedEvent`.
    - Same for `TournamentCyclesCompletedEvent` wrapping `TournamentCycleCompletedEvent`.
    - Both new names are importable from `genjishimada_sdk.tournaments` and listed in `__all__`.
  </behavior>
  <action>
In the "Event types (RabbitMQ)" section (after the existing `TournamentCycleStartedEvent` / `TournamentCycleCompletedEvent` definitions), add two new `Struct` subclasses: `TournamentCyclesStartedEvent` with a single field `cycles: list[TournamentCycleStartedEvent]`, and `TournamentCyclesCompletedEvent` with `cycles: list[TournamentCycleCompletedEvent]`. KEEP the existing single-cycle structs unchanged — they become the per-entry element type. Add Google-style class docstrings (D-rules apply: one-line summary + `Attributes:` block describing `cycles`). Add both new names to the `__all__` tuple (keep it alphabetically sorted: `TournamentCyclesCompletedEvent` and `TournamentCyclesStartedEvent` slot in after `TournamentCycleWithWinnerResponse`). Do NOT remove or rename any existing struct.
  </action>
  <verify>
    <automated>just lint-sdk</automated>
  </verify>
  <done>`just lint-sdk` passes (Ruff + BasedPyright strict); both batch structs exist with `cycles` list fields and appear in `__all__`. If a later task's import of `genjishimada_sdk` fails with ModuleNotFoundError, run `just fix` to reinstall the workspace SDK.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Group outbox rows into one combined event per rotation</name>
  <files>apps/api/services/tournament_outbox_service.py, apps/api/tests/repository/tournaments/test_outbox_poller.py</files>
  <behavior>
    - Two `cycle_started` rows sharing the same `created_at` → exactly ONE publish on `api.tournament.cycles_started`, with idempotency key `tournament:cycles_started:{created_at_iso}`, carrying a `cycles` list of length 2; BOTH rows marked published.
    - Two `cycle_completed` rows sharing one `created_at` → ONE publish on `api.tournament.cycles_completed`; both rows marked published; `reward_service.award_cycle_end` and `_reset_non_participant_streaks` are each invoked ONCE PER ROW (per cycle), and deferred XP events still publish after commit.
    - A malformed payload row still raises `msgspec.ValidationError` and leaves its group unmarked (at-least-once preserved).
    - Unknown `event_type` still raises `KeyError` via the routing map.
  </behavior>
  <action>
Edit ONLY `tournament_outbox_service.py` (no repository change — `fetch_unpublished_transitions` already SELECTs `*`, so `created_at` is present in each row dict).

1) Replace the `_EVENT_ROUTING` entries with the PLURAL routing keys mapped to the new batch structs: `"cycle_started" -> ("api.tournament.cycles_started", TournamentCyclesStartedEvent)` and `"cycle_completed" -> ("api.tournament.cycles_completed", TournamentCyclesCompletedEvent)`. Update the import from `genjishimada_sdk.tournaments` to add `TournamentCyclesStartedEvent` and `TournamentCyclesCompletedEvent` (keep the single-cycle imports — still needed to convert each row payload). Keep the module docstring accurate (mention grouping by `(event_type, created_at)`).

2) In `publish_pending_transitions`, KEEP the existing per-row side-effect loop EXACTLY for the XP/streak invariant. The recommended structure: iterate `rows` once; for each row, `msgspec.convert(row["payload"], <single-cycle struct for that event_type>)` into a per-cycle event, and append it to a `dict` keyed by `(row["event_type"], row["created_at"])` (also stash the row `id` per group so all group rows can be marked). For each `cycle_completed` row, STILL call `pending_xp_events += await reward_service.award_cycle_end(event, conn=conn)` and `await _reset_non_participant_streaks(repository, event, conn=conn)` exactly as today — these run PER CYCLE, not per group.

3) After grouping, for each `(event_type, created_at)` group: build ONE batch event (`TournamentCyclesStartedEvent(cycles=[...])` or `TournamentCyclesCompletedEvent(cycles=[...])`), resolve its plural routing key via `_EVENT_ROUTING`, then `await service.publish_message(routing_key=..., data=batch_event, headers=Headers({}), idempotency_key=f"tournament:{event_type}:{created_at.isoformat()}")` ONCE, then `await repository.mark_transition_published(row_id, conn=conn)` for EVERY row id in that group — all inside the SAME transaction (publish-before-mark preserved). Keep `await reward_service.publish_xp_events(pending_xp_events)` AFTER the transaction commits, unchanged.

4) Decide how `_build_event` fits: either repurpose it to return the SINGLE-cycle `(routing_key_unused, per_cycle_event)` for conversion, or inline `msgspec.convert` and keep a small helper that maps an `event_type` to its single-cycle struct. Whichever you choose, the `TestBuildEvent::test_invalid_event_type_rejected` test must still get a `KeyError` for an unknown `event_type` — preserve a routing/struct lookup that raises `KeyError` on unknown types (adjust that test only if you change the helper's signature, keeping the KeyError-on-unknown contract).

5) Update `apps/api/tests/repository/tournaments/test_outbox_poller.py` to the new contract: assertions on routing keys become `api.tournament.cycles_started` / `api.tournament.cycles_completed`; idempotency keys become `tournament:cycles_started:{created_at_iso}` / `tournament:cycles_completed:{created_at_iso}`. Because each rotation's rows must share a `created_at` to group, seed grouped rows with an explicit identical `created_at` (extend `_seed_transition` to accept/insert a `created_at` and pass the same value for rows in one logical rotation; the table column accepts an explicit insert). Update `TestPublishAndMark` to assert ONE publish per group whose `data.cycles` length matches the number of seeded rows in that group, and both rows marked published. Keep `TestSkipLocked`, `TestPublishFailure`, `TestPoolNotReady`, and `TestCycleEndRewardHook` semantically intact — adjust only the key/routing/`created_at` plumbing they touch (the per-cycle `award_cycle_end` invocation assertions must still pass unchanged). If `TestBuildEvent` references a changed helper, update it minimally to preserve the KeyError-on-unknown-type assertion.
  </action>
  <verify>
    <automated>uv run --directory apps/api pytest tests/repository/tournaments/test_outbox_poller.py -v -p no:xdist</automated>
  </verify>
  <done>The outbox poller test file passes with the grouped contract; a multi-row rotation produces one publish per `(event_type, created_at)` group on the plural routing key, all rows marked published, and `award_cycle_end` + streak reset still invoked once per cycle. `just lint-api` passes.</done>
</task>

<task type="auto">
  <name>Task 3: CV2 batch announcement consumers (started + completed)</name>
  <files>apps/bot/extensions/tournaments.py</files>
  <action>
Edit `apps/bot/extensions/tournaments.py`. Add a module constant near `_WORKSHOP_URL`: `_TOURNAMENT_GALLERY_IMAGE = "<placeholder image URL>"` with a `# TODO: swap for real tournament artwork` comment. Update the imports from `genjishimada_sdk.tournaments` to add `TournamentCyclesStartedEvent` and `TournamentCyclesCompletedEvent` (keep the single-cycle imports — `TournamentCycleStartedEvent`/`TournamentCycleCompletedEvent` remain the per-entry types and `_transfer_champion_role` still takes a `TournamentCycleCompletedEvent`).

Replace `_on_cycle_started`: re-decorate as `@queue_consumer("api.tournament.cycles_started", struct_type=TournamentCyclesStartedEvent, idempotent=True)`. Signature receives the batch event. Build ONE `ui.LayoutView` containing a single `ui.Container(accent_color=discord.Color.blurple())`. Container children in order: a header `ui.TextDisplay` ("# 🏆 New Tournament Cycle" plus a short blurb), one hero `ui.MediaGallery(MediaGalleryItem(_TOURNAMENT_GALLERY_IMAGE))`, then for EACH `entry` in `event.cycles`: a `ui.Separator()` followed by a `ui.TextDisplay` section with `### {category.name}`, the map link `[{entry.map_name}]({_WORKSHOP_URL.format(code=entry.map_code)})` plus a backtick-wrapped `{entry.map_code}`, the difficulty, and an "Ends" line using `discord.utils.format_dt(entry.ends_at, "R")` and `discord.utils.format_dt(entry.ends_at, "F")`. Fetch per entry: `category = await self.bot.api.get_tournament_category(entry.category_id)` and `map_data = await self.bot.api.get_map(code=entry.map_code)` (use `map_data.difficulty`; DROP `map_banner`). Post once via `await self.announcement_channel.send(view=view, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False))`. A missing map should still propagate (DLQ) as today.

Replace `_on_cycle_completed`: re-decorate as `@queue_consumer("api.tournament.cycles_completed", struct_type=TournamentCyclesCompletedEvent, idempotent=True)`. ORDERING (Pitfall 5): FIRST loop `for entry in event.cycles:` fetch `category = await self.bot.api.get_tournament_category(entry.category_id)` and call `await self._transfer_champion_role(entry, category)` (entry is a per-cycle `TournamentCycleCompletedEvent`, signature unchanged). THEN build and post ONE results card LAST: a `ui.LayoutView` with `ui.Container(accent_color=discord.Color.gold())`, header `ui.TextDisplay`, hero `ui.MediaGallery(MediaGalleryItem(_TOURNAMENT_GALLERY_IMAGE))`, then per entry a `ui.Separator()` + `ui.TextDisplay` section: `### {category.name}`; when `entry.winner_user_id is not None` append `— 👑 <@{entry.winner_user_id}>`; podium rows `` `#{e.rank}` <@{e.user_id}> — {e.time:.2f}s `` for `e in entry.standings[:_PODIUM_SIZE]`, or "No submissions" when empty. Aggregate ALL non-None `winner_user_id`s into both the content ping (space-joined `<@id>` mentions, or `None` if no winners) and the allow-list (`[discord.Object(id=w) for w in winners]`). Post once via `await self.announcement_channel.send(content=content, view=view, allowed_mentions=discord.AllowedMentions(users=allowed_users, everyone=False, roles=False))`.

SECURITY (T-10-10 / T-11-19): mention users ONLY by numeric `<@id>`; NEVER interpolate `entry.name` / standings `name` into a mention; the AllowedMentions allow-list contains only the numeric winner ids. Remove ALL `map_banner` / `set_thumbnail` usage from the started/completed handlers. Re-cache the category fetch within `_on_cycle_completed` so the SAME category object is reused for transfer and rendering per entry (avoid a double fetch per cycle if convenient, but correctness over micro-optimisation).
  </action>
  <verify>
    <automated>just lint-bot</automated>
  </verify>
  <done>`just lint-bot` passes; both consumers subscribe to the plural routing keys, decode the batch structs, render one CV2 LayoutView each (blurple started / gold completed) with the static hero image and one Separator-delimited section per category; champion transfer runs once per cycle BEFORE the single results post; all winners aggregated into one ping with a numeric-only allow-list; no `map_banner` remains on these surfaces.</done>
</task>

<task type="auto">
  <name>Task 4: CV2 command cards (info, streak, reroll)</name>
  <files>apps/bot/extensions/tournaments.py</files>
  <action>
Convert three command responses from `discord.Embed` to CV2 `ui.LayoutView`s sent via `itx.edit_original_response(view=...)`. NO hero image on these three (lightweight). Preserve ALL existing data-fetch, the locally-computed `ends_at`, zero-state copy, and the reroll mod-gate logic UNCHANGED — only the rendering changes.

`/tournament info` (`TournamentCommandCog.info`): build a `ui.LayoutView` with `ui.Container(accent_color=discord.Color.blurple())`. Keep the existing fetch (`get_tournament_category`, `list_tournament_cycles(status="active", ...)`, the no-active-cycle short-circuit, `get_map`, and the local `ends_at` computation from `started_at` + 7/14 days by `cycle_frequency`). Container content via `ui.TextDisplay`(s): a `# Active Tournament Cycle: {category_data.name}` header, the map link `[{active.map_name}]({_WORKSHOP_URL.format(code=active.map_code)})` + `` `{active.map_code}` ``, difficulty (`map_data.difficulty`), category, and (when `active.started_at is not None`) an "Ends" line with `format_dt(ends_at,'R')` and `format_dt(ends_at,'F')`. DROP the `map_banner` thumbnail. The no-active-cycle branch stays a plain content edit (no view).

`/tournament streak` (`TournamentCommandCog.streak`): build a `ui.LayoutView` with `ui.Container(accent_color=discord.Color.green())`. Keep the 404→zero-state handling exactly (current 0 / max 0 with the "Submit in a cycle to start your streak!" copy when both are 0; re-raise any non-404 `APIHTTPError`). Render a `# Your Tournament Streak` header plus current/max lines via `ui.TextDisplay`.

`/tournament-reroll` (`TournamentRerollCog.tournament_reroll`): build a `ui.LayoutView` with `ui.Container(accent_color=discord.Color.blurple())`. KEEP the mod-gate (`UserFacingError` before any API write — D-07) and the reroll/choose branching UNCHANGED. Render `# Next-Cycle Map Updated`, the map link + code, and difficulty (`result.map_difficulty`) via `ui.TextDisplay`.

Leave `/tournament leaderboard` and `TournamentLeaderboardPaginator` UNTOUCHED (already CV2). Leave `TournamentVerificationView` UNTOUCHED (already CV2).
  </action>
  <verify>
    <automated>just lint-bot</automated>
  </verify>
  <done>`just lint-bot` passes; info (blurple), streak (green), and reroll (blurple) all render via `ui.LayoutView` through `edit_original_response(view=...)`; all data-fetch, local `ends_at`, zero-state copy, and the reroll mod-gate are byte-for-byte preserved in behavior; no `map_banner` remains on these surfaces; leaderboard/verification views are unchanged.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| RabbitMQ → bot consumer | Event payloads (incl. free-text `name`) cross from API/DB into Discord rendering |
| Discord message render | Mentions in card content can ping users/roles/@everyone |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-10-10 | Tampering/Elevation | tournament leaderboard/results render | mitigate | Mention users ONLY by numeric `<@id>`; never interpolate `entry.name`/standings `name` into a mention (preserved from existing code). |
| T-11-19 | Elevation (mention injection) | announcement/results `channel.send` | mitigate | `discord.AllowedMentions(users=[numeric winner ids], everyone=False, roles=False)` on every announcement/results post; winners aggregated as numeric ids only. |
| T-WBE-01 | Spoofing (dup events) | outbox publish-before-mark | accept | Batch idempotency key `tournament:{event_type}:{created_at_iso}` is stable per rotation across poller retries; `@queue_consumer(idempotent=True)` dedupes downstream (at-least-once accepted by design, D-11). |
| T-WBE-02 | Tampering (XP invariant drift) | grouped poller loop | mitigate | Per-cycle `award_cycle_end` + `_reset_non_participant_streaks` + deferred `publish_xp_events` kept EXACTLY; test `TestCycleEndRewardHook` asserts per-cycle invocation. |
</threat_model>

<verification>
- `just lint-sdk` — SDK structs typecheck/format.
- `uv run --directory apps/api pytest tests/repository/tournaments/test_outbox_poller.py -v -p no:xdist` — grouped publish contract, XP/streak invariant, skip-locked, publish-failure, pool-not-ready.
- `just lint-api` — outbox service + test format/typecheck.
- `just lint-bot` — both consumers + three command cards.
- SDK rebuild caveat: if any bot/api import of `genjishimada_sdk` fails with `ModuleNotFoundError`, run `just fix` to reinstall the workspace, then re-run the failing lint/test.
</verification>

<success_criteria>
- One `cycle_started` and one `cycle_completed` row per category share a transaction `created_at`; the poller publishes ONE combined event per `(event_type, created_at)` group on `api.tournament.cycles_started` / `api.tournament.cycles_completed`, and marks every row in the group published in the same transaction.
- Per-cycle XP grant, streak advance, and non-participant streak reset behavior is unchanged (one per cycle).
- Bot renders ONE blurple started card and ONE gold results card per rotation, each with a static hero image and a Separator-delimited section per category; champion role transfers run once per cycle BEFORE the single results post; all winners aggregated into one numeric-only ping.
- `/tournament info`, `/tournament streak`, `/tournament-reroll` render as CV2 LayoutViews; no `map_banner` on any tournament surface.
- No SQL migration, no `pending_transitions` schema change, no pg_cron change.
- All four verify commands pass.
</success_criteria>

<output>
Create `.planning/quick/260531-wbe-tournament-cv2-announcements-single-even/260531-wbe-SUMMARY.md` when done.
</output>
