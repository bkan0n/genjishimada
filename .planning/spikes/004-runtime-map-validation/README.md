---
spike: 004
name: runtime-map-validation
type: standard
validates: "Given OverwatchMap Literal replaced by str + a runtime check against maps.names (plus the missing FK on core.maps.map_name), when an unknown map name is submitted, then it is rejected with a clear, Literal-equivalent error; known names pass; and the static-typing loss is characterized"
verdict: VALIDATED
related: [005, 006]
tags: [maps, msgspec, validation, asyncpg]
---

# Spike 004: runtime-map-validation

## What This Validates

> **Given** the `OverwatchMap` `Literal` is replaced by plain `str` plus a runtime check against
> `maps.names` (and the currently-missing FK on `core.maps.map_name`),
> **when** an unknown map name is submitted,
> **then** it is rejected with a clear, Literal-equivalent error; known names pass; and we can
> name exactly what static type-safety is sacrificed.

This is the crux of the whole idea. Today `MapCreateRequest.map_name: OverwatchMap` is a closed
`Literal`, and msgspec validates it strictly at decode time — so a brand-new map is **rejected at
the request boundary** until the SDK Literal is regenerated and every service redeploys. That single
fact is what blocks "appears automatically." This spike proves we can move the gate from the type
system (compile-time) to the database (runtime) without losing the rejection behaviour.

## Research

No external research needed — this is project-internal mechanics (msgspec + asyncpg), verified
empirically against the real schema rather than from docs. Key facts confirmed by the codebase
exploration and reconfirmed here:

- `OverwatchMap` is a `Literal[...]` in `libs/sdk/src/genjishimada_sdk/maps.py` (70 entries).
- msgspec validates `Literal` strictly: `Invalid enum value 'X' - at $.map_name`.
- `core.maps.map_name` is plain `text` with **no** FK/CHECK; validation is purely API-side.
- `maps.mastery.map_name` **does** have an FK to `maps.names.name`.

## How to Run

```bash
# from this directory
uv run --env-file ../../../.env.local --with asyncpg --with msgspec python validate.py
uv run --env-file ../../../.env.local --with asyncpg python fk_test.py          # rolled back; DB untouched
uv run --with basedpyright basedpyright typecheck_demo.py                        # shows the typing cost
```

Requires the local Docker Postgres up (`docker compose -f docker-compose.local.yml up -d postgres-local`),
which holds 63 real map names in `maps.names`.

## What to Expect

- `validate.py` — OLD Literal rejects a typo; NEW str path decodes everything, then the runtime
  DB check accepts known names and rejects unknowns *with a "did you mean" suggestion*.
- `fk_test.py` — 0 orphans today, FK adds cleanly, a bad `map_name` insert is rejected by the FK,
  a good one is accepted. All inside a rolled-back transaction.
- `typecheck_demo.py` — basedpyright errors on the `Literal` typo, stays silent on the `str` typo.

## Investigation Trail

1. **Reproduced OLD vs NEW side by side.** msgspec `Literal` rejection message is terse
   (`Invalid enum value 'Hanamuraa'`). The `str` field decodes *any* string — confirming the
   boundary stops blocking new maps, which is precisely the unblock we need.
2. **Runtime validation can be *better* than the Literal.** Added `difflib.get_close_matches` →
   `'Circ Royal' → Did you mean: Circuit Royal?`. The closed Literal could never suggest; the DB
   check can. This partly offsets the lost compile-time safety with better *runtime* DX.
3. **FK backstop.** Pre-flight orphan check returned **0** — the FK can be added directly today
   (no reconciliation migration needed *right now*, though the real migration must still guard for
   it). FK rejects bad inserts with a precise `DETAIL: Key (map_name)=(...) is not present`.
4. **Postgres transaction gotcha (surprise).** Catching the FK violation mid-transaction aborted
   the whole transaction (`InFailedSQLTransactionError`) and broke the next statement. Fix: wrap the
   fallible insert in a **SAVEPOINT** (`async with conn.transaction()` nested). The real service
   must do this if it catches constraint errors and continues.
5. **Static-typing cost, measured.** basedpyright flags `submit_with_literal("Hanamuraa")` and is
   silent on `submit_with_str("Hanamuraa")`. The loss is concrete and narrow: **hardcoded map-name
   string literals written in code are no longer typo-checked.** Map names flowing from the DB,
   requests, or the bot were never Literal-checked at runtime anyway.
6. **Drift discovery (the decisive finding).** Compared the SDK Literal against `maps.names`:
   **70 Literal entries vs 63 DB rows, with 7 maps in the Literal but absent from the DB**
   (Arena Victoriae, Gogadoro, Neon Junction, Place Lacroix, Powder Keg Mine, Redwood Dam, Thames
   District). The two "sources of truth" already disagree. Those 7 maps pass request validation but
   would fail the `maps.mastery` FK and never appear in autocomplete (which reads `maps.names`).
   The manual dual-maintenance process is *already* silently broken in production-like data.

## Results

**VALIDATED.** Replacing the `Literal` with `str` + a runtime `maps.names` check fully reproduces
the rejection of unknown maps and removes the request-boundary blocker, enabling automatic
appearance. Evidence:

- str field decodes any name (boundary no longer blocks); runtime check rejects unknowns with a
  clearer, suggestion-bearing error than msgspec's Literal message.
- FK on `core.maps.map_name → maps.names.name` adds cleanly (0 orphans today) and enforces integrity
  as defence-in-depth.
- The only thing lost is compile-time typo-checking of map-name *string literals in source code* —
  narrow, and partly recovered by runtime suggestions.

**Surprises / signal for the build:**
- **Single source of truth is not just nicer, it fixes a real bug.** The Literal and DB already
  drifted by 7 maps. DB-as-truth eliminates this entire class of inconsistency.
- **Add the FK, but guard the migration for orphans** (clean today, may not be on prod). Also add
  the FK *after* the runtime check, not instead of it — the runtime check gives the good error
  message; the FK is the backstop.
- **Use a SAVEPOINT** in the service when catching constraint violations inside a transaction.
- The 7 phantom Literal-only maps should be reconciled into `maps.names` as part of the real build.
