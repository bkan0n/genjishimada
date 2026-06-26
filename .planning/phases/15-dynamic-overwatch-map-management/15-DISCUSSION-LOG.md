# Phase 15: Dynamic Overwatch map management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-25
**Phase:** 15-dynamic-overwatch-map-management
**Areas discussed:** Endpoint home & scope, Phase scope boundary, Banner handling, Durability & phantom maps, banner_url column consequence

---

## Pre-phase note

The phase did not exist in ROADMAP.md when `/gsd-discuss-phase` was invoked
(milestone v1.0 was marked complete; dynamic map management lived only as wrapped
spikes 004–008 on the `feat/better-ow-map-management` branch). User chose to add a
new phase first. Phase 15 was appended via `gsd-sdk query phase.add`, then the
roadmap entry was cleaned to the phase 12–14 format and the directory renamed from
the auto-generated long slug to `15-dynamic-overwatch-map-management`.

The spike findings (`spike-findings-genjishimada`) lock most of the *mechanism*, so
discussion focused only on the gray areas the spikes left open.

---

## Endpoint home & scope

| Option | Description | Selected |
|--------|-------------|----------|
| Maps domain + maps:admin | `POST /api/v3/maps` guarded by `maps:admin`; keeps map management in the maps controller | |
| Content CMS + content:admin | `POST /api/v3/content/maps` + `content:admin`, mirroring the movement-tech CMS verbatim | ✓ |
| Maps domain + content:admin | Maps namespace but reuse `content:admin` | |

**User's choice:** Content CMS + content:admin.
**Notes:** The movement-tech CMS at `/api/v3/content/` is already fully built and
uses `content:admin` — mirror it.

---

## Phase scope boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Add-only (+ all plumbing) | Create map + full Literal→str removal + endpoints + FK + seed; no edit/delete | |
| Add + replace banner | Above plus re-uploading/replacing an existing map's banner | ✓ |
| Full CRUD | Add, edit (rename/replace), and remove maps | |

**User's choice:** Add + replace banner.
**Notes:** Rename and delete deferred to a later phase.

---

## Banner handling

| Option | Description | Selected |
|--------|-------------|----------|
| Digest key + banner required | Content-addressed key like `upload_screenshot`; store URL in banner_url | |
| Encoded-name key + required | URL-encoded exact name key; banner mandatory | |
| Digest key + banner optional | Digest key, allow name-only adds | |

**User's choice (free-text):** "the file name needs to be the stripped variant
since those are dynamically created when fetching map data. there is a strip
method somewhere for this. banner should be required."
**Notes:** This **overrides Spike 007's** `banner_url`-column recommendation. The
strip method is `get_map_banner()` (`libs/sdk/.../maps.py:1013`), which derives the
banner URL from the stripped name at read time. Storing at that same stripped key
makes new banners resolve through the existing read path with zero read-site
changes. Banner required at create.

---

## banner_url column consequence (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Drop column + add collision guard | No `banner_url`; store at stripped key; reject (422) a new name whose stripped key collides with a different existing map | ✓ |
| Drop column, no guard | Same storage, accept collision risk | |
| Keep banner_url column too | Store at stripped key AND persist URL as a forward-looking escape hatch | |

**User's choice:** Drop column + add collision guard.
**Notes:** Simplest migration (FK + seed rewrite, no new column); the add-time
collision guard closes the exact lossy-key risk Spike 007 raised, within the
chosen design.

---

## Durability & phantom maps

| Option | Description | Selected |
|--------|-------------|----------|
| Reconcile + on-demand script | Add the 7 phantom maps to `maps.names`; regenerate seed via standalone script; backups primary | ✓ |
| Reconcile + wire into backup | Reconcile, and wire seed-export into the nightly backup job | |
| Drop phantoms + on-demand | Drop the 7 as stale cruft; on-demand seed script | |

**User's choice:** Reconcile + on-demand script.
**Notes:** The 7 phantom maps become usable; seed regenerated manually on demand,
not from the request path; nightly/weekly backups remain primary recovery.

---

## Claude's Discretion

- Internal service/repo layout (extend `ContentService`/`ContentRepository` vs a
  dedicated maps-content module) — match the movement-tech CMS structure.
- Banner content-type validation depth (mirror `upload_image`).
- `request_max_body_size` (default to 25 MB).
- Optional short-TTL bot cache for the full name list.

## Deferred Ideas

- Rename a map (FK `ON UPDATE CASCADE` + stripped banner key interaction).
- Delete / archive a map name (dependent `maps.mastery` / `core.maps` rows).
- Bot-side "add map" slash command (adding stays API/dashboard-only this phase).
- Wiring the seed export into the nightly backup job.
- Forward-looking `banner_url` column for arbitrary (non-strippable) keys.
