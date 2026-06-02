# Tournament Feature — Frontend Spec

> Audience: frontend engineer building the tournament UI against the Genji Shimada API.
> Everything here is verified against the live code (`apps/api/routes/v3/tournaments.py`,
> `libs/sdk/src/genjishimada_sdk/tournaments.py`, migrations `0020`–`0022`).

---

## 1. Mental Model (read this first)

- A **Category** is a difficulty-grouped tournament track (e.g. "Hard", "Extreme"). Each category
  has its own cadence (`weekly` or `biweekly`) and its own reward config.
- A **Cycle** is one run of a category on one randomly-selected map. Exactly **one cycle is `active`
  per category at a time**. When it ends, it finalizes and the next pre-rolled cycle takes over
  automatically.
- Players submit their **best completion time** to the active cycle. The **leaderboard** ranks
  verified-then-fastest. Rank 1 at finalization becomes the **Champion** (gets a Discord role).
- Cycle status flows: `pending → active → finalizing → completed`.
- Transitions are **automatic** (a DB cron job), not triggered by any API call. The frontend learns
  about a transition by re-polling (see §6).

```
Category "Hard" (weekly)
  ├── Cycle #12  status=completed   map=ABC123   winner=PlayerX
  ├── Cycle #13  status=active      map=DEF456   ← players submit here
  └── Cycle #14  status=pending     map=GHI789   ← pre-rolled, admin preview only
```

---

## 2. Auth & Scopes

All endpoints require an authenticated request (`X-API-KEY` header, same as the rest of the v3 API).
Each endpoint requires one of two scopes:

| Scope | Use |
|-------|-----|
| `tournaments:read` | All `GET` endpoints (player-facing views) |
| `tournaments:write` | Submitting completions + all admin/config/cycle mutations |

Superusers bypass scope checks. A missing/insufficient scope returns `401`.

**Base path for everything below:** `/api/v3/tournaments`

---

## 3. Data Models (what you render)

All times are **floats in seconds**. All timestamps are ISO-8601 datetimes. `null` is possible
wherever noted.

### Category — `TournamentCategoryResponse`
```jsonc
{
  "id": 1,
  "name": "Hard",
  "difficulties": ["Hard", "Very Hard"],   // top-level tiers only (see §7)
  "cycle_frequency": "weekly",             // "weekly" | "biweekly"
  "participation_xp": 50,                  // flat XP for first submission in a cycle
  "placement_xp": [{"place": 1, "xp": 200}, {"place": 2, "xp": 100}],
  "streak_xp": [{"threshold": 5, "xp": 300}],
  "champion_role_id": 123456789012345678,  // Discord role id, or null
  "is_active": true,
  "created_at": "2026-05-01T00:00:00Z",
  "updated_at": "2026-05-01T00:00:00Z"
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
  "verified": true,     // verified always outranks unverified
  "completion": true
}
```

### Completion (returned on submit) — `TournamentCompletionResponse`
```jsonc
{
  "id": 999, "cycle_id": 13, "user_id": 140728390589939712, "map_id": 456,
  "time": 42.51, "screenshot": "https://cdn.genji.pk/...", "video": null,
  "verified": false, "completion": false, "inserted_at": "2026-05-24T12:00:00Z"
}
```

### Streak — `TournamentStreakResponse`
```jsonc
{ "user_id": 140728390589939712, "current_streak": 3, "max_streak": 7,
  "last_cycle_id": 13, "updated_at": "2026-05-24T12:00:00Z" }
```

### Config — `TournamentConfigResponse`
```jsonc
{ "blacklist_weeks": 4, "created_at": "...", "updated_at": "..." }
```

---

## 4. Endpoints

### Player-facing (read)

