# Tournament Feature — Frontend Spec

> Audience: frontend engineer building the tournament UI against the Genji Shimada API.
> Verified against the live code (`apps/api/routes/v3/tournaments.py`,
> `libs/sdk/src/genjishimada_sdk/tournaments.py`) as of migration `0025`.

**What the web frontend is:** a **public read-only display** of tournaments + an **admin
dashboard** for staff. That is the whole surface.

**What the web frontend is NOT:** it does not submit times and it does not verify/reject
runs. Players submit their tournament times by submitting a **normal completion via the
Discord bot** (the API auto-detects the active tournament cycle by map code). Mods
verify/reject through the bot's mod-review flow. There is **no web submit UI** — do not
build one.

**Base path for everything below:** `/api/v3/tournaments`

---

## 1. Mental model — Edition vs Cycle vs Category

- **Category** — a difficulty-grouped tournament track (e.g. "Hard", "Extreme") with its
  own reward config (XP tiers, champion role). Categories no longer carry cadence — that is
  now global config (see Edition / config). Status: `is_active` toggle.
- **Cycle** — one run of a category on one selected map. Exactly **one `active` cycle per
  category at a time**. Status flow: `pending → active → finalizing → completed`. A pending
  cycle is the pre-rolled next map (admin preview only). Cycles link internally to an edition.
- **Edition** — the shared, grid-anchored **timing parent** spanning all categories. It
  carries the one shared `started_at` / `ends_at` for the whole tournament term. Status flow:
  `active → awaiting_results → completed`. The countdown the frontend renders comes from
  `edition.ends_at` directly — it is a **stored** field, not computed client-side.

```
Edition #7  status=active   started_at=2026-05-23T00:00:00Z  ends_at=2026-05-30T00:00:00Z
  ├── Category "Hard"     active cycle → map=DEF456   pending cycle → map=GHI789
  └── Category "Extreme"  active cycle → map=JKL012   pending cycle → map=MNO345
```

**Automatic transitions.** A `pg_cron` job runs every minute. At an edition boundary it:
1. finalizes the current edition's cycles,
2. sets the edition to `awaiting_results` (final standings may be deferred until in-flight
   verifications drain),
3. starts the **next** edition at the **exact** grid boundary — `started_at` of the new
   edition = `ends_at` of the previous one, never `now()` (this is the drift fix),
4. pre-rolls the next `pending` cycle per category.

The frontend learns about transitions by **re-polling** (see §6). There is no API call that
triggers a transition.

- **`awaiting_results`** — the edition's term ended but final standings are deferred pending
  the drain of in-flight verifications. Results publish automatically once verifications
  settle, or can be force-published via `PATCH /publish-results`.

---

## 2. Auth & scopes

All endpoints require an authenticated request via the `X-API-KEY` header (same as the rest
of the v3 API).

| Scope | Use |
|-------|-----|
| `tournaments:read` | All `GET` endpoints (public display) |
| `tournaments:write` | Admin dashboard mutations (category CRUD, config, map select/reroll, pause, bootstrap, publish-results) |
| `tournaments:verify` | Bot verify/reject only — **not** the web dashboard |

Superusers bypass scope checks. A missing/insufficient scope returns `401`.

---

## 3. Data models

All times are **floats in seconds**. All timestamps are ISO-8601 datetimes. `null` is
possible wherever noted. These are the fields that exist now — do not assume others.

### Config — `TournamentConfigResponse`
Global config singleton (cadence is global, never per-category).
```jsonc
{
  "blacklist_weeks": 4,            // weeks a map is excluded after use
  "cadence": "weekly",            // "weekly" | "biweekly" (GLOBAL)
  "anchor_weekday": 1,            // grid anchor weekday, 0=Sun..6=Sat
  "anchor_time": "12:00:00",      // wall-clock time-of-day in anchor_tz
  "anchor_tz": "America/New_York", // IANA timezone name
  "transitions_paused": false,    // global hiatus lever
  "debug_cycle_seconds": null,    // int | null — debug/test edition-length override
  "created_at": "2026-05-01T00:00:00Z",
  "updated_at": "2026-05-01T00:00:00Z"
}
```

