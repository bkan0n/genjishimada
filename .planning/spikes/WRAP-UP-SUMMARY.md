# Spike Wrap-Up Summary

Cumulative record of spike wrap-up sessions. Latest session at top.

---

## Session 3 — Dynamic Map Management (banner upload + moderator dropdown)

**Date:** 2026-06-25
**Spikes processed:** 2 (007–008)
**Feature areas:** Dynamic map management (appended to the existing reference)
**Skill output:** `./.claude/skills/spike-findings-genjishimada/` (appended)

### Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 007 | multipart-banner-upload | standard | VALIDATED | Dynamic map management |
| 008 | moderator-mapname-dropdown | standard | VALIDATED | Dynamic map management |

### Key Findings

- **The mixed-multipart upload shape works on real Litestar.** A `msgspec.Struct` with `name: str` +
  `banner: UploadFile`, taken as `Annotated[..., Body(media_type=RequestEncodingType.MULTI_PART)]`,
  decodes both parts in one request — mirroring the existing `upload_image` route and native browser
  `FormData`. **msgspec boundary validation survives the switch:** a missing `name` part still returns
  a clean 400, so multipart complements (does not replace) the runtime `maps.names` check. (Spike 007)
- **Decisive finding — the derived banner key is unsafe for arbitrary new maps.** The
  `get_map_banner()`-style `re.sub(r"[^a-zA-Z0-9]","",name).lower()` is **lossy** (`Château Guillard`
  → `chteauguillard`, the accent dropped) and **collides** (`King's Row` and `Kings Row` → `kingsrow`,
  one overwrites the other). Real OW maps carry apostrophes/accents, so the dynamic-add path must store
  the upload URL in a new **`maps.names.banner_url` column** and key the object uniquely (content
  digest / surrogate id / URL-encoded name) — not reuse `upload_screenshot` (date+digest key, never
  `get_map_banner()`-resolvable). Add a dedicated `upload_map_banner` method. Empty/blank name → 422.
  (Spike 007)
- **A full-list names endpoint must be added — it does not exist today.**
  `/utilities/autocomplete/names` is search-required, `limit=5`, similarity-ordered, typed
  `list[OverwatchMap]` — type-ahead only. Add `GET /utilities/map-names → list[str]`
  (`SELECT name FROM maps.names ORDER BY name`) for the moderator dropdown. (Spike 008)
- **The moderator `MapNameSelect` is the one bot spot the Literal removal silently breaks.** It builds
  options from `get_args(OverwatchMap)`; after the Literal becomes `str` that returns nothing. Spike
  008 ported the 25/page pagination math **verbatim**, swapping only the source of `all_maps`
  (Literal → DB), and proved it behaviour-preserving: correct `total_pages`, live pickup of inserts
  with no restart, a new page materialising past a 25-boundary. The only real work is sourcing the list
  from the new endpoint and fetching it **once** at async view-build time (the `__init__` is sync and
  can't `await`). `get_args(MapCategory)` in the same file is a different, legitimately-static Literal
  and stays. (Spike 008)
- **Conventions reinforced:** use the real framework when the question *is* the framework's behaviour
  (Spike 007 ran real Litestar despite the stdlib-`http.server` default); port real code verbatim and
  swap only the variable under test (Spike 008); probe real-shaped inputs — the banner-key collision
  only surfaced by feeding actual apostrophe/accent map names. All captured in CONVENTIONS.md.

---

## Session 2 — Dynamic Overwatch Map Management

**Date:** 2026-06-25
**Spikes processed:** 3 (004–006)
**Feature areas:** Dynamic map management
**Skill output:** `./.claude/skills/spike-findings-genjishimada/` (appended)

### Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 004 | runtime-map-validation | standard | VALIDATED | Dynamic map management |
| 005 | upload-map-live | standard | VALIDATED | Dynamic map management |
| 006 | map-durability | standard | VALIDATED | Dynamic map management |

### Key Findings

- **The `OverwatchMap` Literal is the only blocker.** msgspec validates the closed `Literal` strictly,
  so `MapCreateRequest.map_name` rejects any new map at request-decode time until the SDK regenerates
  and every service redeploys. `maps.names`, `MapNameTransformer`, and the `maps.mastery` FK are
  already DB-driven. (Spike 004)
- **Replace the Literal with `str` + a runtime check against `maps.names`** (service layer), backed by
  a new FK on `core.maps.map_name → maps.names.name` as defence-in-depth. Runtime validation is *better
  DX* than the Literal — `difflib.get_close_matches` gives "did you mean" suggestions the closed
  Literal never could. The only thing lost is compile-time typo-checking of hardcoded map-name string
  literals — narrow, and was never enforced on DB/request/bot-sourced names anyway. (Spike 004)
- **Already-present drift bug:** the SDK Literal (70) and `maps.names` (63) disagree by 7 maps
  (Arena Victoriae, Gogadoro, Neon Junction, Place Lacroix, Powder Keg Mine, Redwood Dam, Thames
  District). DB-as-single-source-of-truth fixes this entire class of inconsistency. Reconcile the 7 into
  `maps.names` when writing the new seed. (Spike 004)
- **One DB-only endpoint makes a map appear on all three surfaces with no restart.** `POST` name +
  banner → `INSERT INTO maps.names ... ON CONFLICT DO NOTHING` + banner to object storage. Website
  reads, submission validation, and bot autocomplete all read the live DB, so they update live.
  Verified end-to-end against real Postgres + MinIO. Mirror the movement-tech CMS pattern
  (Controller → Service → Repository, `content:admin` scope); reuse `ImageStorageService`. (Spike 005)
- **Durability via a committed idempotent seed, regenerated by a separate export job.** Endpoint stays
  DB-only (instant); a migration-only rebuild would otherwise drop dynamic maps. Replace the 63 plain
  INSERTs in `0001_init.sql` with one `INSERT ... ON CONFLICT DO NOTHING` block (also fixes a latent
  non-idempotency bug) and regenerate it from the live DB out-of-band. Backups remain primary recovery.
  **Explicitly rejected:** API writing migration files / opening PRs per map. (Spike 006)
- **Gotchas captured in CONVENTIONS.md:** caught constraint errors abort the whole Postgres
  transaction (use a SAVEPOINT); `asyncio.run()` can't run in an `atexit` handler (clean up in
  `finally`); proxy MinIO through a `/api/banner` endpoint instead of a public bucket policy.

