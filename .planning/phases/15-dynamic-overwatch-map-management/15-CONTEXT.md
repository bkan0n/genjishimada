# Phase 15: Dynamic Overwatch map management - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Let an admin add a new Overwatch map (name + banner) through **one API call** and
have it appear automatically on all three surfaces — website reads, map
submission, and bot slash commands — with **no code change and no redeploy**.

The crux: `OverwatchMap = Literal[...]` (`libs/sdk/src/genjishimada_sdk/maps.py`)
is validated strictly by msgspec at decode time, so it rejects any new map at the
request boundary until the SDK is regenerated and every service redeploys.
Replacing the Literal with `str` + runtime validation against `maps.names` moves
the gate from the type system to the DB, so a single `INSERT` makes a map appear
everywhere.

**In scope:**
- Drop the `OverwatchMap` Literal → `str` across the whole blast radius (28 files /
  ~109 lines); add service-layer runtime validation against `maps.names` + a
  `difflib` "did you mean" suggestion; add an FK backstop on `core.maps.map_name`.
- `POST /api/v3/content/maps` — mixed-multipart create (name + required banner).
- **Replace-banner** for an existing map (re-upload path).
- `GET /utilities/map-names → list[str]` full-list endpoint + DB-fed moderator
  `MapNameSelect` dropdown.
- Durability: idempotent `ON CONFLICT` seed in `0001_init.sql` + standalone
  on-demand export script; reconcile the 7 phantom Literal-only maps into
  `maps.names`.

**Out of scope (deferred):** renaming a map, deleting/archiving a map name, any
bot-side "add map" slash command (bot only *consumes* via autocomplete/dropdown).
</domain>

<decisions>
## Implementation Decisions

### Endpoint home & auth scope
- **D-01:** New write endpoint lives under the **content CMS namespace**:
  `POST /api/v3/content/maps`, guarded by the existing **`content:admin`** scope.
  Mirror the movement-tech CMS structure verbatim (Controller → Service →
  Repository): `routes/v3/content.py` `MovementTechController` pattern,
  `ContentService`, `ContentRepository`. (The movement-tech CMS is already fully
  built and uses `content:admin` — reuse it rather than minting a maps-domain
  scope.)
- **D-02:** The full-list read endpoint is `GET /utilities/map-names → list[str]`
  (all rows, `SELECT name FROM maps.names ORDER BY name`, no `search`, no `limit`).
  It is a **new** handler — the existing `/utilities/autocomplete/names`
  (search-required, similarity-ordered, `limit=5`) is for type-ahead and is NOT a
  substitute. The autocomplete endpoint stays unchanged.

### Phase scope boundary
- **D-03:** **Add + replace-banner.** Creating a new map (name + banner) and
  re-uploading/replacing the banner for an existing map are both in scope. Rename
  and delete are deferred to a future phase.

### Banner handling — OVERRIDES Spike 007
- **D-04:** Banner is **required** at create (single mixed-multipart request,
  `Struct{name: str, banner: UploadFile}`).
- **D-05:** **Store the banner at the stripped-name key**, matching the existing
  `get_map_banner()` derivation
  (`libs/sdk/src/genjishimada_sdk/maps.py:1013` — `re.sub(r"[^a-zA-Z0-9]","",name).lower()`
  → `assets/map_banners/{stripped}.png`). The read path
  (`get_map_banner()`, called at `maps.py:463`, `newsfeed.py:108`, bot
  `maps.py:103/218`) derives the banner URL on the fly, so storing at that same key
  makes new banners resolve through the existing path with **zero read-site
  changes**. The new `upload_map_banner(content, content_type, map_name) -> url`
  method keys the object by the stripped name (NOT a date+digest like
  `upload_screenshot`, NOT URL-encoded exact name).
- **D-06:** **DROP the `maps.names.banner_url` column** that Spike 007 proposed.
  It is redundant once D-05 keeps reads on `get_map_banner()`. The migration
  therefore needs **no new column** — only the FK + the idempotent-seed rewrite.
  > **Deliberate deviation from Spike 007**, which recommended `banner_url` to
  > avoid the lossy derived key. Rationale: consistency with the existing read
  > path and zero read-site churn outweigh defensive collision-safety for the
  > current real OW roster.
