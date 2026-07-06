# Phase 15: Dynamic Overwatch Map Management - Research

**Researched:** 2026-06-25
**Domain:** Litestar REST API + AsyncPG + msgspec; runtime-vs-type-system validation; S3 banner storage; discord.py UI; SQL migrations
**Confidence:** HIGH (all claims verified against live codebase grep/reads + VALIDATED spikes 004–008)

## Summary

This phase removes the single static gate — `OverwatchMap = Literal[...]` in
`libs/sdk/src/genjishimada_sdk/maps.py:107` — that forces an SDK regen + full redeploy every time
an Overwatch map is added. msgspec validates that Literal strictly at decode time, so it rejects
any unknown map at the request boundary. Flipping the field type to `str` moves the gate from the
type system to the database: a single `INSERT INTO maps.names` then makes a new map appear on all
three surfaces (website reads, map submission, bot autocomplete/dropdown) with no code change and
no restart. The validation work that the Literal did for free moves to a service-layer runtime
check against `maps.names`, which can additionally produce a `difflib` "did you mean" suggestion
the closed Literal never could.

The blast radius is **28 files** touching `OverwatchMap`, but the live (non-test) flip is small:
the Literal definition itself, ~12 SDK struct fields, a handful of API repo/route/service type
hints, bot type hints, and **exactly one** behavioural change — the moderator
`MapNameSelect.__init__` which sources its options from `list(get_args(OverwatchMap))`
(`apps/bot/extensions/moderator.py:768`). Everything else is a type-annotation swap that produces
no runtime behaviour change (msgspec already decodes `str`; the bot's `MapNameTransformer` and the
autocomplete endpoint already read `maps.names` at runtime). **`get_args(MapCategory)` and every
other Literal `get_args(...)` call stays untouched** — only the map-name usage moves to the DB.

