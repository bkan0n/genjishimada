# Phase 15: Dynamic Overwatch Map Management - Pattern Map

**Mapped:** 2026-06-25
**Files analyzed:** 13 new/modified targets (+ ~14 test-fixture files, batched)
**Analogs found:** 13 / 13 (every new/modified file has a strong in-repo analog)

This phase is overwhelmingly *wiring existing patterns together*. There is no "no analog" section — every file copies from a live, working analog. The single net-new pattern (mixed-multipart create) is itself a fusion of two existing analogs (`upload_image` multipart route + `MovementTechController` create-endpoint shape).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/routes/v3/content.py` (ADD `create_map`/`replace_banner` + structs) | controller | request-response / file-I/O | same file — `MovementTechController.create_category` (content.py:252) + `upload_image` (utilities.py:31) | exact (same file) |
| `apps/api/services/<map_content>_service.py` (NEW or extend `content_service.py`) | service | CRUD / file-I/O | `ContentService.create_category` (content_service.py:65) + `create_technique` txn (content_service.py:264) | exact (role+flow) |
| `apps/api/repository/<map_content>_repository.py` (NEW or extend `content_repository.py`) | repository | CRUD | `ContentRepository.create_category` (content_repository.py:117) | exact |
| `apps/api/services/image_storage_service.py` (ADD `upload_map_banner`) | service | file-I/O | `ImageStorageService.upload_screenshot` (image_storage_service.py:44) — ADAPT key derivation | role-match (key differs) |
| `apps/api/routes/v3/autocomplete.py` (ADD `list_all_map_names`) | controller | request-response | `AutocompleteController.get_similar_map_names` (autocomplete.py:21) | exact |
| `apps/api/repository/autocomplete_repository.py` (ADD `fetch_all_map_names`) | repository | CRUD (read) | `AutocompleteRepository.get_similar_map_names` (autocomplete_repository.py:16) | exact |
| `libs/sdk/src/genjishimada_sdk/maps.py` (Literal → `str` at :107) | model (type alias) | transform | n/a — definition edit; all consumers keep compiling (see §Shared/Flip) | exact (1-line) |
| `apps/bot/extensions/moderator.py` (`MapNameSelect.__init__` :761) | component (UI) | event-driven | `MapNameTransformer` (transformers.py:21, already DB-backed) — same DB-fed sourcing | role-match |
| `apps/bot/extensions/api_service.py` (ADD `get_all_map_names`) | service (HTTP client) | request-response | `get_autocomplete_map_names` (api_service.py:788) | exact |
| `apps/api/migrations/0032_dynamic_map_management.sql` (NEW: FK + orphan guard + reconcile) | migration | batch | `maps.mastery` FK (0001_init.sql:1300) | exact (FK shape) |
| `apps/api/migrations/0001_init.sql` (REWRITE seed → `ON CONFLICT`) | migration (seed) | batch | current 63 plain INSERTs (0001_init.sql:823+) — collapse to one block | exact (in-file) |
| `scripts/export_map_names_seed.py` (NEW standalone export) | utility (script) | batch | no exact analog — DB read → SQL text; lowest-risk, plain asyncpg | role-only |
| `apps/api/tests/**` (~14 files, replace `get_args(OverwatchMap)`) | test | — | `test_maps_repository_create_core_map.py:93` fixture | exact |

---

## Pattern Assignments

### `apps/api/routes/v3/content.py` — ADD `create_map` (controller, request-response + file-I/O)

**Analogs:** `MovementTechController` (same file) for class structure/scope/error-to-HTTP; `upload_image` (`utilities.py:31`) for the multipart wiring.

**Imports already present in content.py (1-27) — reuse, add UploadFile/Body/RequestEncodingType:**
```python
import msgspec
from litestar import Controller, delete, get, post, put
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_201_CREATED, HTTP_409_CONFLICT
# ADD for multipart (copy from utilities.py:8-12):
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body
from typing import Annotated
```

**Multipart route wiring — fuse `upload_image` (utilities.py:31-56) with the content create-endpoint shape (content.py:252-280).** `upload_image` is *sync* (`sync_to_thread=False`, `data.file.read()`); the create endpoint does async DB work, so use the **async** form (`await data.banner.read()`) per RESEARCH Pattern 1:
```python
class MapCreateMultipart(msgspec.Struct):
    name: str
    banner: UploadFile

@post(
    path="/maps",                                   # controller path is "/content/movement-tech";
    status_code=HTTP_201_CREATED,                   # use a sibling controller path "/content" or add here
    summary="Create Overwatch Map",
    opt={"required_scopes": {"content:admin"}},     # SAME scope as every MovementTech admin route
    request_max_body_size=1024 * 1024 * 25,         # 25 MB — matches upload_image (utilities.py:37)
)
async def create_map(
    self,
    data: Annotated[MapCreateMultipart, Body(media_type=RequestEncodingType.MULTI_PART)],
    map_content_service: MapContentService,         # inject via controller `dependencies` like content_service
) -> MapCreateResponse:
    content = await data.banner.read()
    content_type = data.banner.content_type or "image/png"
    row = await map_content_service.create_map(data.name, content, content_type)
    return msgspec.convert(row, MapCreateResponse)
```

**Error-to-HTTP pattern — copy verbatim from content.py:276-280 (the try/except + `from e` + `msgspec.convert` shape).** The service raises domain/HTTP errors; controller converts. For the 422 guards (empty name, stripped collision) the service raises `CustomHTTPException` directly (already an HTTP exception) so the controller may not need to catch them — confirm during planning. Duplicate-name behaviour: RESEARCH Open Q2 — default to idempotent 201 (`ON CONFLICT DO NOTHING`), optionally an `inserted: bool` flag.

**Controller `dependencies` block — copy the shape from content.py:185-188:**
```python
dependencies = {
    "map_content_repo": Provide(provide_map_content_repository),
    "map_content_service": Provide(provide_map_content_service),
}
```

---

### `apps/api/services/<map_content>_service.py` — `create_map` (service, CRUD + file-I/O)

**Analog:** `ContentService.create_category` (content_service.py:65-80) for the create+UniqueViolation→domain-error shape; `ContentService.create_technique` (content_service.py:264-310) for the **`async with self._pool.acquire() as conn, conn.transaction():`** multi-step pattern.

**Class skeleton + DI provider — copy content_service.py:23-35 and :453-458 verbatim, rename:**
```python
class MapContentService(BaseService):
    def __init__(self, pool: Pool, state: State, map_content_repo: MapContentRepository) -> None:
        super().__init__(pool, state)
        self._map_content_repo = map_content_repo

async def provide_map_content_service(state: State, map_content_repo: MapContentRepository) -> MapContentService:
    return MapContentService(state.db_pool, state, map_content_repo)
```

**`create_map` ordering — RESEARCH Pitfall 1 (transaction-abort poisoning).** Run guards + S3 upload BEFORE opening the transaction; the `ON CONFLICT DO NOTHING` insert is the only fallible DB statement:
```python
import difflib  # RESEARCH Pattern 2/3; difflib is the chosen "did you mean" tool
from utilities.errors import CustomHTTPException
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

async def create_map(self, name: str, banner: bytes, content_type: str) -> dict:
    # 1. empty-name guard (D-07 / REQ-05) -> 422
    if not name.strip():
        raise CustomHTTPException(detail="Map name cannot be empty.", status_code=HTTP_422_UNPROCESSABLE_ENTITY)
    # 2. stripped-key collision guard (D-07 / REQ-06) -> 422  (Pattern 3 below)
    existing = await self._map_content_repo.fetch_all_map_names()
    target = _strip_key(name)
    for other in existing:
        if other != name and _strip_key(other) == target:
            raise CustomHTTPException(
                detail=(f"Map name '{name}' collides with existing '{other}' "
                        f"(both resolve to banner key '{target}')."),
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            )
    # 3. upload banner (REQ-07) — uses ImageStorageService.upload_map_banner
    self._image_svc.upload_map_banner(banner, content_type, name)
    # 4. single clean insert (REQ-03) — ON CONFLICT DO NOTHING, idempotent (doubles as replace, A5)
    return await self._map_content_repo.insert_map_name(name)
```
Note: `ImageStorageService` must be injected into this service (add to its `__init__` / provider, mirroring how `content_service` injects `content_repo`). For the consumer-side `validate_map_name` (REQ-02, submission path) copy RESEARCH Pattern 2 verbatim (`difflib.get_close_matches(name, known, n=3, cutoff=0.6)`).

**`_strip_key` helper — must match `get_map_banner()` exactly (maps.py:1015-1016):**
```python
import re
def _strip_key(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")
```

---

### `apps/api/repository/<map_content>_repository.py` — `insert_map_name` / `fetch_all_map_names` (repository, CRUD)

**Analog:** `ContentRepository.create_category` (content_repository.py:117-150) for the INSERT + `self._get_connection(conn)` + asyncpg exception translation shape.

```python
async def insert_map_name(self, name: str, *, conn: Connection | None = None) -> dict:
    _conn = self._get_connection(conn)
    query = """
    INSERT INTO maps.names (name) VALUES ($1)
    ON CONFLICT DO NOTHING
    RETURNING name
    """
    row = await _conn.fetchrow(query, name)
    # ON CONFLICT DO NOTHING returns no row when the name already existed (A5/Open Q2)
    return {"name": name, "inserted": row is not None}

async def fetch_all_map_names(self, *, conn: Connection | None = None) -> list[str]:
    _conn = self._get_connection(conn)
    rows = await _conn.fetch("SELECT name FROM maps.names ORDER BY name")
    return [r["name"] for r in rows]
```
**Param style:** `$1` positional (asyncpg). **Connection fallback:** `self._get_connection(conn)` — both verbatim conventions from content_repository.py. Note: the collision guard reads ALL names anyway, so `fetch_all_map_names` is reused by both the service guard and the `GET /utilities/map-names` endpoint (D-02).

---

### `apps/api/services/image_storage_service.py` — ADD `upload_map_banner` (service, file-I/O)

**Analog:** `upload_screenshot` (image_storage_service.py:44-66) — copy the `io.BytesIO` + `client.upload_fileobj` + `ExtraArgs` plumbing EXACTLY; **change only the key derivation** (D-05: stripped name, NOT date+digest). RESEARCH Pitfall 4: the key MUST end `.png` regardless of source content-type, because `get_map_banner()` (maps.py:1017) hardcodes `.png`.

```python
def upload_map_banner(self, content: bytes, content_type: str, map_name: str) -> str:
    stripped = re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")  # match get_map_banner()
    key = f"assets/map_banners/{stripped}.png"   # .png ALWAYS (read path hardcodes it)
    self.client.upload_fileobj(
        io.BytesIO(content),
        S3_BUCKET_NAME,
        key,
        ExtraArgs={
            "ContentType": content_type,
            "CacheControl": "public, max-age=31536000, immutable",  # same as upload_screenshot:63
        },
    )
    return f"{S3_PUBLIC_URL}/{key}"
```
**DO NOT copy** `upload_screenshot`'s `digest`/`today`/`_ext_from_content_type` key logic — that produces a non-`get_map_banner()`-resolvable key (RESEARCH anti-pattern). `import re` at module top (file currently imports `hashlib, io, os, dt` — add `re`). Replace-banner (D-03/REQ-04) is automatic: re-upload overwrites the same key. Known limitation: CDN `immutable` may serve stale until TTL (RESEARCH Open Q1) — consider a shorter `max-age` for banners.

---

### `apps/api/routes/v3/autocomplete.py` — ADD `list_all_map_names` (controller, request-response)

**Analog:** `get_similar_map_names` (autocomplete.py:21-41) — same controller (`path="/utilities"`, `dependencies` already has `autocomplete`). D-02: NO `search`, NO `limit`, returns `list[str]`. Do NOT touch the existing `/autocomplete/names` route.

```python
@get(
    path="/map-names",
    tags=["Autocomplete"],
    summary="List All Map Names",
    description="Return all Overwatch map names alphabetically. Full list, no search/limit.",
)
async def list_all_map_names(self, autocomplete: AutocompleteRepository) -> list[str]:
    return await autocomplete.fetch_all_map_names()
```

### `apps/api/repository/autocomplete_repository.py` — ADD `fetch_all_map_names` (repository, read)

**Analog:** `get_similar_map_names` (autocomplete_repository.py:16-36) — same `_get_connection(conn)` + `_conn.fetch` + `[r["name"] for r in res]` shape, but query is `SELECT name FROM maps.names ORDER BY name` (no similarity, no params). Type hint return `list[str]` (NOT `list[OverwatchMap]`).
```python
async def fetch_all_map_names(self, *, conn: Connection | None = None) -> list[str]:
    _conn = self._get_connection(conn)
    rows = await _conn.fetch("SELECT name FROM maps.names ORDER BY name")
    return [r["name"] for r in rows]
```
> Implementation note for planner: `fetch_all_map_names` is needed by BOTH the autocomplete repo (for the GET endpoint, D-02) AND the map-content service (for the collision guard). Decide whether to duplicate the trivial query or share — either is fine; the query is identical.

---

### `libs/sdk/src/genjishimada_sdk/maps.py` — `OverwatchMap` Literal → `str` (model, the crux)

**The single behavioural edit** (maps.py:107-178): replace the 70-entry `Literal[...]` with `OverwatchMap = str`. Keep the name exported (it's in `__all__` and imported by ~27 files) so every consumer keeps compiling with zero edits (RESEARCH §A/B, Assumption A1). `get_map_banner()` (maps.py:1013-1017) already takes `map_name: str` — no change. **Leave `MapCategory` (maps.py:101), `Mechanics`, `Restrictions`, `Tags`, `DifficultyAll` Literals untouched.**

After this edit, two consumer classes break and need the changes below:
1. `apps/bot/extensions/moderator.py:768` — `get_args(str)` returns `()` (next section).
2. ~14 test files — `get_args(str)` returns `()` → `random_element([])` raises (Shared Pattern §Test-fixture flip).

All other ~18 sites are type-only annotations that keep compiling.

---

### `apps/bot/extensions/moderator.py` — `MapNameSelect.__init__` DB-fed (component, event-driven)

**THE one bot behavioural change** (moderator.py:761-779). `MapNameSelect.__init__` is a sync `ui.Select` subclass — cannot `await` (RESEARCH Pattern 5 / Spike 008). Source the list from a constructor param fetched once in the async wizard-build context.

**Analog for "where the names come from":** `MapNameTransformer` (transformers.py:32) already calls `itx.client.api.transform_map_name(...)` — the bot already sources map names from the API at runtime. Apply the same DB-fed sourcing here.

**Change `__init__` (keep the slice / total_pages / SelectOption math VERBATIM — Spike 008 proved it):**
```python
def __init__(self, current: str | None, all_maps: list[str], page: int = 0) -> None:
    all_maps = sorted(all_maps)                          # was: list(get_args(OverwatchMap)); all_maps.sort()
    start_idx = page * _PAGINATED_SELECT_PAGE_SIZE       # UNCHANGED
    end_idx = start_idx + _PAGINATED_SELECT_PAGE_SIZE
    page_maps = all_maps[start_idx:end_idx]
    options = [SelectOption(label=m, value=m, default=(m == current)) for m in page_maps]
    super().__init__(placeholder=f"Select map name (page {page + 1})...", options=options)
    self.page = page
    self.total_pages = (len(all_maps) + _PAGINATED_SELECT_PAGE_SIZE - 1) // _PAGINATED_SELECT_PAGE_SIZE
```

**Thread the fetched list through.** `MapNameSelect` is constructed in `rebuild()` (moderator.py:1334). `rebuild()` runs inside `MapEditWizardView`, constructed at TWO async sites:
- `apps/bot/extensions/moderator.py:105` — `MapEditWizardView(map_data, is_mod=True)`
- `apps/bot/extensions/map_editor.py:61` — `MapEditWizardView(map_data, is_mod=False)`

At both sites, fetch once (`all_maps = await itx.client.api.get_all_map_names()`) and pass into `MapEditWizardView.__init__` → store on `self` → pass to `MapNameSelect(current, all_maps=self._all_maps, page=...)` at moderator.py:1334-1337. **`moderator.py:743` `get_args(MapCategory)` STAYS a Literal.**

---

### `apps/bot/extensions/api_service.py` — ADD `get_all_map_names` (service, HTTP client)

**Analog:** `get_autocomplete_map_names` (api_service.py:788-800) — same `Route(...)` + `self._request(r, response_model=...)` shape; drop `search`/`limit`/`params`, return `list[str]`.
```python
def get_all_map_names(self) -> Response[list[str]]:
    """Return all Overwatch map names (full list, no search)."""
    r = Route("GET", "/utilities/map-names")
    return self._request(r, response_model=list[str])
```

---

### `apps/api/migrations/0032_dynamic_map_management.sql` — FK + orphan guard + phantom reconcile (migration, batch)

**Analog:** the `maps.mastery` FK (0001_init.sql:1300): `CONSTRAINT ... REFERENCES maps.names (name) ON UPDATE CASCADE`. Mirror it on `core.maps.map_name`. Sequence per RESEARCH Pitfall 5: reconcile phantoms (D-08) → orphan pre-flight (D-11, fail loud) → add FK.
```sql
-- 1. Reconcile 7 phantom Literal-only maps (D-08) so the FK can be added.
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
        RAISE EXCEPTION 'Cannot add FK: orphan core.maps.map_name not in maps.names: %', orphan;
    END IF;
END $$;

-- 3. FK backstop (D-11) — mirrors maps.mastery.map_name (0001_init.sql:1300).
ALTER TABLE core.maps
    ADD CONSTRAINT maps_map_name_names_fk
    FOREIGN KEY (map_name) REFERENCES maps.names (name)
    ON UPDATE CASCADE;
```
**Number:** highest existing is `0031_skill_history.sql` → this is `0032` (verified by `ls`). The seed migration block uses `IF NOT EXISTS`-style idempotency elsewhere; this migration is one-shot DDL (no `IF NOT EXISTS` on `ADD CONSTRAINT` — acceptable, runs once).

### `apps/api/migrations/0001_init.sql` — idempotent seed rewrite (migration seed, batch)

**Current shape (0001_init.sql:823-~1200):** 63 separate `INSERT INTO maps.names (name) VALUES ('X');` statements — non-idempotent (replay → duplicate-PK error, D-09). **Collapse to ONE `ON CONFLICT DO NOTHING` block** including all 70 reconciled names (the 63 live + 7 phantoms) so a fresh from-migrations bootstrap matches the reconciled live DB:
```sql
INSERT INTO maps.names (name) VALUES
    ('Circuit Royal'), ('Runasapi'), ('Practice Range'), -- ... all 70 names ...
    ('Arena Victoriae'), ('Gogadoro'), ('Neon Junction'), ('Place Lacroix'),
    ('Powder Keg Mine'), ('Redwood Dam'), ('Thames District')
ON CONFLICT DO NOTHING;
```
Source the 70 names from the `OverwatchMap` Literal (maps.py:107-178) as it stands BEFORE the flip (capture the list before editing it to `str`).

---

### `scripts/export_map_names_seed.py` — standalone export (utility, batch) — WEAKEST analog

No exact in-repo analog (no existing seed-export script). D-10: manual-run only, NEVER request-path, NOT wired into nightly backup. Lowest-risk approach: plain `asyncpg.connect` (read `SELECT name FROM maps.names ORDER BY name`), emit the same `INSERT ... ON CONFLICT DO NOTHING` block shape as the 0001 seed. Reuse the env-var names from `image_storage_service.py`/CLAUDE.md (`POSTGRES_*`). Keep it dependency-light; this is the one file the planner should treat as net-new rather than copy-from-analog.

---

### `apps/api/tests/**` — replace `get_args(OverwatchMap)` (test) — do in the SAME wave as the SDK flip

**Analog/target:** `test_maps_repository_create_core_map.py:93` — `"map_name": fake.random_element(elements=get_args(OverwatchMap))`. After the flip `get_args(str)` → `()` → `random_element([])` raises (RESEARCH Pitfall 6). Replace with a module-level seed-name constant:
```python
_SEED_MAP_NAMES = ["Hanamura", "Busan", "Ilios", "Nepal", "Oasis"]  # any subset of seeded maps.names
# was: fake.random_element(elements=get_args(OverwatchMap))
"map_name": fake.random_element(elements=_SEED_MAP_NAMES),
```
**Keep `get_args(MapCategory)` / `get_args(PlaytestStatus)` in the SAME lines untouched** (create_core_map.py:94,97). Affected files (RESEARCH §F): `tests/conftest.py:346`; `tests/repository/maps/test_maps_repository_{advanced_operations,check_code_exists,create_core_map,entity_operations,fetch_partial_map,guide_operations,update_core_map}.py`; `tests/repository/community/test_community_repository_popular.py`. (`test_maps_integration.py:881` uses string literal `"Nepal"` — no change.)

---

## Shared Patterns

### Three-layer Controller → Service → Repository + Litestar DI
**Source:** `content.py` (controller) → `content_service.py` (service) → `content_repository.py` (repository).
**Apply to:** the entire add-map feature. Controller is thin (decode → call service → `msgspec.convert` → return); service owns logic + transactions + S3; repository owns raw SQL. DI via `dependencies = {"x": Provide(provide_x)}` on the controller (content.py:185-188) and `provide_*` functions at module bottom (content_service.py:453).

### Scope guard
**Source:** every `MovementTechController` admin route — `opt={"required_scopes": {"content:admin"}}` (content.py:257, :286, :321, ...).
**Apply to:** `POST /content/maps` (write). The GET `/utilities/map-names` follows the autocomplete controller (no explicit scope; it inherits the global auth unless `exclude_from_auth`). Superusers bypass; the test client (`X-API-KEY: testing`) is superuser, so tests bypass scope (A4).

### Error handling — three-tier, controller converts to HTTP
**Source:** content.py:276-280 (`try: ... except DuplicateNameError as e: raise HTTPException(...) from e`) + content_service.py:79 (`except UniqueConstraintViolationError ... raise DuplicateNameError`) + content_repository.py:143-149 (asyncpg → repository exception).
**Apply to:** all service/repo paths. NOTE the 422 guards (empty-name, collision) raise `CustomHTTPException` (from `utilities/errors.py`) directly in the service — these are already HTTP exceptions, so no controller catch needed. `from e` to preserve the chain (CLAUDE.md).

### Transaction safety — avoid abort poisoning
**Source:** `content_service.py:295` — `async with self._pool.acquire() as conn, conn.transaction():` wrapping the multi-statement create.
**Apply to:** `create_map`. RESEARCH Pitfall 1 / CONTEXT specifics: run validation + S3 upload BEFORE opening the txn; let `INSERT ... ON CONFLICT DO NOTHING` be the only fallible DB statement so a caught violation can't poison a later statement.

### Banner key derivation — single source of truth
**Source:** `get_map_banner()` (maps.py:1015-1016) — `re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")`.
**Apply to:** `upload_map_banner` (write key) AND `_strip_key` (collision guard). All three must produce identical output, and the stored object MUST be `.png` (read path hardcodes the extension at maps.py:1017). This is the load-bearing contract of D-05.

### SQL / repository conventions (CLAUDE.md, verified live)
**Apply to:** every new query. `$1, $2` positional params; `self._get_connection(conn)` for pool/txn fallback; `*, conn: Connection | None = None` keyword-only; `fetchrow`/`fetch`/`fetchval`; `dict(row)` / `[r["x"] for r in rows]` conversion.

### Bot HTTP client convention
**Source:** `api_service.py:788` — `r = Route(METHOD, path[, **path_params]); return self._request(r, params=..., response_model=...)`.
**Apply to:** `get_all_map_names`.

---

## No Analog Found

| File | Role | Data Flow | Reason / Mitigation |
|------|------|-----------|---------------------|
| `scripts/export_map_names_seed.py` | utility script | batch | No existing standalone DB-export script in repo. Lowest-risk: plain `asyncpg.connect` + emit the `ON CONFLICT` seed block. Treat as net-new (see assignment above). RESEARCH §Code Examples gives the output shape. |

Everything else copies from a live, in-repo analog. The "new" mixed-multipart create endpoint is a fusion of two existing analogs (`upload_image` route + `MovementTechController` create shape), not net-new infrastructure.

---

## Metadata

**Analog search scope:** `apps/api/routes/v3/`, `apps/api/services/`, `apps/api/repository/`, `apps/api/migrations/`, `apps/api/tests/`, `apps/bot/extensions/`, `apps/bot/utilities/`, `libs/sdk/src/genjishimada_sdk/`.
**Files scanned (read in full or targeted):** content.py, utilities.py, content_service.py, image_storage_service.py, content_repository.py, autocomplete.py, autocomplete_repository.py, maps.py (SDK, 3 ranges), moderator.py (3 ranges), api_service.py, transformers.py, map_editor.py, 0001_init.sql (3 ranges), test fixtures.
**Pattern extraction date:** 2026-06-25