### Category — `TournamentCategoryResponse`
No `cycle_frequency` — cadence is global config.
```jsonc
{
  "id": 1,
  "name": "Hard",
  "difficulties": ["Hard", "Very Hard"],   // top-level DifficultyTop tiers (see §7)
  "participation_xp": 50,                  // flat XP for first submission in a cycle
  "placement_xp": [{"place": 1, "xp": 200}, {"place": 2, "xp": 100}],
  "streak_xp": [{"threshold": 5, "xp": 300}],
  "champion_role_id": 123456789012345678,  // Discord role id, or null
  "is_active": true,
  "created_at": "2026-05-01T00:00:00Z",
  "updated_at": "2026-05-01T00:00:00Z"
}
```

### Edition — `TournamentEditionResponse`
The shared timing parent. `ends_at` is **stored**, read it directly.
```jsonc
{
  "id": 7,
  "started_at": "2026-05-23T00:00:00Z",  // exact grid value (anchor + N×period), never now()
  "ends_at": "2026-05-30T00:00:00Z",     // STORED, not derived — use for the countdown
  "status": "active",                     // active|awaiting_results|completed
  "created_at": "2026-05-16T00:00:00Z"
}
```

### Cycle (list/archive) — `TournamentCycleWithWinnerResponse`
```jsonc
{
  "id": 13,
  "category_id": 1,
  "map_id": 456,
  "map_code": "DEF456",
  "map_name": "Parkour Paradise",
  "map_difficulty": "Hard",                // string label
  "status": "active",                      // pending|active|finalizing|completed
  "started_at": "2026-05-23T00:00:00Z",    // null while pending
  "ended_at": null,                        // set when completed
  "created_at": "2026-05-16T00:00:00Z",
  "winner_name": null,                     // rank-1 display name, null if no subs
  "winner_user_id": null
}
```

### Cycle list wrapper — `TournamentCycleListResponse`
```jsonc
{ "total": 42, "cycles": [ /* TournamentCycleWithWinnerResponse[] */ ] }
```

### Next-cycle preview — `TournamentNextCycleResponse`
```jsonc
{
  "id": 14, "category_id": 1, "map_id": 789,
  "map_code": "GHI789", "map_name": "Sky Temple", "map_difficulty": "Very Hard",
  "status": "pending", "created_at": "2026-05-16T00:00:00Z"
}
```

### Leaderboard entry — `TournamentLeaderboardEntryResponse`
```jsonc
{
  "rank": 1,
  "user_id": 140728390589939712,
  "name": "PlayerX",
  "time": 42.51,        // seconds
  "verified": true,     // verified always outranks unverified (see §7)
  "completion": true    // counts as a full completion (quest/badge eligibility)
}
```

### Streak — `TournamentStreakResponse`
```jsonc
{
  "user_id": 140728390589939712,
  "current_streak": 3,
  "max_streak": 7,
  "last_cycle_id": 13,     // int | null
  "updated_at": "2026-05-24T12:00:00Z"
}
```

### Lifecycle — `TournamentLifecycleResponse`
Returned by `PATCH /pause` and `PATCH /debug-cycle-length`.
```jsonc
{ "transitions_paused": false, "debug_cycle_seconds": null }
```

### Request bodies (admin dashboard)

- **`TournamentCategoryCreateRequest`** — `name` and `difficulties` required;
  `participation_xp=0`, `placement_xp=[]`, `streak_xp=[]`, `champion_role_id=null` default.
  No `cycle_frequency`.
- **`TournamentCategoryPatchRequest`** — all optional: `name`, `difficulties`,
  `participation_xp`, `placement_xp`, `streak_xp`, `champion_role_id`, `is_active`.
- **`TournamentConfigPatchRequest`** — all optional: `blacklist_weeks`, `cadence`,
  `anchor_weekday`, `anchor_time`, `anchor_tz`.
- **`TournamentChooseMapRequest`** — `{ "map_code": "ABC123" }`.
- **`TournamentPauseRequest`** — `{ "paused": true }`.
- **`TournamentDebugCycleLengthRequest`** — `{ "seconds": 60 }` (or `null` to clear).

---

## 4. Endpoints

### Public read — scope `tournaments:read`

