---
spike: 008
name: moderator-mapname-dropdown
type: standard
validates: "Given the moderator MapNameSelect dropdown, when its source switches from get_args(OverwatchMap) to the live maps.names (full sorted list, 25/page), then it shows all maps including dynamically-added ones with no bot restart, grows pages correctly, and no longer depends on the SDK Literal — and we confirm a full-list names endpoint must be added"
verdict: VALIDATED
related: [004, 005, 007]
tags: [maps, bot, ui, pagination]
---

# Spike 008: moderator-mapname-dropdown

## What This Validates

> **Given** the moderator map-edit wizard's `MapNameSelect` dropdown,
> **when** its source switches from `get_args(OverwatchMap)` to the live `maps.names`
> (full sorted list, paginated 25/page — Discord's option cap),
> **then** it shows **all** maps including dynamically-added ones with **no bot restart**, grows its
> page count correctly as the table grows, and no longer depends on the SDK `Literal`.

This is the **one bot spot the Literal removal (Spike 004) would silently break.** The bot's
autocomplete path (`MapNameTransformer`, `apps/bot/utilities/transformers.py:21`) is already DB-backed
via the API, but `MapNameSelect` (`apps/bot/extensions/moderator.py:756-779`) still builds its
paginated dropdown from `list(get_args(OverwatchMap))`. After the Literal becomes `str`, that call
returns nothing useful and the dropdown can never show new maps. It must read the DB.

## Research

No external research — this is project-internal bot mechanics. Two facts established by reading the
real code first:

1. **The pagination math to preserve** (`moderator.py:768-779`, page size `_PAGINATED_SELECT_PAGE_SIZE
   = 25` at line 461):
   ```python
   all_maps = list(get_args(OverwatchMap)); all_maps.sort()
   start = page * SIZE; end = start + SIZE; page_maps = all_maps[start:end]
   total_pages = (len(all_maps) + SIZE - 1) // SIZE
   ```
   This spike ports it **verbatim**, swapping only the source of `all_maps`.

2. **The API gap (decisive):** there is **no full-list map-names endpoint** today. The closest,
   `GET /utilities/autocomplete/names` (`apps/api/routes/v3/autocomplete.py:21`), **requires** a
   `search` arg, is similarity-ordered, defaults to `limit=5`, and returns `list[OverwatchMap]` —
   built for type-ahead, useless as a full paginated source. The model to follow is the same
   controller, but a new handler is needed (see Signal).

## How to Run

```bash
# from this directory; requires docker compose -f docker-compose.local.yml up -d postgres-local
uv run --env-file ../../../.env.local --with asyncpg python -u server.py
# open http://localhost:8077 — page the dropdown, add a map, watch it appear; Ctrl-C to stop (auto-cleans)
```

**Isolation:** throwaway `spike008` schema seeded from `maps.names` (63 maps); dropped in `main()`'s
`finally` on Ctrl-C. SIGINT the **listener** PID (`lsof -ti tcp:8077`), not the `uv` wrapper, so
cleanup runs. Real data untouched (verified: `maps.names` still 63 after).

## What to Expect

- A Discord-styled paginated select fed by `SELECT name FROM <schema>.names ORDER BY name`.
- Prev/Next paging; placeholder shows `(page N)`; page count = `ceil(total/25)`.
- An "add a map" box that `INSERT … ON CONFLICT DO NOTHING` into the live DB — the dropdown reflects
  it on the next render with **no restart**, including spilling onto a new page when the table grows
  past a 25-boundary.

## Observability

In-memory forensic log at `GET /api/log` (categories `setup`/`select`/`add`/`teardown`): every page
render logs `page / shown / total`, every insert logs `name / inserted`. Makes the "DB is the source"
claim auditable as you click.

## Investigation Trail

1. **Ported the exact pagination, DB-fed.** `build_select_page()` is `MapNameSelect.__init__`'s math
   line-for-line, with `all_maps` from the DB. Page 0 → 25 options, `total_pages=3`, `total_maps=63`,
   placeholder `Select map name (page 1)...` — matches the real component's contract.
2. **Last page partial-fill correct.** Page 2 → 13 options (63−50), last = `Workshop Island`. The
   `ceil` page-count and slice arithmetic behave identically to the static version.
3. **Dynamic pickup, no restart (the core claim).** Inserted `ZZZZ Edge Map` → `total_maps` 63→64 and
   it appears live on the last page (`present: True`) without restarting the "select". Re-adding an
   existing name (`Aatlis`, already a real seeded map) → `inserted:false`, idempotent.
4. **Page-boundary growth proven concretely, not just by formula.** Added 12 maps to cross the 75→76
   boundary → `total_pages` flipped **3 → 4** and page index 3 materialized with 1 option
   (`Zzz Page Filler 12`). A brand-new page appears purely from a DB insert — exactly the behaviour
   the static Literal could never have.
5. **Confirmed the API gap.** Re-read `autocomplete.py`: no full-list handler exists; the autocomplete
   endpoint is search-required + `limit=5` + similarity-ordered + `list[OverwatchMap]`-typed. A full
   sorted list cannot be obtained from it. A new endpoint must be added for the dropdown.
6. **Verified clean teardown.** Ctrl-C → schema dropped, `spike008 exists: False`, `maps.names` still
   63. Exit 0.

## Results

**VALIDATED.** The moderator dropdown works fully DB-fed: the verbatim-ported 25/page pagination
behaves identically to the Literal version, reflects live inserts with no bot restart, and grows its
page count correctly. The only real work is sourcing `all_maps` from the API/DB instead of
`get_args(OverwatchMap)` — and adding the full-list endpoint that doesn't exist yet.

**Signal for the build:**
- **Add a full-list names endpoint.** New handler on the existing `AutocompleteController` (or maps
  controller), e.g. `GET /utilities/map-names` → `list[str]` returning `SELECT name FROM maps.names
  ORDER BY name` (all rows, no `search`, no `limit`). Return type becomes `list[str]` once the
  `OverwatchMap` Literal is dropped (Spike 004). The existing search/`limit=5` autocomplete stays for
  type-ahead — it is *not* a substitute for the dropdown's full list.
- **Bot client method + `MapNameSelect` change.** Add `api_service.get_all_map_names() -> list[str]`
  alongside the existing `get_autocomplete_map_names`. In `MapNameSelect.__init__`, replace
  `all_maps = list(get_args(OverwatchMap)); all_maps.sort()` with the fetched-and-sorted DB list.
  Keep the rest (slice, `total_pages`, `SelectOption`) **unchanged** — it's correct as-is.
- **Fetch timing / caching.** `MapNameSelect.__init__` is sync (a discord.py `ui.Select` subclass), so
  it can't `await`. Fetch the full list **once** when the wizard view is built (async context) and
  pass it into the paginated select's constructor — don't query per page-flip. ~63 short strings is
  tiny; a short-TTL cache on the bot is optional, not required.
- **Drop the `OverwatchMap` import** from `moderator.py` once both `MapCategory`-style `get_args`
  usages are separated — note `get_args(MapCategory)` (line 743) is a *different*, legitimately-static
  Literal and stays; only the map-name one moves to the DB.
- **No Discord-runtime risk found.** The change is purely the data source; pagination, the 25-option
  cap, and `SelectOption` construction are untouched and already correct.
