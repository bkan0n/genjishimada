---
spike: 007
name: multipart-banner-upload
type: standard
validates: "Given a running real-Litestar endpoint, when an admin POSTs a mixed multipart/form-data body (map-name text field + banner UploadFile), then Litestar decodes both together, the banner is stored under a stable assets/map_banners/<sanitized>.png key that get_map_banner() re-derives, and the name is inserted — one request, no restart"
verdict: VALIDATED
related: [005, 004, 006]
tags: [maps, litestar, multipart, s3]
---

# Spike 007: multipart-banner-upload

## What This Validates

> **Given** a running **real Litestar** endpoint with no restart,
> **when** an admin POSTs a *mixed* `multipart/form-data` body — a map-name **text field**
> *and* a banner **file** (`UploadFile`) — in one request,
> **then** Litestar decodes both together, the banner lands at a **stable**
> `assets/map_banners/<sanitized>.png` key that `get_map_banner()` re-derives, and the name is
> inserted into `maps.names`.

Spike 005 proved the end-to-end "appears everywhere" feeling using **base64-in-JSON**. The real app
takes `multipart/form-data`. A pure single-file endpoint already exists
(`apps/api/routes/v3/utilities.py:upload_image` → `Annotated[UploadFile, Body(MULTI_PART)]` →
`ImageStorageService.upload_screenshot`). The **unproven** piece this spike isolates is the *mixed*
body: a `msgspec.Struct` field **plus** an `UploadFile` decoded from one request — and storing the
banner under a *stable* key (not the dated/digested `screenshots/...` key) so the existing
`get_map_banner()` derivation keeps resolving it.

## Research

No external docs needed — this is empirical verification of Litestar's own multipart decoder, which
is far stronger than reading docs. Approach decided up front:

| Approach | How | Verdict |
|----------|-----|---------|
| Two requests (name JSON, then file) | client orchestrates | rejected — not atomic, two round-trips, what 005 implicitly avoided |
| Base64 file inside JSON struct | as Spike 005 | works but bloats payload ~33%, not how browsers post files |
| **Mixed multipart: `Struct{name:str, banner:UploadFile}`** | `Annotated[Struct, Body(media_type=RequestEncodingType.MULTI_PART)]` | **chosen** — single atomic request, native browser `FormData`, mirrors real CMS shape |

**Deviation from CONVENTIONS** (which mandate stdlib `http.server`): justified and necessary — the
question is *specifically* about Litestar's multipart behaviour, so the spike runs **real Litestar**
(`litestar[standard]`, already a project dep, ships uvicorn). Everything else follows conventions:
real local Postgres + MinIO, throwaway `spike007` schema seeded from `maps.names`, `spike007/` MinIO
prefix, cleanup in the lifespan `finally`, forensic in-memory log at `GET /api/log`.

## How to Run

```bash
# from this directory; requires docker compose -f docker-compose.local.yml up -d postgres-local minio-local
uv run --env-file ../../../.env.local \
  --with 'litestar[standard]' --with asyncpg --with boto3 --with msgspec \
  python -u app.py
# open http://localhost:8077  — upload a name + banner, watch it appear; Ctrl-C to stop (auto-cleans)
```

**Isolation:** startup drops/creates `spike007` schema, seeds `spike007.names` from the real
`maps.names` (63 maps), writes banners under MinIO `spike007/`. SIGINT the **listener** PID
(`lsof -ti tcp:8077`) — not the `uv` wrapper — so the lifespan `finally` runs: deletes the MinIO
objects and drops the schema. Real data is never touched.

## What to Expect

- Browser form (`FormData`) or `curl -F 'name=...' -F 'banner=@file.png'` → one multipart POST.
- Response: `{"ok":true,"name":...,"banner_key":"spike007/assets/map_banners/<sanitized>.png","inserted":true}`.
- The map appears in the live grid with its banner served by `GET /api/banner?name=` — which
  **re-derives the same key from the name** (never persists a URL), exactly as `get_map_banner()` does.
- Re-POST the same name → `inserted:false` (idempotent `ON CONFLICT DO NOTHING`).

## Observability

In-memory forensic log (ISO ts, categories `setup`/`upload`/`teardown`) at `GET /api/log`, rendered
live in the page. Each upload records decoded `name`, `banner_filename`, `content_type`,
`banner_bytes`, and the stored `key` — so the mixed-decode is auditable byte-for-byte.

## Investigation Trail