| Method | Path | Returns | Notes |
|--------|------|---------|-------|
| `GET` | `/config` | `TournamentConfigResponse` | Global config incl. cadence + anchor. |
| `GET` | `/categories` | `TournamentCategoryResponse[]` | Build the category selector from this. |
| `GET` | `/categories/{id}` | `TournamentCategoryResponse` | `404` if not found. |
| `GET` | `/streaks/{user_id}` | `TournamentStreakResponse` | `404` = no streak yet (treat as 0). |
| `GET` | `/cycles` | `TournamentCycleListResponse` | Main list/archive endpoint. Query params below. |
| `GET` | `/cycles/{cycle_id}/leaderboard` | `TournamentLeaderboardEntryResponse[]` | Unpaginated, already ranked. |
| `GET` | `/categories/{id}/next-cycle` | `TournamentNextCycleResponse` | `404` if category or pending cycle missing. |
| `GET` | `/editions/active` | `TournamentEditionResponse` | The shared timing window. `404` if none active. |

**`GET /cycles` query params:**
- `status` — `pending` | `active` | `finalizing` | `completed` (optional)
- `category_id` — int (optional)
- `limit` — 1–100, default `20`
- `offset` — default `0`

> **Getting the current active cycle for a category** (common): there is no dedicated
> endpoint. Call `GET /cycles?status=active&category_id={id}` and take `cycles[0]`
> (0 or 1 result). The `cycle_id` is what you pass to `/leaderboard`.

### Admin dashboard write — scope `tournaments:write`

| Method | Path | Body | Returns | Errors |
|--------|------|------|---------|--------|
| `POST` | `/categories` | `TournamentCategoryCreateRequest` | `TournamentCategoryResponse` (201) | `409` name exists |
| `PATCH` | `/categories/{id}` | `TournamentCategoryPatchRequest` | `TournamentCategoryResponse` (200) | `404` · `409` locked or name conflict |
| `DELETE` | `/categories/{id}` | — | `204` | `404` · `409` locked |
| `PATCH` | `/config` | `TournamentConfigPatchRequest` | `TournamentConfigResponse` (200) | `422` invalid `anchor_tz` |
| `POST` | `/categories/{id}/select-map` | — | `TournamentNextCycleResponse` (201) | `404` · `409` pending exists · `422` no eligible maps |
| `POST` | `/categories/{id}/reroll` | — | `TournamentNextCycleResponse` (201) | `404` · `422` no eligible maps |
| `POST` | `/categories/{id}/reroll-active` | — | `TournamentNextCycleResponse` (201) | `404` category/active not found · `422` no eligible maps |
| `PATCH` | `/categories/{id}/next-cycle` | `TournamentChooseMapRequest` | `TournamentNextCycleResponse` (200) | `404` · `422` map not eligible |
| `POST` | `/bootstrap` | — | `TournamentEditionResponse` (201) | `409` active edition exists · `422` a category has no eligible maps |
| `PATCH` | `/publish-results` | — | `204` | `409` if no edition `awaiting_results` |
| `PATCH` | `/pause` | `TournamentPauseRequest` | `TournamentLifecycleResponse` (200) | — |
| `PATCH` | `/debug-cycle-length` | `TournamentDebugCycleLengthRequest` | `TournamentLifecycleResponse` (200) | `403` in production |

Notes on the admin mutations:
- **`reroll`** discards the pending cycle and re-randomizes the next map.
- **`reroll-active`** rerolls the **live** active cycle's map — it **wipes that cycle's
  submissions** and **preserves the edition window** (the deadline does not move).
- **`next-cycle` (PATCH)** explicitly chooses the pending map by `map_code`.
- **`bootstrap`** manually activates the **first** grid-snapped edition (one edition + one
  child cycle per active category). Thereafter rollover is automatic.
- **`publish-results`** force-publishes results, ignoring in-flight verifications.
- **`pause`** is a **global** hiatus: the active edition still finishes its term, only the
  **next** edition is suppressed.
- **`debug-cycle-length`** is DEBUG/TEST ONLY (returns `403` in production); pass
  `seconds: null` to clear the override.

> "Locked" (`409`) on category edit/delete means the category currently has an `active` or
> `finalizing` cycle. Surface this as "can't edit while a tournament is running."

### Discord-bot only — NOT the web dashboard — scope `tournaments:verify`

| Method | Path | Returns | Errors |
|--------|------|---------|--------|
| `PATCH` | `/completions/{tournament_completion_id}/verify` | `JobStatusResponse` | `404` |
| `PATCH` | `/completions/{tournament_completion_id}/reject` | `JobStatusResponse` | `404` · `409` already verified (verified is terminal) |