---

## Session 1 — Skill Score

**Date:** 2026-06-12
**Spikes processed:** 3 (001–003)
**Feature areas:** Skill input query (data layer), Scoring algorithm, Leaderboard UI
**Skill output:** `./.claude/skills/spike-findings-genjishimada/`

### Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 001 | skill-input-query | standard | VALIDATED | Skill input query (data layer) |
| 002 | scoring-farming-resistance | standard | VALIDATED | Scoring algorithm |
| 003 | leaderboard-feel | standard | VALIDATED | Leaderboard UI |

### Key Findings

- **Skill is separate from XP** and computed from verified, non-legacy, non-archived completions only.
  One AsyncPG query produces one best row per `(user, map)` carrying every candidate signal.
- **The `completion` flag means verification depth, not practice-vs-real.** `TRUE` = partial
  (screenshot-only), `FALSE` = fully-verified (video). This reshaped the whole design into a hybrid
  model and is the load-bearing schema fact — confirmed against the migration COMMENT, the repo SQL,
  and the user.
- **Signal density drives the formula.** Difficulty (100%) and time-percentile-vs-field (99.6%) are
  the dense backbone; leaderboard rank (236 runs) and medals (90 maps) are sparse bonus layers only.
  Never compare raw `time` across maps — units differ; use percentile vs the map's field.
- **Hybrid scorer survives the kill-risk.** Floor (any verified clear) + video-gated proof multipliers,
  aggregated with diminishing returns `Σ s_i / i**gamma`. Farming resistance holds at every credible
  weight; `gamma` is the anti-farm dial (gamma=0 is farmable — don't ship; default 0.68).
- **The proof layer is bimodal, not inert** — 0% median uplift (most players have no video) but up to
  +238.6% for the ~41 who video their runs, reshuffling the elite tier. That is the hybrid model
  working as intended.
- **Felt validation by a domain expert** produced the adopted default weights
  (`diff_base=1.44 gamma=0.68 time_bonus=0.55 shrink_k=10.0 wr_bonus=0.10 partial_factor=0.60`). The
  real `SkillService` keeps them config-tunable.
- **Stack proven for spiking:** stdlib + `asyncpg` only, one DB read cached to JSON and reused, scorer
  as a single shared module, standalone dependency-free bundle for tester handoff. See CONVENTIONS.md.

---

## Next

Both ideas are packaged into `spike-findings-genjishimada`, which auto-loads during the real build.
Recommended next steps:
- `/gsd:plan-phase` for **dynamic map management** (drop the Literal, add the endpoint + FK +
  idempotent seed + reconcile the 7 phantom maps), or for the `SkillService` + `/api/v3/skill/*`.
- `/gsd:spike` (frontier mode) for remaining unknowns (skill snapshot table, recompute cadence;
  multipart banner upload via Litestar `UploadFile`, the moderator `MapNameSelect` cleanup).