1. **Built the mixed-multipart endpoint on real Litestar.** `MapBannerUpload(msgspec.Struct)` with
   `name: str` + `banner: UploadFile`, taken as `Annotated[MapBannerUpload, Body(media_type=MULTI_PART)]`.
   Smoke test (`curl -F name=... -F banner=@png`): **decoded both** — `{ok:true, inserted:true}`,
   banner at `spike007/assets/map_banners/spiketestmap.png`. 63→64 maps.
2. **Banner round-trip proves stable-key derivation.** `GET /api/banner?name=Spike Test Map`
   re-derives the identical key from the name and returns **HTTP 200, 67 bytes, image/png**. The URL
   is never stored — the name is the only persisted thing, and the key is recomputed. This is exactly
   the contract `get_map_banner()` relies on.
3. **Idempotency.** Re-POSTing `Spike Test Map` → `inserted:false`. `ON CONFLICT DO NOTHING` holds.
4. **Required-field validation is preserved across the multipart boundary (surprise upside).** POST
   with the `banner` part but **no `name` field** → Litestar returns a clean **400**:
   `{"detail":"Validation failed","extra":[{"message":"Object missing required field 'name'",...}]}`.
   msgspec validates the multipart struct exactly like a JSON body — we don't lose boundary validation
   by switching to multipart.
5. **Litestar populates `UploadFile` metadata from the part headers.** Log confirms `filename`,
   `content_type` (`image/png`), and byte length all arrive correctly — so the real
   `ImageStorageService.upload_screenshot(content, content_type)` signature is fed directly.
6. **Stable-key sanitization is LOSSY and can COLLIDE — the decisive finding.** Probed real-shaped
   names through the `get_map_banner()`-style `re.sub(r"[^a-zA-Z0-9]","",name).lower()`:
   - `Château Guillard` → `chteauguillard` (the **â is silently dropped**).
   - `King's Row` → `kingsrow` **and** `Kings Row` → `kingsrow` — **same key**. Two distinct maps
     overwrite each other's banner.
   Real OW maps carry apostrophes/accents (King's Row, Château Guillard, Lijiang Tower, Eichenwalde),
   so the "stable derived key" is **not collision-free** for the dynamic-add case.
7. **Verified clean teardown.** SIGINT the listener → lifespan `finally` deleted 5 MinIO objects and
   dropped `spike007`; confirmed `spike007 schema exists: False`. Exit 0.

## Results

**VALIDATED.** A single real-Litestar `multipart/form-data` endpoint cleanly decodes a mixed body
(`msgspec.Struct` text field + `UploadFile`), preserves msgspec boundary validation (missing field →
400), exposes correct file metadata, stores the banner, inserts the name idempotently, and the banner
round-trips by key re-derivation — all with no restart, against real Postgres + MinIO.

**Signal for the build:**
- **The mixed-multipart shape works as-is.** Real endpoint: `data: Annotated[MapCreateMultipart,
  Body(media_type=RequestEncodingType.MULTI_PART)]` with `name: str` + `banner: UploadFile`, mirroring
  the existing `upload_image` route + the movement-tech CMS controller pattern
  (`opt={"required_scopes": {"content:admin"}}`). Set `request_max_body_size` like `upload_image` (25 MB).
- **Reuse `ImageStorageService`, but add a stable-key upload method.** Today's `upload_screenshot`
  keys by date + content digest (`screenshots/YYYY/MM/DD/<blake2b>.ext`) — good for screenshots,
  wrong for banners (a new digest every re-upload, never `get_map_banner()`-resolvable). Add e.g.
  `upload_map_banner(content, content_type, map_name) -> url` that writes to a stable key.
- **RESOLVE the sanitization collision before shipping (this is the real decision).** The lossy
  alphanumeric-only key collides on punctuation-only-different names and drops accented chars. Two
  options — the spike makes the case for (b):
  - (a) keep the derived stable key but **add a uniqueness guard** (reject/alert if the sanitized stem
    already maps to a different `maps.names.name`).
  - (b) **store the returned URL in a new `maps.names.banner_url` column** and key the object by
    something guaranteed-unique (URL-encoded exact name, a surrogate id, or a content digest like
    `upload_screenshot`). The reference flagged `banner_url` as "decide at plan time"; this spike is
    the decisive reason to prefer it — derived keys are not safe for arbitrary new map names.
- **Keep the msgspec boundary validation** — switching to multipart did not weaken it; required
  fields still 400 at the boundary, complementing the runtime `maps.names` check from Spike 004.
- **Empty/blank `name` should 422**, not 201 — the spike returned a soft `{ok:false}`; the real
  service should raise a `CustomHTTPException` (project convention).