These exist for the bot's mod-review flow. The web dashboard does not call them.

**There is no `POST /cycles/{cycle_id}/submit`.** Tournament completions are created
server-side when a user submits a **normal completion** via `POST /api/v3/completions/` —
the API auto-detects an active tournament cycle by map code. That path is **async/job-based**
(it returns a `CompletionSubmissionJobResponse` with `job_status` and `completion_id`), not a
synchronous `201`. The web frontend does not submit tournament times.

---

## 5. Frontend flows

### A. View the active tournament + countdown
1. `GET /editions/active` → the shared window (`started_at`, `ends_at`, `status`).
2. For each category: `GET /cycles?status=active&category_id={id}` → take `cycles[0]` for the
   current map (`map_name`, `map_code`, `map_difficulty`).
3. Countdown = `edition.ends_at − now()`, read straight from the **stored** `ends_at`. Do
   **not** derive it from `started_at` + cadence.

### B. Leaderboard
- `GET /cycles/{cycle_id}/leaderboard` → already ranked; render as-is.

### C. Archive / past champions
- `GET /cycles?status=completed` (optionally `&category_id={id}`). Each row carries
  `winner_name` / `winner_user_id` and `ended_at` — enough for a "Past Champions" list. Use
  `total` for pagination.

### D. Streaks
- `GET /streaks/{user_id}` → `current_streak` / `max_streak`. Treat `404` as "no streak yet"
  (show 0), not an error.

### E. Admin dashboard
- Category CRUD (`POST` / `PATCH` / `DELETE /categories`).
- Config (`PATCH /config`: cadence + anchor).
- Map management: preview (`GET .../next-cycle`), random select (`POST .../select-map`),
  reroll pending (`POST .../reroll`), reroll live (`POST .../reroll-active`), explicit choose
  (`PATCH .../next-cycle`).
- Lifecycle: pause/resume (`PATCH /pause`), bootstrap first edition (`POST /bootstrap`),
  force-publish (`PATCH /publish-results`).

---

## 6. Polling & async behavior

- **All admin writes are synchronous** and return the final result — **except** verify/reject
  and tournament-completion submission, which are **async/job-based** (and both happen via the
  bot, not the web frontend).
- **Edition/cycle transitions are automatic and server-driven** (a `pg_cron` job runs every
  minute). There is no event the browser receives.
  - To detect a transition, **re-poll** `GET /editions/active` and/or
    `GET /cycles?status=active&category_id={id}`. A changed edition `id`/`ends_at` or cycle
    `id`/`started_at` means a transition happened. Suggested cadence: every 30–60s on an open
    tournament page, plus on user focus.
  - Render the countdown from the **stored** `edition.ends_at`.
- Discord announcements and XP grants happen via the bot/queue after a transition; they do not
  change any API response and need no frontend handling.

---

## 7. Reference values

**Cycle status** (`status`): `pending`, `active`, `finalizing`, `completed`.
- `pending` — pre-rolled next map, admin preview only.
- `active` — the live cycle for the current edition term.
- `finalizing` — brief transient state during finalization.
- `completed` — done; results frozen; appears in archive.

**Edition status** (`status`): `active`, `awaiting_results`, `completed`.

**Cadence** (`config.cadence`, GLOBAL): `weekly` or `biweekly`.

**Difficulty tiers** (`difficulties` on a category — `DifficultyTop`, top-level only):
`Easy`, `Medium`, `Hard`, `Very Hard`, `Extreme`, `Hell`.
(Maps internally have +/- sub-tiers, but categories group by these top-level tiers. Note
`map_difficulty` on cycle responses is a free-form string label, not the typed enum.)

**Leaderboard ranking rule:** verified `DESC`, then time `ASC` — a verified run always
outranks an unverified one; within a tier the fastest wins. `rank` is precomputed; render
as-is.

**`verified` vs `completion`:** `verified` means the run passed verification and so affects
its **ranking tier** (verified always outranks unverified). `completion` means the submission
counts as a **full completion** for quest/badge eligibility — a distinct flag from `verified`.

**Champion:** the `winner_user_id` of a `completed` cycle (rank 1 at finalization). The
Discord role transfer is handled bot-side; `category.champion_role_id` names the role
representing that title (may be `null`).