| Method | Path | Returns | Notes |
|--------|------|---------|-------|
| `GET` | `/categories` | `TournamentCategoryResponse[]` | All categories. Build the tournament selector from this. |
| `GET` | `/categories/{category_id}` | `TournamentCategoryResponse` | `404` if not found. |
| `GET` | `/cycles` | `TournamentCycleListResponse` | **The main list/archive endpoint.** Query params below. |
| `GET` | `/cycles/{cycle_id}/leaderboard` | `TournamentLeaderboardEntryResponse[]` | Full list, **not paginated**. Already ranked. |
| `GET` | `/streaks/{user_id}` | `TournamentStreakResponse` | `404` if the user has no streak record yet. |
| `GET` | `/config` | `TournamentConfigResponse` | Global config (map cooldown weeks). |

**`GET /cycles` query params:**
- `status` — `pending` | `active` | `finalizing` | `completed` (optional)
- `category_id` — int (optional)
- `limit` — 1–100, default `20`
- `offset` — default `0`

> **Getting the current active cycle for a category** (very common): there is no dedicated
> endpoint. Call `GET /cycles?status=active&category_id={id}` and take `cycles[0]`
> (0 or 1 result). The `cycle_id` you get is what you pass to `/leaderboard` and `/submit`.

### Player-facing (write)

| Method | Path | Body | Returns | Errors |
|--------|------|------|---------|--------|
| `POST` | `/cycles/{cycle_id}/submit` | `TournamentCompletionCreateRequest` | `TournamentCompletionResponse` (201) | `404` cycle not found · `409` cycle not active · `409` time not faster than your best |

**Submit body — `TournamentCompletionCreateRequest`:**
```jsonc
{ "user_id": 140728390589939712, "time": 42.51,
  "screenshot": "https://...", "video": "https://..." /* optional, nullable */ }
```

### Admin-facing (write) — for the staff/config UI

| Method | Path | Body | Returns | Errors |
|--------|------|------|---------|--------|
| `POST` | `/categories` | `TournamentCategoryCreateRequest` | `TournamentCategoryResponse` (201) | `409` name exists |
| `PATCH` | `/categories/{id}` | `TournamentCategoryPatchRequest` | `TournamentCategoryResponse` | `404` · `409` locked or name conflict |
| `DELETE` | `/categories/{id}` | — | `204` | `404` · `409` locked |
| `GET` | `/categories/{id}/next-cycle` | — | `TournamentNextCycleResponse` | `404` category or pending cycle |
| `POST` | `/categories/{id}/select-map` | — | `TournamentNextCycleResponse` (201) | `404` · `409` pending exists · `422` no eligible maps |
| `POST` | `/categories/{id}/reroll` | — | `TournamentNextCycleResponse` (201) | `404` · `422` no eligible maps |
| `PATCH` | `/categories/{id}/next-cycle` | `TournamentChooseMapRequest` `{ "map_code": "ABC123" }` | `TournamentNextCycleResponse` | `404` · `422` map not eligible |
| `GET` | `/config` / `PATCH` `/config` | `TournamentConfigPatchRequest` `{ "blacklist_weeks": 4 }` | `TournamentConfigResponse` | — |

> "Locked" (`409`) on category edit/delete means the category currently has an `active` or
> `finalizing` cycle. Surface this as "can't edit while a tournament is running."

`TournamentCategoryCreateRequest` defaults: `cycle_frequency="weekly"`, `participation_xp=0`,
`placement_xp=[]`, `streak_xp=[]`, `champion_role_id=null`. `TournamentCategoryPatchRequest` is
fully partial — omit a field to leave it unchanged.

---

## 5. Core User Flows

### A. View an active tournament
1. `GET /categories` → user picks a category.
2. `GET /cycles?status=active&category_id={id}` → `cycles[0]` is the active cycle.
3. Render map (`map_name`, `map_code`, `map_difficulty`) and the **time remaining** (see §6 — you
   compute this).
4. `GET /cycles/{cycle_id}/leaderboard` → render standings.

### B. Submit a time
1. `POST /cycles/{cycle_id}/submit` with `{user_id, time, screenshot, video?}`.
2. **Synchronous** — you get the completion back immediately (201). No job polling.
3. Handle `409`:
   - "cycle not active" → the cycle ended; refresh the active cycle.
   - "time not faster" → only a personal best is accepted; show "not faster than your best time."
4. Optimistically update the leaderboard, or re-fetch it.