The add-map endpoint mirrors the fully-built movement-tech content CMS (Controller → Service →
Repository, `content:admin` scope) and the existing `upload_image` multipart route. Spike 007
proved on real Litestar that a mixed multipart body (`Struct{name: str, banner: UploadFile}`)
decodes in one request with msgspec boundary validation preserved. Banner storage (per
CONTEXT.md D-04..D-07, **which overrides Spike 007's `banner_url` column**) writes the object at
the stripped-name key matching `get_map_banner()` so reads need zero changes; the lossy-key
collision risk Spike 007 raised is closed by a service-layer 422 collision guard at add time.

**Primary recommendation:** Flip `OverwatchMap` → `str` SDK-wide; add a `content:admin`-scoped
`POST /api/v3/content/maps` mixed-multipart endpoint (create + replace-banner) with service-layer
runtime validation, a stripped-key collision guard (422), and a stripped-key banner upload; add
`GET /utilities/map-names → list[str]`; swap the bot's `MapNameSelect` to the DB-fed list; ship
migration `0032` with an orphan-guarded FK on `core.maps.map_name`, an idempotent `ON CONFLICT`
seed rewrite in `0001_init.sql`, and reconciliation of the 7 phantom Literal-only maps.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** New write endpoint lives under the content CMS namespace: `POST /api/v3/content/maps`,
  guarded by the existing `content:admin` scope. Mirror the movement-tech CMS structure verbatim
  (Controller → Service → Repository): `routes/v3/content.py` `MovementTechController` pattern,
  `ContentService`, `ContentRepository`. (Reuse `content:admin` — do not mint a maps-domain scope.)
- **D-02:** The full-list read endpoint is `GET /utilities/map-names → list[str]` (all rows,
  `SELECT name FROM maps.names ORDER BY name`, no `search`, no `limit`). It is a **new** handler —
  the existing `/utilities/autocomplete/names` (search-required, similarity-ordered, `limit=5`) is
  for type-ahead and is NOT a substitute. The autocomplete endpoint stays unchanged.
- **D-03:** Add + replace-banner. Creating a new map (name + banner) and re-uploading/replacing the
  banner for an existing map are both in scope. Rename and delete are deferred.
- **D-04:** Banner is **required** at create (single mixed-multipart request,
  `Struct{name: str, banner: UploadFile}`).
- **D-05:** Store the banner at the **stripped-name key**, matching the existing `get_map_banner()`
  derivation (`maps.py:1013` — `re.sub(r"[^a-zA-Z0-9]","",name).lower()` →
  `assets/map_banners/{stripped}.png`). Reads stay on `get_map_banner()` with zero read-site
  changes. New `upload_map_banner(content, content_type, map_name) -> url` keys by stripped name
  (NOT date+digest like `upload_screenshot`, NOT URL-encoded exact name).
- **D-06:** **DROP the `maps.names.banner_url` column** that Spike 007 proposed. Migration needs
  **no new column** — only the FK + idempotent-seed rewrite. (Deliberate deviation from Spike 007.)
- **D-07:** **Collision guard at add time.** The create service MUST reject (HTTP **422**,
  `CustomHTTPException`) a new name whose stripped key already maps to a **different** existing map.
  The empty/blank-name → 422 check from the spike also stays.
- **D-08:** Reconcile the 7 phantom Literal-only maps into `maps.names`: Arena Victoriae, Gogadoro,
  Neon Junction, Place Lacroix, Powder Keg Mine, Redwood Dam, Thames District.
- **D-09:** Replace the plain `INSERT`s in `0001_init.sql` with one idempotent
  `INSERT ... ON CONFLICT DO NOTHING` block (also fixes a latent non-idempotency bug — today's seed
  errors on replay with a duplicate-PK violation).
- **D-10:** Regenerate the seed from the live DB with a **standalone on-demand export script** — run
  manually, NOT wired into the nightly backup job, never from the request path. Backups remain the
  primary recovery path; the seed is for from-migrations bootstrap parity.
- **D-11:** Add `core.maps.map_name → maps.names.name` FK (`ON UPDATE CASCADE`) as defence-in-depth,
  **after** the service runtime check. **Guard the migration with an orphan pre-flight.**

### Claude's Discretion
- Exact internal layout of the new map-management service/repository (extend
  `ContentService`/`ContentRepository` vs. a dedicated maps-content module) — follow whichever best
  matches the movement-tech CMS structure.
- Image content-type validation depth on the banner upload (mirror `upload_image` /
  `ImageStorageService._ext_from_content_type`).
- The `request_max_body_size` value — default to `upload_image`'s 25 MB.
- Optional short-TTL bot cache for the full name list (~63 short strings is tiny; fetch-once-per-
  wizard-build is sufficient).

### Deferred Ideas (OUT OF SCOPE)
- Renaming a map (interacts with `core.maps` FK `ON UPDATE CASCADE` and the stripped banner key).
- Delete / archive a map name (must handle dependent `maps.mastery` / `core.maps` rows).
- Bot-side "add map" slash command (bot only consumes via autocomplete + dropdown this phase).
- Wiring the seed export into the nightly backup job.
- Forward-looking `banner_url` column for arbitrary non-strippable keys.
</user_constraints>

<phase_requirements>
## Phase Requirements

Derived from CONTEXT.md decisions and the spike blueprint. The planner maps these to plans/tasks.

| ID | Description | Research Support |
|----|-------------|------------------|
| REQ-01 | Flip `OverwatchMap` Literal → `str` across the SDK blast radius | File-by-file inventory below; msgspec decodes `str` so boundary stops blocking new maps |
| REQ-02 | Add service-layer runtime validation against `maps.names` with `difflib` "did you mean" | `validate_map_name` pattern; `maps.names` already the canonical table |
| REQ-03 | `POST /api/v3/content/maps` mixed-multipart create (name + required banner), `content:admin` | Spike 007 `app.py`; `upload_image` route; `MovementTechController` pattern |
| REQ-04 | Replace-banner for an existing map (re-upload path) | D-03; idempotent banner key means re-upload overwrites at same key |
| REQ-05 | Empty-name guard → 422 `CustomHTTPException` | D-07; spike soft-`{ok:false}` must become 422 in real service |
| REQ-06 | Stripped-key collision guard → 422 when a new name strips to a different existing map's key | D-07; `get_map_banner()` derivation is lossy |
| REQ-07 | `upload_map_banner(content, content_type, map_name) -> url` keyed by stripped name | D-05; mirror `get_map_banner()`, NOT `upload_screenshot` |
| REQ-08 | `GET /utilities/map-names → list[str]` full-list endpoint | D-02; distinct from search-required `/utilities/autocomplete/names` |
| REQ-09 | Bot `api_service.get_all_map_names()` client method | Mirrors `get_autocomplete_map_names` |
| REQ-10 | Swap `MapNameSelect` to DB-fed list; fetch once in async wizard-build context | Spike 008; `__init__` is sync, cannot await |
| REQ-11 | Migration 0032: FK `core.maps.map_name → maps.names.name ON UPDATE CASCADE` + orphan pre-flight | D-11; `maps.mastery` already has this FK pattern |
| REQ-12 | Idempotent `ON CONFLICT DO NOTHING` seed rewrite in `0001_init.sql` | D-09; 63 plain INSERTs today, non-idempotent |
| REQ-13 | Reconcile 7 phantom Literal-only maps into `maps.names` | D-08; SDK Literal (70) vs `maps.names` (63) drift |
| REQ-14 | Standalone on-demand seed export script (manual, never request-path) | D-10 |
| REQ-15 | Newly-added map resolves on all three surfaces with no redeploy | The whole feature; verify website read, submission accept, bot dropdown |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Map-name acceptance (request boundary) | API / Service | DB (FK backstop) | Literal gate removed; runtime check + FK own validation |
| Add-map write (name + banner) | API / Service → Repository | S3 (MinIO/R2) | Three-layer CMS pattern; banner to object storage, name to DB |
| Banner addressing | DB-derived (`get_map_banner()`) at read | S3 storage at write | Stripped-key derivation keeps reads unchanged (D-05) |
| Full map-name list | API / Repository | — | `SELECT name FROM maps.names ORDER BY name` |
| Map-name autocomplete (type-ahead) | API / Repository (unchanged) | — | Already DB-backed; stays as-is |
| Bot map-name dropdown options | Bot (async view build) → API | — | Fetch full list once, feed sync `ui.Select.__init__` |
| Durable map record | DB (live, primary) | Migration seed + backups (DR) | Endpoint writes DB only; seed/backups for bootstrap/DR |
| Compile-time map-name type safety | **Removed (deliberate trade)** | Runtime check replaces it | Codegen can't deliver "appears automatically" |

## Standard Stack

No new external packages. Everything is already a project dependency.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Litestar | >=2.16.0 `[VERIFIED: pyproject.toml]` | REST framework, multipart decode | Existing API framework; `upload_image` proves multipart works |
| msgspec | >=0.19.0 `[VERIFIED: pyproject.toml]` | Struct decode/encode, boundary validation | Spike 007 proved mixed multipart Struct decode |
| asyncpg | >=0.30.0 (via litestar-asyncpg >=0.4.0) `[VERIFIED: pyproject.toml]` | Raw SQL, pool, transactions | Project standard; no ORM |
| boto3 | >=1.40.25 `[VERIFIED: pyproject.toml]` | S3-compatible banner upload | `ImageStorageService` already uses it |
| difflib | stdlib (Python 3.13) `[VERIFIED: stdlib]` | "did you mean" suggestion | Spike 004 blueprint; zero deps |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| discord.py | master (git) `[VERIFIED: pyproject.toml]` | `ui.Select` for `MapNameSelect` | Bot dropdown swap |
| pytest + pytest-asyncio + pytest-databases | per pyproject `[VERIFIED]` | Integration tests w/ real Postgres | `AsyncTestClient` + `postgres_service` fixtures |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Runtime `str` + DB validation | Keep Literal + per-map codegen | Codegen still needs regen + redeploy → defeats "appears automatically" (explicitly rejected) |
| Stripped-key banner storage (D-05) | `banner_url` column (Spike 007) | CONTEXT D-06 drops the column for zero read-site churn; collision risk handled by D-07 guard |
| `difflib.get_close_matches` | rapidfuzz (a project dep) | difflib is stdlib, zero-import, sufficient for ~63 short strings; rapidfuzz is declared but not imported |

**Installation:** None — no new packages. `[VERIFIED: pyproject.toml — no new deps required]`

## Package Legitimacy Audit

No external packages are installed in this phase. All libraries used are pre-existing project
dependencies verified in `pyproject.toml` and the workspace lockfile. **slopcheck / registry
verification N/A — zero new packages.**

## Architecture Patterns

### System Architecture Diagram

```
                          ADD-MAP (write path)                      READ paths (unchanged)
   admin / dashboard                                          website ───────────┐
        │ multipart/form-data {name, banner}                 bot autocomplete ────┤ all read
        ▼                                                     bot dropdown ────────┤ maps.names
  POST /api/v3/content/maps  (content:admin scope guard)      map submission ──────┘ (+ get_map_banner)
        │                                                                │
        ▼                                                                ▼
  Controller (thin)  ──decode Struct{name,banner}──►  msgspec boundary (missing field → 400)
        │
        ▼
  MapContentService.create_map(name, banner_bytes, content_type)
        │  1. name.strip() empty?            ──► CustomHTTPException 422
        │  2. stripped-key collision?        ──► CustomHTTPException 422   (query maps.names)
        │  3. upload_map_banner(...)         ──► S3 object at assets/map_banners/{stripped}.png
        │  4. INSERT INTO maps.names (name)  ──► ON CONFLICT DO NOTHING   (live source of truth)
        ▼
  maps.names  ◄── core.maps.map_name FK (ON UPDATE CASCADE, defence-in-depth)
        │
        └── get_map_banner(name) re-derives the SAME stripped key at read time → resolves new banner
```

The new map appears everywhere because all three surfaces already read `maps.names` at runtime;
the Literal was the only static gate. No queue/event publishing is involved (this is a pure
synchronous DB+S3 write, like the movement-tech CMS).

### Recommended Project Structure (files touched / added)

```
libs/sdk/src/genjishimada_sdk/
├── maps.py                 # DROP Literal at :107 → OverwatchMap = str; flip ~12 struct fields
├── completions.py          # 3 fields flip (type-only)
└── newsfeed.py             # 4 fields flip (type-only)

apps/api/
├── routes/v3/content.py    # ADD create_map endpoint + request/response structs (mirror MovementTech)
├── routes/v3/autocomplete.py  # ADD get_all_map_names handler (GET /utilities/map-names)
├── routes/v3/maps.py       # type hints flip (OverwatchMap → str), no behaviour change
├── services/content_service.py     # ADD map create/validate/collision logic (or new module)
├── services/image_storage_service.py  # ADD upload_map_banner method
├── repository/content_repository.py   # ADD insert_map_name, fetch_all_map_names, fetch_known_map_names
├── repository/autocomplete_repository.py  # type hints flip
├── utilities/map_search.py, shared_queries.py  # type hints flip
└── migrations/0032_dynamic_map_management.sql  # NEW: FK + orphan guard + reconcile phantoms
└── migrations/0001_init.sql  # REWRITE seed → one ON CONFLICT block (D-09)

apps/bot/
├── extensions/moderator.py     # MapNameSelect: get_args(OverwatchMap) → DB-fed list (THE one behaviour change)
├── extensions/api_service.py   # ADD get_all_map_names(); flip OverwatchMap type hints
├── extensions/{map_search,map_submission,newsfeed}.py, utilities/{maps,transformers}.py  # type hints flip

scripts/
└── export_map_names_seed.py    # NEW: standalone on-demand seed export (D-10)
```

### Pattern 1: Mixed-multipart create endpoint (Spike 007 — VALIDATED on real Litestar)
**What:** One `multipart/form-data` request carrying a text field AND an `UploadFile`, decoded into
a `msgspec.Struct`. msgspec boundary validation is preserved (missing `name` → 400).
**When to use:** The add-map create endpoint.
**Example:**
```python
# Source: .claude/skills/.../sources/007-multipart-banner-upload/app.py:99-197 (VALIDATED)
#         + apps/api/routes/v3/utilities.py:31 (upload_image, the existing multipart route)
class MapCreateMultipart(msgspec.Struct):
    name: str
    banner: UploadFile

@post(
    "/maps",                                  # under MovementTechController-style controller, path /content
    status_code=HTTP_201_CREATED,
    opt={"required_scopes": {"content:admin"}},
    request_max_body_size=1024 * 1024 * 25,   # 25 MB, matches upload_image
)
async def create_map(
    self,
    data: Annotated[MapCreateMultipart, Body(media_type=RequestEncodingType.MULTI_PART)],
    map_content_service: MapContentService,
) -> MapCreateResponse:
    content = await data.banner.read()
    content_type = data.banner.content_type or "image/png"
    row = await map_content_service.create_map(data.name, content, content_type)
    return msgspec.convert(row, MapCreateResponse)
```
Note: `upload_image` uses `sync_to_thread=False` with a *sync* handler that does `data.file.read()`.
The mixed-multipart spike used an *async* handler with `await data.banner.read()`. Prefer the async
form here because the service does async DB work; read the file with `await data.banner.read()`.

### Pattern 2: Runtime validation with "did you mean" (Spike 004)
**What:** Replace the Literal's terse `Invalid enum value` with a DB check that suggests near matches.
**When to use:** Service layer, before insert and on any path that accepts a free-form map name.
**Example:**
```python
# Source: dynamic-map-management.md §1 (Spike 004, VALIDATED)
import difflib
from utilities.errors import CustomHTTPException
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

async def validate_map_name(name: str, known: set[str]) -> str:
    if name in known:
        return name
    suggestions = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
    hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
    raise CustomHTTPException(
        detail=f"'{name}' is not a known Overwatch map.{hint}",
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
    )
```
This validator is for *consumers* of a map name (e.g., submission). The **create** endpoint is the
opposite — it inserts a NEW name, so it does NOT validate-against-existing; instead it runs the
empty-name guard and the stripped-key collision guard (Pattern 3).

### Pattern 3: Stripped-key collision guard (D-07)
**What:** Reject (422) a new name whose stripped key collides with a *different* existing map.
**Why:** `get_map_banner()` strips accents and punctuation, so `King's Row` and `Kings Row` both →
`kingsrow`; storing the second banner would overwrite the first.
**Example:**
```python
# Derived from get_map_banner() at libs/sdk/.../maps.py:1013-1017 + CONTEXT D-07
import re

def strip_key(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")

async def assert_no_stripped_collision(name: str, conn) -> None:
    target = strip_key(name)
    rows = await conn.fetch("SELECT name FROM maps.names")
    for r in rows:
        existing = r["name"]
        if existing != name and strip_key(existing) == target:
            raise CustomHTTPException(
                detail=(f"Map name '{name}' collides with existing map "
                        f"'{existing}' (both resolve to banner key '{target}'). "
                        "Choose a name that does not strip to the same key."),
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            )
```

### Pattern 4: Banner upload keyed by stripped name (D-05)
**What:** New `ImageStorageService.upload_map_banner` keying by the stripped name, NOT date+digest.
**Example:**
```python
# Source: apps/api/services/image_storage_service.py:44 (upload_screenshot — pattern to ADAPT)
#         + get_map_banner() at maps.py:1013 (the key derivation to MATCH)
def upload_map_banner(self, content: bytes, content_type: str, map_name: str) -> str:
    stripped = re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")
    # get_map_banner() hardcodes .png; keep .png so reads resolve regardless of upload content-type
    key = f"assets/map_banners/{stripped}.png"
    self.client.upload_fileobj(
        io.BytesIO(content), S3_BUCKET_NAME, key,
        ExtraArgs={"ContentType": content_type,
                   "CacheControl": "public, max-age=31536000, immutable"},
    )
    return f"{S3_PUBLIC_URL}/{key}"
```
**Critical:** `get_map_banner()` (maps.py:1013-1017) hardcodes `.png` in the URL. The uploaded
object key MUST end `.png` regardless of the actual image content-type, or reads won't resolve.
The replace-banner path (D-03) is automatic: re-uploading the same map overwrites the same key.
Note the `immutable` cache header — a replaced banner may be served stale by the CDN until cache
expiry; surface this as a known limitation (see Open Questions).

### Pattern 5: DB-fed bot dropdown (Spike 008)
**What:** `MapNameSelect.__init__` is a sync `ui.Select` subclass — it cannot `await`. Fetch the
full name list once in the async wizard-build context and pass it into the constructor.
**Where:** `MapEditWizardView` is constructed in two async command callbacks —
`apps/bot/extensions/moderator.py:105` and `apps/bot/extensions/map_editor.py:61`. Fetch the list
there (`await itx.client.api.get_all_map_names()`), thread it through `MapEditWizardView.__init__`
→ `rebuild()` (moderator.py:1334) → `MapNameSelect(current, page=..., all_maps=fetched_list)`.
**Example:**
```python
# Source: dynamic-map-management.md §5 (Spike 008, VALIDATED) + moderator.py:761-779
def __init__(self, current: str | None, all_maps: list[str], page: int = 0) -> None:
    all_maps = sorted(all_maps)                       # was: list(get_args(OverwatchMap)); all_maps.sort()
    start_idx = page * _PAGINATED_SELECT_PAGE_SIZE    # 25/page — UNCHANGED
    end_idx = start_idx + _PAGINATED_SELECT_PAGE_SIZE
    page_maps = all_maps[start_idx:end_idx]
    options = [SelectOption(label=m, value=m, default=(m == current)) for m in page_maps]
    super().__init__(placeholder=f"Select map name (page {page + 1})...", options=options)
    self.page = page
    self.total_pages = (len(all_maps) + _PAGINATED_SELECT_PAGE_SIZE - 1) // _PAGINATED_SELECT_PAGE_SIZE
```
**Keep the slice / `total_pages` / `SelectOption` math verbatim — Spike 008 proved it correct.**

### Anti-Patterns to Avoid
- **Don't keep the Literal and codegen per map** — still needs regen + redeploy; defeats the goal.
- **Don't add the FK instead of the runtime check** — FK error is opaque; the service check gives
  the "did you mean" message. FK is the backstop, runtime check is the gate.
- **Don't have the API write a migration file / open a PR per map** — couples a running service to
  the repo and creates migration-number contention (Spike 006 rejected this).
- **Don't reuse `upload_screenshot` for banners** — it keys by date+digest, never `get_map_banner()`-
  resolvable.
- **Don't key the banner by the full/URL-encoded name** — reads derive the stripped key, so only
  the stripped key resolves (D-05).
- **Don't move `get_args(MapCategory)` (or Mechanics/Restrictions/Tags/Difficulty) off the Literal**
  — only the map-name `get_args(OverwatchMap)` in `moderator.py:768` becomes DB-fed.
- **Don't `await` inside `MapNameSelect.__init__`** — it's sync; fetch once in the async view build.

## Blast-Radius Change Inventory (OverwatchMap → str)

**28 files** reference `OverwatchMap` (`[VERIFIED: grep -rln OverwatchMap]`). Categorised:

### A. The Literal definition (1 site — the crux)
| File:Line | Change |
|-----------|--------|
| `libs/sdk/src/genjishimada_sdk/maps.py:107` | `OverwatchMap = Literal[...]` → `OverwatchMap = str`. Keep the name exported (it's in `__all__` at :50 and imported widely) so all `OverwatchMap` references resolve to `str`. This is the minimal-churn approach: one edit flips the type for all 27 consumers. |

### B. SDK struct fields (type-only flip; msgspec already decodes str — no behaviour change)
| File:Line | Field |
|-----------|-------|
| `libs/sdk/.../maps.py:312, 346, 433, 587, 650, 663, 678, 931, 969, 1028, 1102` | various `map_name: OverwatchMap` (and one `OverwatchMap \| UnsetType`) |
| `libs/sdk/.../completions.py:138, 183, 228` | `map_name: OverwatchMap` |
| `libs/sdk/.../newsfeed.py:75, 98, 123, 141` | `map_name: OverwatchMap` |
*If `OverwatchMap` is aliased to `str` (option A), these need **no edit** — they keep compiling.*

### C. API type hints (type-only; no behaviour change)
| File:Line | Note |
|-----------|------|
| `apps/api/repository/autocomplete_repository.py:18, 38, 52, 78` | return/param hints; `get_similar_map_names` already does `SELECT name FROM maps.names` |
| `apps/api/routes/v3/autocomplete.py:29, 50, 97` | endpoint return hints (`list[OverwatchMap]` → `list[str]`) |
| `apps/api/repository/maps_repository.py:847, 867, 876` | param hints |
| `apps/api/routes/v3/maps.py:110, 667` | filter param hints |
| `apps/api/services/maps_service.py:687` | param hint |
| `apps/api/utilities/map_search.py:57`, `shared_queries.py:8, 42` | param hints |

### D. Bot type hints (type-only; transformer already DB-backed)
| File:Line | Note |
|-----------|------|
| `apps/bot/utilities/transformers.py:22` | `MapNameTransformer.transform` return hint — already resolves via API/DB at runtime |
| `apps/bot/extensions/api_service.py:416, 444, 506, 534, 788, 802, 813, 1451` | param/return hints + `response_model=list[OverwatchMap]` (becomes `list[str]`) |
| `apps/bot/extensions/map_search.py:324, 438` | `Transform[OverwatchMap, MapNameTransformer]` hints |
| `apps/bot/extensions/map_submission.py:25` | `Transform[OverwatchMap, MapNameTransformer]` — **the submission path the Literal blocked** |
| `apps/bot/extensions/newsfeed.py:172, 193, 215`, `utilities/maps.py:202`, `moderator.py:1335` | hints/casts |

### E. The ONE behavioural change
| File:Line | Change |
|-----------|--------|
| `apps/bot/extensions/moderator.py:768` | `all_maps = list(get_args(OverwatchMap))` → DB-fed list (Pattern 5). Once `OverwatchMap = str`, `get_args(str)` returns `()` → empty dropdown. This is the only place the flip changes runtime behaviour. **`moderator.py:743` `get_args(MapCategory)` STAYS.** |

### F. Tests (update fixtures — these are the bulk of the 28)
14 test files use `fake.random_element(elements=get_args(OverwatchMap))` to pick a random map name
(`test_maps_repository_*.py`, `test_community_repository_popular.py`, `conftest.py:346`). Once
`OverwatchMap = str`, `get_args(str)` returns `()` and `random_element([])` raises. **Replace with a
module-level constant list of seed map names** (e.g., `_SEED_MAP_NAMES = ["Hanamura", "Busan", ...]`
or read from `maps.names`). `get_args(MapCategory)` in the same files stays. Affected:
`tests/conftest.py:346`; `tests/repository/maps/test_maps_repository_{advanced_operations,
check_code_exists,create_core_map,entity_operations,fetch_partial_map,guide_operations,
update_core_map}.py`; `tests/repository/community/test_community_repository_popular.py`;
`tests/integration/test_maps_integration.py:881` (string literal `"Nepal"` — fine, no change).

**Summary count:** 1 definition + ~18 type-only annotations + 1 behavioural (bot dropdown) +
~14 test-fixture updates. The CONTEXT estimate of ~28 files / ~109 lines is accurate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multipart body parsing | Manual boundary parsing | `Body(media_type=RequestEncodingType.MULTI_PART)` | Spike 007 proved Litestar decodes mixed Struct+UploadFile + preserves msgspec validation |
| "Did you mean" suggestion | Custom Levenshtein | `difflib.get_close_matches` | stdlib, sufficient for ~63 short strings |
| S3 key derivation | New key scheme | Match `get_map_banner()` stripped key exactly | D-05: reads re-derive this exact key; any other key won't resolve |
| Scope enforcement | Custom auth check | `opt={"required_scopes": {"content:admin"}}` | Global `scope_guard` already enforces it |
| Constraint-violation → HTTP error | Raw asyncpg catch in route | Repository exceptions → service → `CustomHTTPException` | Established three-tier hierarchy |
| Transaction management | Manual BEGIN/COMMIT | `async with conn.transaction():` | ContentService pattern; also avoids the abort-poisoning gotcha |

**Key insight:** Almost everything here already exists in the codebase — the movement-tech CMS, the
`upload_image` route, `ImageStorageService`, `get_map_banner()`, the `maps.mastery` FK pattern, and
the DB-backed autocomplete. This phase is overwhelmingly *wiring existing patterns together* plus
one type-system flip, not new infrastructure.

## Common Pitfalls

### Pitfall 1: Transaction-abort poisoning
**What goes wrong:** Catching an FK/unique violation mid-transaction and continuing raises
`InFailedSQLTransactionError` on the next statement.
**Why:** Postgres aborts the whole transaction on any constraint violation.
**How to avoid:** Wrap the fallible insert in a SAVEPOINT (`async with conn.transaction():` nested),
OR — better here — run the empty-name + collision guards **before** opening the transaction, and let
the `ON CONFLICT DO NOTHING` insert be the only fallible statement. The create endpoint should
validate first (S3 upload + guards), then do a single clean insert.
**Warning signs:** A second statement after a caught DB error throwing `InFailedSQLTransactionError`.

### Pitfall 2: Lossy stripped-key collision silently overwriting a banner
**What goes wrong:** `King's Row` and `Kings Row` both strip to `kingsrow`; the second upload
overwrites the first's banner.
**Why:** `get_map_banner()` derivation drops accents/punctuation (D-05/D-06 keep this derivation).
**How to avoid:** The D-07 collision guard (Pattern 3) must run before the S3 upload. Verify it
catches both an accent collision (`Château`/`Chateau`) and a punctuation collision (`King's Row`).
**Warning signs:** Two distinct `maps.names` rows whose stripped keys are equal.

### Pitfall 3: msgspec boundary validation must still pass after the flip
**What goes wrong:** Assuming the `str` flip removes ALL validation.
**Why:** msgspec still validates required fields and types at the boundary (Spike 007: a missing
`name` part still returns a clean 400). The flip only removes the *enum* check, not field presence.
**How to avoid:** Keep `name: str` (required) on the request Struct; the runtime DB check is the new
*value* gate, the boundary still enforces *presence/type*.

### Pitfall 4: Banner key extension mismatch
**What goes wrong:** Uploading a `.webp`/`.jpg` banner but `get_map_banner()` requests `{name}.png`.
**Why:** `get_map_banner()` (maps.py:1017) hardcodes `.png`.
**How to avoid:** `upload_map_banner` must write the object at `{stripped}.png` regardless of source
content-type (set `ContentType` header to the real type, but the key extension stays `.png`).

### Pitfall 5: Orphan rows block the FK migration
**What goes wrong:** `ALTER TABLE core.maps ADD CONSTRAINT ... FOREIGN KEY (map_name) ...` fails if
any `core.maps.map_name` is absent from `maps.names`.
**Why:** FK requires all existing values to be valid.
**How to avoid:** Run the orphan pre-flight (D-11) first; reconcile the 7 phantom maps (D-08) in the
same migration **before** adding the FK. Local = 0 orphans, but prod may differ — the migration
should fail loudly with a clear message if orphans remain, not silently.
**Warning signs:** Migration error referencing `maps_map_name_names_fk`.

### Pitfall 6: `get_args(str)` returning empty in tests
**What goes wrong:** After the flip, 14 test files calling `get_args(OverwatchMap)` get `()` →
`fake.random_element([])` raises (`IndexError`/`ValueError`).
**How to avoid:** Replace those calls with a constant seed-name list before/with the SDK flip (see
inventory §F). This is the largest single chunk of the blast radius.

## Code Examples

### Full-list names endpoint (D-02)
```python
# ADD to AutocompleteController in apps/api/routes/v3/autocomplete.py (path is already "/utilities")
@get(
    path="/map-names",
    tags=["Autocomplete"],
    summary="List All Map Names",
    description="Return all Overwatch map names alphabetically. Full list, no search/limit.",
)
async def list_all_map_names(self, autocomplete: AutocompleteRepository) -> list[str]:
    return await autocomplete.fetch_all_map_names()

# ADD to AutocompleteRepository in apps/api/repository/autocomplete_repository.py
async def fetch_all_map_names(self, *, conn: Connection | None = None) -> list[str]:
    _conn = self._get_connection(conn)
    rows = await _conn.fetch("SELECT name FROM maps.names ORDER BY name")
    return [r["name"] for r in rows]
```

### Bot client method (REQ-09)
```python
# ADD to apps/bot/extensions/api_service.py, alongside get_autocomplete_map_names (:788)
def get_all_map_names(self) -> Response[list[str]]:
    r = Route("GET", "/utilities/map-names")
    return self._request(r, response_model=list[str])
```

### Migration 0032 skeleton (REQ-08/11/13)
```sql
-- apps/api/migrations/0032_dynamic_map_management.sql

-- 1. Reconcile the 7 phantom Literal-only maps (D-08) so the FK can be added.
INSERT INTO maps.names (name) VALUES
    ('Arena Victoriae'), ('Gogadoro'), ('Neon Junction'), ('Place Lacroix'),
    ('Powder Keg Mine'), ('Redwood Dam'), ('Thames District')
ON CONFLICT DO NOTHING;

-- 2. Orphan pre-flight (D-11): fail loudly if any core.maps.map_name is unknown.
DO $$
DECLARE orphan text;
BEGIN
    SELECT string_agg(DISTINCT m.map_name, ', ') INTO orphan
    FROM core.maps m LEFT JOIN maps.names n ON n.name = m.map_name
    WHERE n.name IS NULL;
    IF orphan IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot add FK: orphan core.maps.map_name values not in maps.names: %', orphan;
    END IF;
END $$;

-- 3. FK backstop (D-11), mirroring maps.mastery.map_name (0001_init.sql:1300).
ALTER TABLE core.maps
    ADD CONSTRAINT maps_map_name_names_fk
    FOREIGN KEY (map_name) REFERENCES maps.names (name)
    ON UPDATE CASCADE;
```

### Idempotent seed rewrite (D-09) — replace 0001_init.sql:823-1200
```sql
-- One block instead of 63 plain INSERTs. Include the 7 phantom maps so a fresh
-- from-migrations bootstrap matches the reconciled live DB. ON CONFLICT fixes the
-- latent replay bug (today's seed errors on duplicate PK).
INSERT INTO maps.names (name) VALUES
    ('Circuit Royal'), ('Runasapi'), ('Practice Range'), -- ... all 70 reconciled names ...
    ('Arena Victoriae'), ('Gogadoro'), ('Neon Junction'), ('Place Lacroix'),
    ('Powder Keg Mine'), ('Redwood Dam'), ('Thames District')
ON CONFLICT DO NOTHING;
```

## Runtime State Inventory

> This phase is partly a rename/refactor (Literal → str) and adds durable state. Inventory below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `maps.names` (PK `name`, 63 rows live; 70 in Literal → 7 phantom drift). `core.maps.map_name` (plain text, no FK). `maps.mastery.map_name` (already FK'd to `maps.names`). S3 `assets/map_banners/{stripped}.png` objects. | Reconcile 7 phantoms (D-08); add FK on `core.maps.map_name` (D-11); new banner objects written by `upload_map_banner`. |
| Live service config | None. No n8n/Datadog/external service stores `OverwatchMap`. The seed lives in `0001_init.sql` (git). | None beyond the seed rewrite (D-09). |
| OS-registered state | None — no Task Scheduler/pm2/systemd references to map names. | None. |
| Secrets / env vars | None reference map names. S3 creds (`AWS_*`, `S3_*`, `R2_*`) already configured for banner upload. | None. |
| Build artifacts | The SDK (`genjishimada_sdk`) is a workspace package; flipping `OverwatchMap` changes the shared type. API and bot both import it. | `just sync` / reinstall workspace after SDK edit so both apps pick up the new type. No codegen artifact for `OverwatchMap`. |

**Phantom-map drift (verified):** SDK Literal has 70 entries (`maps.py:107-178`); `maps.names` seed
has 63 INSERTs (`0001_init.sql`, `[VERIFIED: grep count]`). The 7 extras (Arena Victoriae,
Gogadoro, Neon Junction, Place Lacroix, Powder Keg Mine, Redwood Dam, Thames District) pass Literal
request validation but have no `maps.names` row → fail the `maps.mastery` FK and never autocomplete.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `OverwatchMap = Literal[...]` static gate | `str` + runtime DB validation | This phase | New maps appear without regen/redeploy |
| Banner via `banner_url` column (Spike 007) | Banner at stripped-key, no column (D-05/D-06) | CONTEXT override | Zero read-site churn; collision handled by D-07 guard |
| 63 plain non-idempotent INSERTs | One `ON CONFLICT DO NOTHING` block | This phase (D-09) | Seed replay-safe; fixes latent duplicate-PK bug |
| Bot dropdown from `get_args(OverwatchMap)` | DB-fed list via new endpoint | This phase (Spike 008) | Dropdown shows dynamically-added maps, no restart |

**Deprecated/outdated (stale ROADMAP/Spike text — DO NOT follow):**
- ROADMAP "banner stored via a new `maps.names.banner_url` column" — **overridden by D-06** (column dropped).
- ROADMAP "seed regenerated by a separate export job [wired into backup]" — **overridden by D-10** (standalone on-demand, not wired in).
- Spike 007 "store the upload's URL in a new `maps.names.banner_url` column; key uniquely" —
  **overridden by D-04/D-05/D-06/D-07** (stripped key + collision guard instead).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Aliasing `OverwatchMap = str` (keeping the name) is the lowest-churn flip and BasedPyright strict accepts it for all consumers | Blast-Radius §A/B | If a consumer relies on `get_args()` returning members (only `moderator.py:768` + tests do, both addressed), nothing else breaks. Low risk — verified usages. |
| A2 | `get_map_banner()` hardcoded `.png` means banners must always be stored as `.png` | Pattern 4 / Pitfall 4 | If a non-png banner needs a different extension, reads break. Mitigated by always writing `.png` key. Confirmed by reading maps.py:1017. |
| A3 | The `create_map` endpoint inserts a NEW name and therefore does NOT run validate-against-existing (only empty + collision guards) | Pattern 2/3 | If product wants create to reject already-existing names with a friendly 409, add that explicitly. CONTEXT says `ON CONFLICT DO NOTHING` (idempotent), implying re-create is a no-op, not an error. |
| A4 | `content:admin` scope already exists and is enforced by the global `scope_guard` (no new scope/seed needed) | D-01 | If the test/prod token lacks `content:admin`, create returns 403. Movement-tech CMS already uses it, so it exists. Low risk. |
| A5 | The replace-banner path (D-03) is satisfied by re-uploading to the same stripped key (overwrite); no separate endpoint needed | REQ-04 | If product wants a distinct PUT/PATCH for replace-only (no insert), add it. The collision/idempotent design makes create double as replace. Flag for planner. |
| A6 | CDN `immutable` cache header may serve a stale banner after replace until expiry | Pattern 4 / Open Q | If immediate refresh is required, need cache-busting (versioned key or purge) — conflicts with D-05's fixed key. See Open Questions. |

## Open Questions

1. **Replace-banner vs. CDN immutable cache.**
   - What we know: `upload_screenshot` sets `CacheControl: immutable, max-age=1yr`; D-05 fixes the
     banner key, so a replaced banner reuses the same URL.
   - What's unclear: whether a replaced banner must appear immediately (CDN may serve the cached old
     object until TTL). Versioned keys would fix it but break D-05's derived-key contract.
   - Recommendation: For this phase, accept eventual refresh (or use a shorter `max-age` for banners
     than for screenshots). Surface to the user in discuss-phase; defer cache-busting.

2. **Should `create_map` 409 on an already-existing name, or silently no-op?**
   - What we know: CONTEXT/Spike use `ON CONFLICT DO NOTHING` (idempotent no-op).
   - What's unclear: whether an admin re-adding an existing name should get a clear "already exists"
     response (and whether re-add should still replace the banner).
   - Recommendation: Return 201 with an `inserted: bool` flag (Spike 007 did `inserted=...`), OR
     409 on exact-name duplicate. Let the planner pick; default to the idempotent 201 + flag.

3. **Where does map-create logic live — extend `ContentService` or a new `MapContentService`?**
   - Claude's discretion (CONTEXT). Recommendation: a dedicated `MapContentService`/repository
     (or methods on `ContentRepository`) under the content namespace, to keep movement-tech and map
     concerns separable while reusing the `content:admin` controller. Either matches the CMS shape.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | maps.names, FK, migration, tests | ✓ (docker-compose.local + pytest-databases) | 17 (prod) / test fixture | — |
| MinIO (S3) | banner upload verification | ✓ (docker-compose.local) | bucket `genji-parkour-images` | — for tests, mock `ImageStorageService` |
| Litestar `[standard]` (uvicorn) | running API / multipart | ✓ | >=2.16.0 | — |
| difflib | "did you mean" | ✓ stdlib | 3.13 | — |
| `content:admin`-scoped token | endpoint auth | ✓ (test uses superuser `X-API-KEY: testing` bypassing scope) | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** Banner S3 in unit tests — inject/mock `ImageStorageService`
so tests don't hit MinIO; integration tests can use the local MinIO bucket.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.3.5 + pytest-asyncio (auto) + pytest-databases[postgres] + pytest-xdist (8 workers) `[VERIFIED: pyproject.toml]` |
| Config file | `apps/api/pyproject.toml` (pytest config) |
| Quick run command | `just test-api` (or `uv run pytest apps/api/tests/integration/test_<x>.py -x`) |
| Full suite command | `just ci` (lint + test-all) |
| Test client | `AsyncTestClient(app)` with headers `x-pytest-enabled: 1`, `X-API-KEY: testing` (superuser, bypasses scope) — `conftest.py:114-127` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REQ-01 | `MapCreateRequest`/submission accepts a name absent from the old Literal | integration | `pytest apps/api/tests/integration/test_maps_integration.py -k create -x` | ✅ extend |
| REQ-02 | Unknown map name → 422 with "did you mean" suggestion | unit/integration | `pytest -k validate_map_name -x` | ❌ Wave 0 |
| REQ-03 | `POST /content/maps` mixed multipart decodes name+banner → 201 | integration | `pytest apps/api/tests/integration/test_content_integration.py -k create_map -x` | ❌ Wave 0 (extend file) |
| REQ-04 | Re-upload banner for existing map overwrites same key | integration | `pytest -k replace_banner -x` | ❌ Wave 0 |
| REQ-05 | Empty/blank name → 422 | integration | `pytest -k empty_name -x` | ❌ Wave 0 |
| REQ-06 | Stripped-key collision (King's Row / Kings Row) → 422 | unit/integration | `pytest -k collision -x` | ❌ Wave 0 |
| REQ-07 | `upload_map_banner` writes `assets/map_banners/{stripped}.png` | unit | `pytest -k upload_map_banner -x` | ❌ Wave 0 |
| REQ-08 | `GET /utilities/map-names` returns all rows sorted, no search | integration | `pytest apps/api/tests/integration/test_autocomplete_integration.py -k map_names -x` | ❌ Wave 0 (extend) |
| REQ-11 | FK orphan pre-flight raises on orphan; FK added clean otherwise | integration (schema) | `pytest -k map_name_fk -x` | ❌ Wave 0 |
| REQ-12 | Seed replays idempotently (no duplicate-PK error) | integration (schema) | `pytest -k seed_idempotent -x` | ❌ Wave 0 |
| REQ-13 | All 70 reconciled maps present in `maps.names` after migration | integration | `pytest -k phantom_maps -x` | ❌ Wave 0 |
| REQ-15 | Added map appears: website read (fetch_maps), submission accept, full-list endpoint | integration | `pytest -k appears_everywhere -x` | ❌ Wave 0 |

Bot-side (`MapNameSelect` swap, `get_all_map_names`) is verified via Spike 008's ported pagination
math and a unit test on the slice/`total_pages` logic with a DB-fed list; the discord.py UI itself
is manual-verify (no bot test harness in `apps/api/tests`).

### Sampling Rate
- **Per task commit:** `pytest apps/api/tests/integration/test_<touched>.py -x` (< 30s)
- **Per wave merge:** `just test-api` (full API suite, parallel)
- **Phase gate:** `just ci` green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] Map-create tests in `apps/api/tests/integration/test_content_integration.py` (extend) or a new
      `test_map_content_integration.py` — covers REQ-03/04/05/06.
- [ ] `validate_map_name` + `strip_key`/collision unit tests — covers REQ-02/06.
- [ ] `upload_map_banner` unit test with mocked S3 client — covers REQ-07.
- [ ] `GET /utilities/map-names` test in `test_autocomplete_integration.py` (extend) — REQ-08.
- [ ] Migration tests (FK orphan guard, seed idempotency, phantom reconciliation) — REQ-11/12/13.
      Check `test_tournaments_schema.py` for an existing schema-test pattern to mirror.
- [ ] Update 14 test files replacing `get_args(OverwatchMap)` with a seed-name constant (blocks the
      whole suite from running after the flip) — do this in the SAME wave as the SDK flip.
- [ ] Bot unit test for `MapNameSelect` pagination with DB-fed list — REQ-10.

## Sources

### Primary (HIGH confidence)
- Live codebase reads (this session): `libs/sdk/.../maps.py` (Literal :107, `get_map_banner` :1013),
  `apps/api/routes/v3/content.py`, `apps/api/routes/v3/utilities.py` (`upload_image` :31),
  `apps/api/services/image_storage_service.py` (`upload_screenshot` :44),
  `apps/api/services/content_service.py`, `apps/api/repository/content_repository.py`,
  `apps/api/routes/v3/autocomplete.py`, `apps/api/repository/autocomplete_repository.py`,
  `apps/bot/extensions/moderator.py` (`MapNameSelect` :756-789, `MapEditWizardView` :1273-1346),
  `apps/bot/extensions/api_service.py` (:788-813), `apps/api/migrations/0001_init.sql`
  (maps.names :817-1200, maps.mastery FK :1300), `apps/api/tests/conftest.py`.
- `grep -rln OverwatchMap` → 28 files (blast radius); `grep get_args` (MapCategory et al. stay).
- VALIDATED spikes 004–008 via `Skill("spike-findings-genjishimada")` →
  `references/dynamic-map-management.md` and `sources/007-multipart-banner-upload/app.py`.

### Secondary (MEDIUM confidence)
- `.planning/phases/15-dynamic-overwatch-map-management/15-CONTEXT.md` (locked decisions D-01..D-11).
- `CLAUDE.md` project conventions (three-layer, raw SQL, `$1,$2`, `CustomHTTPException`, scope guard).

### Tertiary (LOW confidence)
- None — all claims verified against live code or VALIDATED spikes.

## Project Constraints (from CLAUDE.md)
- Tech stack: Litestar + AsyncPG + msgspec; **no ORM**, raw SQL with `$1,$2` positional params.
- Three-layer: Controller (thin) → Service (logic/txn) → Repository (SQL). DI via `Provide(provide_*)`.
- Errors: `CustomHTTPException` from `utilities/errors.py`; repository exceptions
  (`UniqueConstraintViolationError`, `ForeignKeyViolationError`) → service → HTTP.
- Scopes: `opt={"required_scopes": {"content:admin"}}`; superusers bypass.
- Migrations: sequential `apps/api/migrations/NNNN_*.sql` — next is **0032**.
- Type hints required (ANN); `str | None` syntax; line length 120; Google docstrings.
- Logging: `log = getLogger(__name__)`, `%s` formatting, `log.exception()` for caught errors.
- DB access via injected `conn: Connection`; `self._get_connection(conn)` for pool fallback.
- Tests: `X-PYTEST-ENABLED=1` header skips queue publishing; pytest-databases per-test DB.
- **GSD workflow enforcement:** edits must go through a GSD command (this is execute-phase work).

## Metadata

**Confidence breakdown:**
- Blast radius / flip inventory: HIGH — exhaustive grep + file reads, every site categorised.
- Endpoint / multipart pattern: HIGH — VALIDATED Spike 007 on real Litestar + existing `upload_image`.
- Banner storage: HIGH — `get_map_banner()` + `upload_screenshot` read directly; D-05 derivation exact.
- Migration / seed / FK: HIGH — `0001_init.sql` and `maps.mastery` FK read directly; phantom count verified.
- Bot dropdown swap: HIGH — `MapNameSelect` + `MapEditWizardView` + both construction sites read.
- Cache-refresh on replace: MEDIUM — `immutable` header read; product expectation unconfirmed (Open Q1).

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (stable internal codebase; re-verify if SDK/migrations change before planning)