- **D-07:** **Collision guard at add time.** Because the stripped key is lossy
  (drops accents; squashes punctuation — `King's Row` and `Kings Row` →
  `kingsrow`), the create service MUST reject (HTTP **422**, `CustomHTTPException`)
  a new name whose stripped key already maps to a **different** existing map. This
  closes the exact collision risk Spike 007 raised, within the chosen design. (The
  empty/blank-name → 422 check from the spike also stays.)

### Durability & phantom maps
- **D-08:** **Reconcile the 7 phantom Literal-only maps into `maps.names`** so they
  become usable: Arena Victoriae, Gogadoro, Neon Junction, Place Lacroix, Powder
  Keg Mine, Redwood Dam, Thames District. (Today they pass Literal request
  validation but fail the `maps.mastery` FK and never appear in autocomplete — a
  real, pre-existing drift bug between the 70-entry Literal and the 63-row table.)
- **D-09:** Replace the plain `INSERT`s in `0001_init.sql` with **one idempotent
  `INSERT ... ON CONFLICT DO NOTHING` block** (also fixes a latent
  non-idempotency bug — today's seed errors on replay with a duplicate-PK
  violation). The committed seed is the from-migrations bootstrap source.
- **D-10:** Regenerate that seed from the live DB with a **standalone on-demand
  export script** — run manually, NOT wired into the nightly backup job, and
  **never** from the request path. Nightly prod backup + weekly dev refresh remain
  the **primary** recovery path for dynamically-added maps; the seed is for
  from-migrations bootstrap parity (new env / catastrophic DR without a backup).

### FK backstop
- **D-11:** Add `core.maps.map_name → maps.names.name` FK
  (`ON UPDATE CASCADE`) as **defence-in-depth, after** the service runtime check
  (the service check produces the good "did you mean" message; the FK only catches
  bugs/direct writes). **Guard the migration with an orphan pre-flight** —
  `SELECT DISTINCT m.map_name FROM core.maps m LEFT JOIN maps.names n ON n.name =
  m.map_name WHERE n.name IS NULL` (0 orphans locally, prod may differ).

### Claude's Discretion
- Exact internal layout of the new map-management service/repository (whether to
  extend `ContentService`/`ContentRepository` or add a dedicated maps-content
  module) — follow whichever best matches the movement-tech CMS structure.
- Image content-type validation depth on the banner upload (mirror
  `upload_image` / `ImageStorageService._ext_from_content_type`).
- The `request_max_body_size` value — default to `upload_image`'s 25 MB.
- Optional short-TTL bot cache for the full name list (the spike notes ~63 short
  strings is tiny; fetch-once-per-wizard-build is sufficient).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Feature blueprint (PRIMARY — read first)
- `Skill("spike-findings-genjishimada")` →
  `.claude/skills/spike-findings-genjishimada/references/dynamic-map-management.md`
  — the validated implementation blueprint (spikes 004–008, all VALIDATED). The
  single most important reference. NOTE the override: this CONTEXT's D-04..D-07
  supersede the spike's `banner_url`-column recommendation.
- `.claude/skills/spike-findings-genjishimada/sources/007-multipart-banner-upload/app.py`
  — real-Litestar mixed-multipart endpoint (proves `Struct{name, banner}` decodes
  in one request, msgspec boundary validation preserved).
- `.claude/skills/spike-findings-genjishimada/sources/008-moderator-mapname-dropdown/server.py`
  — verbatim-ported DB-fed paginated select (the moderator dropdown swap).
- `.claude/skills/spike-findings-genjishimada/sources/006-map-durability/maps_names.seed.sql`
  — the idempotent seed shape.

### Existing code to mirror / modify (from codebase scout)
- `apps/api/routes/v3/content.py` — `MovementTechController` + `content:admin`
  endpoints; the pattern to mirror for `POST /api/v3/content/maps`.
- `apps/api/services/content_service.py`, `apps/api/repository/content_repository.py`
  — CMS service/repo layering to follow.
- `apps/api/routes/v3/utilities.py:31` — `upload_image` multipart route (scope,
  `request_max_body_size=25MB`, `Body(media_type=RequestEncodingType.MULTI_PART)`).
- `apps/api/services/image_storage_service.py:44` — `upload_screenshot` (key
  derivation to NOT copy for banners); add a new `upload_map_banner` here.