### C. Browse the archive / past winners
- `GET /cycles?status=completed&category_id={id}&limit=20&offset=0`.
- Each row carries `winner_name` / `winner_user_id` and `ended_at` — enough for a "Past Champions"
  list without a second request. Use `total` for pagination.

### D. Champion display
- The **champion is `winner_user_id` of a `completed` cycle** (rank 1 at finalization).
- The Discord role transfer is handled by the bot automatically — the frontend just displays the
  winner. `category.champion_role_id` tells you which Discord role represents that title (may be
  `null`).

### E. Player streak
- `GET /streaks/{user_id}` → `current_streak` / `max_streak`. Treat `404` as "no streak yet"
  (show 0), don't surface it as an error.

### F. Admin: pick / preview / reroll the next map
- `GET /categories/{id}/next-cycle` to preview the pre-rolled map.
- `POST .../select-map` (random), `POST .../reroll` (discard + re-random), or
  `PATCH .../next-cycle` with a specific `map_code`.
- All return the resulting `TournamentNextCycleResponse` synchronously.

---

## 6. Async Behavior & Polling (important)

- **All write endpoints are synchronous.** There is **no job-id / `/jobs/{id}` polling** anywhere in
  the tournament feature. You always get the final result in the response.
- **Cycle transitions are automatic and server-driven.** A Postgres cron job runs roughly every
  minute, finalizes a cycle when its duration elapses, promotes the next pending cycle, and pre-rolls
  another. There is no event the browser receives directly.
  - To detect a transition, **re-poll** `GET /cycles?status=active&category_id={id}`. A changed
    `id`/`started_at` means a new cycle started. Suggested cadence: every 30–60s on an open
    tournament page, plus on user focus.
  - After submitting, re-fetch the leaderboard rather than assuming.
- **Downstream effects you don't see directly:** Discord announcements and XP grants happen via the
  bot/queue after a transition. They don't block or change any API response you get; ignore them on
  the frontend except that a user's XP/lootbox will update on its next independent fetch.

---

## 7. Reference Values

**Cycle status** (`status` field): `pending`, `active`, `finalizing`, `completed`.
- `pending` — pre-rolled, no submissions, admin preview only.
- `active` — open for submissions.
- `finalizing` — brief transient state during finalization; submissions rejected.
- `completed` — done; results frozen; appears in archive.

**Cycle frequency** (`cycle_frequency`): `weekly` (7 days) or `biweekly` (14 days).

**Time-remaining computation** (the API does not send an `ends_at` on cycle responses):
```
ends_at = started_at + (7 days if cycle_frequency == "weekly" else 14 days)
```
You need the category's `cycle_frequency` (from `GET /categories/{id}`) plus the cycle's
`started_at`. ⚠️ If you'd prefer the server to send `ends_at` directly, flag it — see §8.

**Difficulty tiers** (`difficulties` on a category, top-level only):
`Easy`, `Medium`, `Hard`, `Very Hard`, `Extreme`, `Hell`.
(Note: maps internally have +/- sub-tiers, but categories group by these 6 top-level tiers.)

**Leaderboard ranking rule:** `verified DESC, time ASC` — verified submissions always rank above
unverified; within a tier, fastest wins. `rank` is precomputed; render as-is.

---

## 8. Gaps / things to confirm with backend

These are real ergonomic gaps you'll hit — worth raising before building around them:

1. **No `ends_at` / time-remaining field** on cycle responses. You must derive it client-side from
   `started_at` + category `cycle_frequency`. Consider requesting the server add `ends_at`.
2. **No single "active cycle for category" endpoint.** You use `GET /cycles?status=active&...` and
   read element 0. Works, but slightly awkward.
3. **Leaderboard is unpaginated** — returns the full ranked list. Fine for typical sizes; be aware
   for very large cycles.
4. **`map_difficulty` is a free-form string** on cycle/next-cycle responses (not the typed tier
   enum). Don't assume it's one of the 6 top-level labels.
5. **Submit requires `user_id` in the body** (not inferred from the auth token). Make sure you pass
   the correct player id.
```