- `libs/sdk/src/genjishimada_sdk/maps.py:1013` — `get_map_banner()` strip method
  (the stripped key D-05 must match); `:107` — the `OverwatchMap` Literal def.
- `apps/api/routes/v3/autocomplete.py` + `apps/api/repository/autocomplete_repository.py`
  — where `maps.names` is read; add the new full-list handler alongside.
- `apps/bot/utilities/transformers.py:21` — `MapNameTransformer` (already DB-backed).
- `apps/bot/extensions/moderator.py` — `MapNameSelect` (the one bot spot still on
  `get_args(OverwatchMap)`); `get_args(MapCategory)` in the same file STAYS a
  Literal.
- `apps/bot/extensions/api_service.py` — add `get_all_map_names()` client method
  alongside `get_autocomplete_map_names`.
- `apps/api/migrations/` — next migration number is **0032** (highest is
  `0031_skill_history.sql`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Movement-tech content CMS** (`routes/v3/content.py`, `ContentService`,
  `ContentRepository`) — fully built, `content:admin`-scoped; the exact template
  for the new add-map endpoint (D-01).
- **`upload_image` route** (`utilities.py:31`) — working multipart pattern (25 MB,
  `RequestEncodingType.MULTI_PART`) to mirror for the banner upload.
- **`ImageStorageService`** — add `upload_map_banner` here; reuse the
  `_ext_from_content_type` / S3 plumbing, just change the key derivation.
- **`MapNameTransformer`** (bot autocomplete) — already DB-backed; no change needed.
- **`maps.names`** table — the existing canonical source of truth all three
  surfaces already read.

### Established Patterns
- Three-layer Controller → Service → Repository with Litestar DI; raw asyncpg, no
  ORM; `$1,$2` positional params; `CustomHTTPException` for API errors; scope guard
  via `opt={"required_scopes": {...}}`.
- Banner URLs are **derived at read time** by `get_map_banner()`, not stored — D-05
  preserves this.
- Migrations are sequential SQL in `apps/api/migrations/NNNN_*.sql`.

### Integration Points
- **Request boundary:** `MapCreateRequest.map_name` (and ~11 other SDK fields) flip
  `OverwatchMap → str`; the runtime `maps.names` check becomes the single gate.
- **Storage:** new `upload_map_banner` writes the object at the stripped key under
  `assets/map_banners/`.
- **Bot:** `MapNameSelect.__init__` (sync `ui.Select`) must be fed the full list
  fetched once in the async wizard-build context — do NOT `await` inside `__init__`.
- **DB:** new FK on `core.maps.map_name`; rewritten idempotent seed in
  `0001_init.sql`.

</code_context>

<specifics>
## Specific Ideas

- The banner filename **must** be the stripped-name variant because those URLs are
  derived dynamically when fetching map data (`get_map_banner()`). This is the
  user's explicit direction and the reason the `banner_url` column is dropped
  (D-05/D-06).
- Keep `get_args(MapCategory)` on its Literal — only the *map-name*
  `get_args(OverwatchMap)` usage in `moderator.py` becomes DB-fed.
- Watch the transaction-abort gotcha: catching an FK/unique violation mid-statement
  poisons the Postgres transaction — wrap fallible statements in a SAVEPOINT
  (`async with conn.transaction():`) or the next statement raises
  `InFailedSQLTransactionError`.

</specifics>

<deferred>
## Deferred Ideas

- **Rename a map** (interacts with the `core.maps` FK `ON UPDATE CASCADE` and the
  stripped banner key) — future phase.
- **Delete / archive a map name** (must handle dependent `maps.mastery` /
  `core.maps` rows) — future phase.
- **Bot-side "add map" slash command** — adding stays API/dashboard-only this
  phase; the bot only consumes (autocomplete + dropdown). A moderator add-from-
  Discord command could be a later convenience.
- **Wiring the seed export into the nightly backup job** — considered (D-10) and
  deferred in favour of an on-demand script; could be automated later if manual
  regeneration proves error-prone.
- **Forward-looking `banner_url` column for arbitrary keys** — considered (D-06)
  and rejected for now; revisit only if a real future map genuinely needs a
  non-strippable key.

</deferred>

---

*Phase: 15-dynamic-overwatch-map-management*
*Context gathered: 2026-06-25*
