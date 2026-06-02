# Phase 11: Tournament Verification Flow - Research

**Researched:** 2026-05-31
**Domain:** Litestar API + discord.py bot + msgspec SDK, raw asyncpg, RabbitMQ (Genji tournament integration)
**Confidence:** HIGH (all major claims verified to file:line from live source this session)

> Methodology note: file content extracted via `Read`/`grep`/`sed`/`python3`, verified line-by-line. A handful of source files contain duplicated symbol references across CONTEXT vs live code (e.g. CONTEXT cites `submit_completion` at `:497`, also seen near other lines) — Python keeps the LAST definition. **Re-confirm exact line numbers immediately before editing; they drift.**

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D1 — Auto-detect on normal submit:** A normal completion whose map is the active cycle's map is automatically considered for that tournament. No separate player-facing tournament-submit step. Detection keys off the active cycle's `map_id` (a cycle pins a specific map).
- **D2 — Eligibility:** Anyone who completes the active tournament map participates — no opt-in. The first *counted* (verified) run auto-enrolls the player (grants participation XP). Apply eligibility gates the tournament system already enforces (blacklist/active-cycle) — planner to confirm which.
- **D3 — Keep fastest tournament-window time (independent ranking):** The tournament board keeps each player's fastest tournament-window time on `tournaments.completions`, independent of core's "latest = fastest". A run slower than all-time PB still counts (kept only if it beats their current tournament best). **No slower-than-PB row is ever inserted into `core.completions`.** Cross-write to `core.completions` happens **only when the run is a PB**.
- **D4 — Verification split:** PB run rides the existing core OCR/mod verification; on `VerificationChangedEvent(verified=true)` the linked tournament record is marked verified (no second embed). Non-PB run (no core row) gets its OWN verification — OCR auto-verify for no-video, mod Accept/Reject embed for video — operating on `tournaments.completions`, reusing the OCR service + embed pattern. A single screenshot is never reviewed twice.
- **D5 — Remove the bypass:** Delete `POST /api/v3/tournaments/cycles/{cycle_id}/submit` and its verification-skipping cross-write. Fix all dependents (tests, callers). No code path may write a tournament completion without verification.
- **D6 — Rewards / standing on verification:** Participation XP and a *verified* leaderboard standing are granted on verification, not on submission. Unverified runs appear as pending (ranked below verified).

### Claude's Discretion (defer to research/planning)
- Exact new RabbitMQ event/queue names + SDK structs for the non-PB tournament verification path; the tournament verify endpoint; the bot handler wiring.
- Whether the non-PB OCR path reuses the in-process `completion.ocr.requested` event or a tournament variant.
- How the active-cycle-by-`map_id` lookup is implemented (new repo method vs. existing).
- Where/how the cross-write becomes `verified=TRUE` once a PB run is verified (today it writes `verified=FALSE`).
- Mod verification channel reuse vs. a dedicated tournament verification channel (default: reuse).

### Deferred Ideas (OUT OF SCOPE)
- Changing how cycles are selected/transitioned (Phases 5/7).
- Changing the leaderboard *ranking* formula (tier-then-time, Phase 6).
- Bot writing to Postgres (architecturally forbidden — bot calls the API).
- Recomputing historical tournament standings on map change (future phase).
</user_constraints>

---

<phase_requirements>
## Phase Requirements (Success Criteria from ROADMAP)

| ID | Description | Research Support |
|----|-------------|------------------|
| SC-1 | Normal verified completion on active-cycle map appears on leaderboard, no separate submit | §D1/D2 hook in completion submit path + new `get_active_cycle_by_map_id` |
| SC-2 | Non-PB run still verified (OCR or mod) and recorded as fastest tournament-window time | §D4b tournament-native verification surface |
| SC-3 | PB+tournament run verified exactly once; marks BOTH core and tournament verified | §D4a — set tournament verified inside `verify_completion`; link via `tournament_completion_id` FK |
| SC-4 | Bypass `POST .../submit` gone; no unverified tournament write | §D5 deletion inventory |
| SC-5 | Participation XP + verified standing only on verification | §D6 move `award_participation` to verify paths |
| SC-6 | `core.completions` "latest=fastest" preserved; no slower-than-PB core rows | §D3 — guaranteed by 0017 speed trigger; PB-gated cross-write only |
</phase_requirements>

---

## Summary

Phase 11 reroutes tournament times through verification. The audit confirms a clean integration story and **corrects several assumptions** a quick reading of CONTEXT might invite:

1. **The tournament completion/verification RabbitMQ queues do NOT exist yet.** The only tournament queues in `infra/rabbitmq/definitions.json` are `api.tournament.cycle_started` and `api.tournament.cycle_completed` (+ DLQs). Tournament XP rides the **generic** `api.xp.grant` queue (VERIFIED). There is **no** `api.tournament.completion.*` or `api.tournament.verification.*` queue. The non-PB mod-review path (D4b) needs **brand-new** queue(s) + SDK event struct(s) + bot consumer(s) — the bulk of the new work.

2. **Keep-fastest (D3) is enforced at the SERVICE layer, not in SQL.** `create_tournament_completion` (`tournaments_repository.py:885-928`) is a plain `INSERT ... RETURNING *` — **no `ON CONFLICT`**. Today's keep-fastest gate is the precheck in `TournamentService.submit_completion`: `fetch_user_completion` (`repo:1055`) → if `data.time >= existing["time"]` raise `SlowerTimeError` (`service:536-537`). **Critical schema fact:** the table's UNIQUE constraint is `UNIQUE (cycle_id, user_id, inserted_at)` — NOT `(cycle_id, user_id)`. So multiple rows per (cycle,user) are physically allowed (each insert gets a fresh `inserted_at`); "best per user" is computed at read time by `fetch_leaderboard`/`fetch_user_completion` via `ORDER BY verified DESC, time ASC LIMIT 1`. This means a naive `ON CONFLICT (cycle_id,user_id)` upsert is NOT possible without a schema change. (See D3 recommendation.)

3. **`tournaments.completions` columns (VERIFIED, migration 0020 lines 86-99):** `id, cycle_id, user_id, map_id, time numeric(10,2), screenshot text NOT NULL, video text NULL, verified bool DEFAULT FALSE, completion bool DEFAULT FALSE, inserted_at timestamptz, UNIQUE(cycle_id,user_id,inserted_at)`. There is **no `verified_by`/`verified_at`** column. There IS a `completion` flag and a `map_id` column.

4. **`core.completions.tournament_completion_id` FK exists** (migration 0020:170-172, `REFERENCES tournaments.completions(id) ON DELETE SET NULL`) — confirms the PB-path link mechanism for D4a.

5. **XP ledger is migration 0022** (`tournaments.xp_grants`), `claim_xp_grant` (`repo:837`) does `INSERT ... ON CONFLICT (cycle_id, user_id, reason) DO NOTHING RETURNING id` (VERIFIED) — calling `award_participation` from verification is idempotent and safe.

6. **OCR is reusable for tournaments.** `attempt_auto_verify_async` (`completions_service.py:281`) receives the screenshot URL via the event (it does NOT fetch from the DB), posts to the OCR HTTP service, and on match calls `verify_completion_with_pool(completion_id)` against **core** completions. So the OCR *check* is reusable for non-PB tournament runs by passing the tournament row's screenshot; only the verify target + idempotency key differ.

The genuinely new constructs: (a) `get_active_cycle_by_map_id` repo lookup; (b) DI wiring so the completion submit path can reach tournament logic; (c) a PB-path side-effect inside `verify_completion`; (d) a non-PB tournament verification surface (OCR variant + new queue/struct/bot Accept-Reject view + new verify API endpoint); (e) deletion of the bypass; (f) moving participation XP to verification.

**Primary recommendation:** Reuse the existing keep-fastest read-time semantics, the XP ledger, the PB-gated `cross_write_to_core` CTE, and the completions Accept/Reject + OCR patterns. Add one repo lookup, wire tournament logic into the completion submit path, branch PB vs non-PB at the insert site, build the non-PB verification surface as a tournament-native mirror of completions, and move `award_participation` to fire from both verify paths.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Auto-detect active-cycle map on submit | API service (`CompletionsService`) | API repo (`TournamentRepository`) | Business logic at the single-writer; needs a DB lookup |
| Keep-fastest tournament time | API service (read-time best-per-user) | API repo (insert + read) | Multiple rows allowed (`UNIQUE(...,inserted_at)`); best computed at read time |
| PB-path verification propagation | API service (`verify_completion`) | API repo | Runs in same txn as core verify; sets linked tournament row verified |
| Non-PB OCR auto-verify | API service (OCR variant) + in-process event | OCR HTTP service | No core row; tournament-native trigger + screenshot source required |
| Non-PB mod Accept/Reject | Bot extension (embed + view) | new API verify endpoint | Bot owns Discord UI; bot never writes DB → calls API |
| Set `tournaments.completions.verified=TRUE` | API endpoint + service + repo | — | Single-writer rule: only API writes Postgres |
| Participation XP on verification | API service (`TournamentRewardService.award_participation`) | XP ledger (0022) | Idempotent claim; must move off submission |

---

## Standard Stack

No new libraries (CLAUDE.md: "no new frameworks"). Pure integration:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Litestar | >=2.16.0 | Routes, DI, in-process `app.emit` event bus | Existing API framework |
| asyncpg (litestar-asyncpg) | >=0.4.0 | Raw SQL, pooled connections | No ORM (architectural constraint) |
| msgspec | >=0.19.0 | SDK request/response/event structs | Shared serialization both sides |
| aio-pika | >=9.5.5 | RabbitMQ publish/consume | Existing queue transport |
| discord.py | master (git) | Bot embeds, `discord.ui` views/buttons | Existing bot framework |

**No package install step → no Package Legitimacy Audit required (zero external packages added).**

---

## Patterns Found

### Completion submit + verification pipeline (the template to mirror)
- `completions_service.py:413` `submit_completion(data, request, notifications, users)`; map existence check `:433-435`.
- `:437` `async with self._pool.acquire() as conn, conn.transaction():`; pending-verification handling `:438-446` (slower-than-pending → `SlowerThanPendingError` raised explicitly at `:443`, BEFORE insert).
- `:448-462` `insert_completion(code, user_id, time, screenshot, video, conn)` (`completions_repository.py:1512`). **The DB speed trigger (0017) fires here for non-PB inserts.**
- `:476` `get_suspicious_flags`; `:478-492` **no video + not suspicious → in-process OCR**: `request.app.emit("completion.ocr.requested", OcrVerificationRequestedEvent(completion_id, user_id, code, time, screenshot), svc=self, users=users, notifications=notifications)` → returns early.
- `:494-501` **else (video or suspicious) → mod review**: publish `CompletionCreatedEvent(completion_id)` on `api.completion.submission`.
- `completions_service.py:575` `verify_completion(request, record_id, data, *, conn, notifications)` → `check_completion_exists` (`:600`), `fetch_completion_for_moderation` (`:604`, returns `user_id/code/old_time/old_verified`), `update_verification` (`:612`), quest progress (`:624-637`), publish `VerificationChangedEvent(completion_id, verified, verified_by, reason)` on **`api.completion.verification`** (`:639-651`). **The event carries NO map_id** (only completion_id/verified/verified_by/reason). `verify_completion_with_pool` (`:654`) wraps it with a pooled conn.
- OCR: `attempt_auto_verify_async(completion_id, user_id, code, time, screenshot, users, notifications)` (`:281`). Screenshot URL is passed IN (`:317`); posts to `http://genjishimada-ocr[-dev]:8000/extract` (`:308-321`); matches code/time/name (`:330-332`); on match → `verify_completion_with_pool(None, completion_id, ...)` (`:340`); on mismatch → publish `FailedAutoverifyEvent` + `CompletionCreatedEvent` (mod review) (`:345-366`).
- In-process listener: `apps/api/events/completions.py:17` `@listener("completion.ocr.requested")` `handle_ocr_verification(event, svc, users, notifications)` → calls `svc.attempt_auto_verify_async(...)` (VERIFIED full file).

### Bot Accept/Reject pattern (template for D4b video runs)
- `completions.py:103-153` `CompletionsVerificationAcceptButton` — green, `custom_id="completions..."` (`:108`); callback → `self.view.bot.api.verify_completion(...)` (`:122`).
- `completions.py:155-187` `CompletionsVerificationRejectButton` — red (`:160`); opens `RejectionReasonModal` (`:168`); then `self.view.bot.api.verify_completion(...)` verified=False (`:174`).
- `completions.py:299` `CompletionVerificationView(ui.LayoutView)`.
- `completions.py:562` `@queue_consumer("api.completion.submission", struct_type=CompletionCreatedEvent, idempotent=True)` → `_process_create_submission_message` (`:563`): fetch submission, build view, send to `self.verification_channel`, store `verification_id`.
- `completions.py:573` `@queue_consumer("api.completion.verification", struct_type=VerificationChangedEvent, idempotent=True)` → `_process_verification_status_change` (`:574`): on `event.verified` posts completion embed + DM + XP grants.
- Bot client: `api_service.py:1080` `verify_completion(...)` → `PATCH /completions/{id}/verify` (mirror for tournament); `submit_completion` at `:1031`.
- API verify route: `routes/v3/completions.py` `verify_completion` handler calls `svc.verify_completion` (verify endpoint exists; the completions POST submit is at `:97`). `[note: exact verify route path is `PATCH /completions/{id}/verify` per bot client]`.

### Phase 9 tournament bot consumers (exist, but ONLY for cycle events)
- `apps/bot/extensions/tournaments.py:68` `TournamentHandler(BaseHandler)`, registered as PUBLIC `bot.tournaments`.
- `:79` `@queue_consumer("api.tournament.cycle_started", ...)` → `_on_cycle_started` (`:84`).
- `:111` `@queue_consumer("api.tournament.cycle_completed", ...)` → `_on_cycle_completed` (`:116`).
- **No tournament completion-created or verification-changed consumer exists.** Phase 11 adds one (+ queue + struct + bot view + api_service method).

### Tournament submit + keep-fastest + cross-write (today's bypass — to remove/repurpose)
- `tournament_service.py:497` `submit_completion(cycle_id, data: TournamentCompletionCreateRequest)`:
  - `:521` `async with self._pool.acquire() as conn, conn.transaction():`
  - `:522-529` `fetch_cycle` → `CycleNotFoundError`/`CycleNotActiveError`.
  - `:531-537` `fetch_user_completion(cycle_id, user_id)` → if `data.time >= existing["time"]` raise `SlowerTimeError` (**keep-fastest gate, D3**).
  - `:539` `is_first_completion = existing is None`.
  - `:541-549` `create_tournament_completion(cycle_id, user_id, map_id=cycle["map_id"], time, screenshot, video)`.
  - `:551-559` `cross_write_to_core(tournament_completion_id=row["id"], user_id, map_id, time, screenshot, video)` — **PB-gated CTE** (inserts core row only when strictly faster; returns new core id or None; writes `verified=FALSE`).
  - `:572-578` if `is_first_completion` → `award_participation(cycle, user_id, conn)` (collect events).
  - `:580-582` after commit → `publish_xp_events`.
- Repo `create_tournament_completion` (`:885-928`): plain `INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot, video) VALUES (...) RETURNING *`. No `ON CONFLICT`. Catches UniqueViolation/FK → domain errors (VERIFIED full body).
- Repo `cross_write_to_core` (`:930+`): CTE `current_best` → `should_insert` (TRUE iff `$4 < best_time` or none) → conditional insert into `core.completions` with `tournament_completion_id` link. Returns new core id or None.

### Leaderboard (D3) — already correct, no change
- `fetch_leaderboard` (`repo:1011`): best-per-user CTE `ORDER BY tc.user_id, tc.verified DESC, tc.time ASC`, then `RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)` over `tournaments.completions` only. Never reads `core.completions`. Unverified sort below verified. Index `idx_tournament_completions_ranking (cycle_id, verified DESC, time ASC)` supports it.
- `fetch_user_completion` (`repo:1055`): `SELECT * ... WHERE cycle_id=$1 AND user_id=$2 ORDER BY verified DESC, time ASC LIMIT 1` — best-per-user read.

### XP ledger idempotency (D6) — already implemented (migration 0022)
- `claim_xp_grant` (`repo:837`): `INSERT INTO tournaments.xp_grants (cycle_id, user_id, reason, amount) VALUES (...) ON CONFLICT (cycle_id, user_id, reason) DO NOTHING RETURNING id`; returns `row is not None` (True only on fresh claim) (VERIFIED).
- `tournament_reward_service.py:_grant_xp` (`:64`): claims first; on fresh claim delegates to `LootboxService.grant_xp` (joins caller's txn) + appends a deferred `XpGrantEvent`. `award_participation` (`:136`) → `_grant_xp(reason_key="participation")`; a 0 participation_xp or an already-claimed grant is a no-op. `publish_xp_events` (`:122`) flushes deferred events post-commit. **Calling `award_participation` repeatedly across PB + non-PB + resubmissions is safe.**

---

## Integration Points (with file:line)

### Speed trigger (root cause of D4b)
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` — `core.enforce_speed_rules_nonlegacy_only()` rejects any non-legacy insert into `core.completions` not strictly faster than the user's best non-legacy time (verified OR pending). ⇒ slower-than-PB runs get **no core row** and never fire a core verification event.
- `completions_repository.py:1512` `insert_completion` — `WITH target_map ... INSERT INTO core.completions (...) RETURNING id`; catches `UniqueViolationError` → `UniqueConstraintViolationError`, `ForeignKeyViolationError` → domain. **The 0017 speed-trigger `RAISE` is NOT explicitly caught here** — it propagates as a raw asyncpg error unless a higher layer translates it. Migration 0012 ("improve speed trigger error") suggests the trigger raises a recognizable message. `[CONFIRM at plan time]` exactly which exception surfaces from the speed trigger so D4b catches the right one (NOT the same as `SlowerThanPendingError`, which is the explicit pending-faster precheck at `completions_service.py:443`). See Pitfall P7.

### Tournament schema (migration `0020_tournaments.sql`, VERIFIED)
- `tournaments.completions` (lines 86-99): `id, cycle_id→cycles, user_id→core.users, map_id→core.maps, time numeric(10,2), screenshot text NOT NULL, video text, verified bool DEFAULT FALSE, completion bool DEFAULT FALSE, inserted_at timestamptz, UNIQUE(cycle_id,user_id,inserted_at)`. No `verified_by`/`verified_at`.
- `tournaments.cycles` (lines 59-69): `id, category_id, map_id→core.maps, status('pending'|'active'|'finalizing'|'completed'), started_at, ended_at, created_at`. Index `idx_cycles_map_id` (line 72) and `idx_cycles_category_status` exist.
- `core.completions.tournament_completion_id` (lines 170-172): `int REFERENCES tournaments.completions(id) ON DELETE SET NULL` + partial index (174-176).
- `tournaments.xp_grants` ledger: migration `0022_tournament_xp_grants.sql`; `UNIQUE(cycle_id,user_id,reason)` (per `claim_xp_grant`).
- **Highest existing migration = `0022`.** A new Phase 11 migration would be `0023`.

### DI wiring
- `CompletionsService.__init__(pool, state, completions_repo)` (`completions_service.py:78`) — **no tournament dependency.** Provider `provide_completions_service(state, completions_repo)` (`:922`).
- `TournamentService.__init__(pool, state, tournament_repo, reward_service=None)` (`tournament_service.py:55-74`; `reward_service` is Optional with a comment that DI always supplies it). Provider `provide_tournament_service(state, tournament_repo, tournament_reward_service)` (`:629-645`).
- `TournamentRewardService.__init__(pool, state, tournament_repo, lootbox_repo, lootbox_service)` (`reward:42-62`). Provider at `reward:274`.
- `completions.py` route providers: `svc/users/notifications/users_repo/completions_repo` (`routes/v3/completions.py:58-62`).

### Bypass to remove (D5)
- Route `routes/v3/tournaments.py:459-500` `@post("/cycles/{cycle_id:int}/submit")` → handler `submit_completion` (`:465`), body `TournamentCompletionCreateRequest` (`:469`), returns `TournamentCompletionResponse`, calls `tournament_service.submit_completion(cycle_id, data)` (`:485`), catches `CycleNotFoundError/CycleNotActiveError/SlowerTimeError`.
- Service `tournament_service.py:497-584` `submit_completion`.
- Repo `cross_write_to_core` (`repo:930+`) — **PRESERVE the PB-gated CTE for D4a** (it is still needed to cross-write PB tournament runs into core with the FK link); only remove the unverified bypass route + its XP-on-submit. `[CONFIRM]` no other caller via grep.
- SDK `TournamentCompletionCreateRequest` (`tournaments.py:331-345`: `user_id, time, screenshot, video`) + `__all__` entry (`:17`). Remove only after the new path stops using it. **`TournamentCompletionResponse` (`:347-372`) and `TournamentCompletionCreatedEvent` (`:441-451`) already exist — KEEP** (response likely used elsewhere; the event will be reused for the new queue).
- `scripts/seed-tournament-local.sh` — header (line 16) says it POSTs to `/api/v3/tournaments/cycles/{id}/submit`; the visible body posts categories/select-map (lines 112/149) and likely the submit later. Replace the bypass POST with a normal completion POST on the cycle map.
- Tests that hit submit (grep results): `apps/api/tests/repository/tournaments/test_cycle_transitions.py`, `apps/api/tests/integration/test_tournament_rewards.py`, `apps/api/tests/integration/test_completions_integration.py`, `apps/api/tests/integration/test_tournaments_integration.py`, `apps/api/tests/services/test_tournament_service.py`, `apps/api/tests/services/test_completions_service.py`. Plus bot tests `apps/api/tests/bot/test_tournament_commands.py`, `test_tournaments_handler.py` (both in current working tree). Rewrite the submit-asserting cases.

---

## Recommended Approach (per D1-D6)

### D1 + D2 — Auto-detect on normal submission
**Add a repo lookup** (none keyed on map_id; `check_active_cycle_for_category` `repo:257` keys on category):
```python
# tournaments_repository.py — new
async def get_active_cycle_by_map_id(self, map_id: int, *, conn=None) -> dict | None:
    _conn = self._get_connection(conn)
    return await _conn.fetchrow(
        "SELECT id, category_id, map_id, status FROM tournaments.cycles "
        "WHERE map_id = $1 AND status = 'active' LIMIT 1",
        map_id,
    )
```
`idx_cycles_map_id` already exists (0020:72). A cycle pins one map (D2).

**Wire tournament logic into the completion submit path.** Recommended: inject `TournamentService` into `CompletionsService` (add to `__init__` `:78` + `provide_completions_service` `:922`), guarded with a `TYPE_CHECKING` import to avoid a circular import (CLAUDE.md pattern). [ASSUMED — planner may inject `TournamentRepository` + `TournamentRewardService` directly if a cycle appears.] `provide_tournament_service` already exists; Litestar resolves nested deps.

**Hook point:** inside `submit_completion`. The service currently resolves map existence by `code` only (`:433`) and does not hold `map_id`; `insert_completion` resolves map_id internally via the `target_map` CTE and returns only the new completion id. So you need a `map_id` for the active-cycle lookup — add a `lookup_map_id(code)` (or extend a query) once, then call `get_active_cycle_by_map_id`. Branch PB vs non-PB.

### D4a (PB path) — ride the core verdict
PB run inserts into `core.completions` successfully (`:448`). Tournament side:
1. After the successful core insert, insert the tournament row (reuse `create_tournament_completion`; the `UNIQUE(...,inserted_at)` means a new row per submission is allowed — keep-fastest is read-time, so no upsert needed). Optionally short-circuit if not faster than the user's current tournament best (`fetch_user_completion`) to avoid noise, but it's not required for correctness (leaderboard already picks best-per-user).
2. **Link** core→tournament via `core.completions.tournament_completion_id` in the same transaction. Either extend `insert_completion` to accept an optional `tournament_completion_id`, or `UPDATE core.completions SET tournament_completion_id=$1 WHERE id=$2`. (The bypass's `cross_write_to_core` already demonstrates writing this link; for the PB path the core row is created by the normal `insert_completion`, so you set the link explicitly.)
3. **Verification propagation:** in `verify_completion` (`:575`), after `update_verification`, you already have `completion_info` (user_id/code/old_time). Resolve map_id from the code, call `get_active_cycle_by_map_id`; if active AND the core row has a `tournament_completion_id`, call a new repo `set_tournament_verified(tournament_completion_id)` and fire `award_participation` (D6) — in the same `conn` transaction — then publish a new `TournamentVerificationChangedEvent`.
   - **Do the tournament-verify side-effect inside the service `verify_completion`, not as a bot consumer** — keeps it atomic with the core verify and avoids a second round-trip / double-XP race. [ASSUMED]

> **Correction vs CONTEXT phrasing:** CONTEXT D4a says "On `VerificationChangedEvent` the linked tournament record is marked verified." The event struct carries NO map_id and the bot cannot write the DB, so the marking must happen API-side inside `verify_completion` (which has completion + map context), not by consuming the event. The event is still published for the bot's UI as today.

### D4b (non-PB path) — tournament-native verification (the hard part)
A slower-than-PB run is rejected by the 0017 speed trigger at `insert_completion`. **Catch the trigger error, don't abort the request:**
```python
try:
    completion_id = await self._completions_repo.insert_completion(...)
    core_id = completion_id
except <SpeedTriggerError>:   # [CONFIRM exact exception — NOT SlowerThanPendingError]
    core_id = None  # non-PB: still record for the tournament if relevant
```
> ⚠️ `SlowerThanPendingError` is the explicit pending-faster precheck (`:443`), raised BEFORE insert. The speed-TRIGGER rejection at `insert_completion` is a separate path (`insert_completion` only catches Unique/FK today). D4b must branch ONLY on the trigger-rejection case and let genuine duplicate/FK errors propagate (Pitfall P7). Confirm the trigger's surfaced exception (migrations 0012/0017) at plan time.

If `active_cycle is not None` and the run is non-PB:
- Insert into `tournaments.completions` (best computed at read time). If you want strict keep-fastest semantics, gate on `fetch_user_completion` first (skip if not faster than existing tournament best).
- Kick off tournament verification for the unverified row:
  - **No-video → OCR auto-verify (tournament variant).** Reuse the OCR HTTP check (screenshot passed in). Add a new in-process event `tournament.ocr.requested(tournament_completion_id, cycle_id, user_id, code, time, screenshot)` → new listener in `apps/api/events/` (mirror `events/completions.py:17`) → new `attempt_tournament_auto_verify_async` that runs the same `/extract` call and, on match, calls a new `verify_tournament_completion(tournament_completion_id)` (sets verified + XP + publishes the new tournament verification event); on mismatch → escalate to mod review (publish the new completion-created tournament event).
    - *Reuse vs variant (Discretion):* **variant** — the OCR core is reusable but `attempt_auto_verify_async` ends by verifying a CORE completion that doesn't exist for non-PB (Pitfall P4). [ASSUMED — `attempt_auto_verify_async`'s only core coupling is the final `verify_completion_with_pool(completion_id)` + the idempotency key; the OCR `/extract` check itself needs only screenshot+code+time+names.]
  - **Video → mod Accept/Reject.** Publish a NEW event on a NEW queue (must be added to `infra/rabbitmq/definitions.json` with DLQ + binding — Phase 09-03 decision, commits `4c31fa4`/`33059e7`). `TournamentCompletionCreatedEvent` (`tournaments.py:441`) currently has only `completion_id, cycle_id` — **extend it** (add user_id/time/video/screenshot) OR have the bot fetch details via a new GET endpoint on receipt (the cycle-event consumers already follow "consumer-only, fetch details on receipt" per `tournaments.py` docstring). Bot side: add a consumer in `TournamentHandler` (or a sibling) rendering an Accept/Reject `ui.View` mirroring `CompletionsVerificationAccept/RejectButton` with DISTINCT `custom_id`s (`tournament_verify_accept`/`tournament_verify_reject` — Pitfall P3) → `bot.api.verify_tournament_completion(tc_id)` / `reject_tournament_completion(tc_id)`.
- **Bot verify callback → new API endpoint** (bot never writes DB):
  - `PATCH /api/v3/tournaments/completions/{tournament_completion_id:int}/verify` (scope `tournaments:verify`) → `TournamentService.verify_tournament_completion` → `set_tournament_verified` + `award_participation` (D6) + publish `TournamentVerificationChangedEvent`.
  - `PATCH .../{id}/reject` → keep row `verified=FALSE` (simplest; stays below verified on the board). Deferred ideas exclude reject-notify.

### D3 — keep fastest tournament time
No ranking change. Concrete tasks: (a) reproduce keep-fastest for the new auto-detect path. **Because the table is `UNIQUE(cycle_id,user_id,inserted_at)` (multiple rows allowed) and "best" is read-time**, the simplest correct approach is: insert each verified-eligible run as a new row and let `fetch_leaderboard`/`fetch_user_completion` pick the best. If product wants exactly one row per (cycle,user), that requires a schema change (add `UNIQUE(cycle_id,user_id)` + an upsert) — **out of scope unless the planner decides**; the read-time approach already satisfies D3 ("keep each player's fastest tournament-window time" = the leaderboard shows their best). (b) Confirm no slower-than-PB row enters `core.completions` — guaranteed by 0017 trigger + PB-gated cross-write; leaderboard core-independent.

> **Correction:** earlier drafts proposed an `ON CONFLICT (cycle_id,user_id)` upsert. That constraint does NOT exist (it's `(cycle_id,user_id,inserted_at)`). Do NOT assume an upsert is available without a schema migration.

### D5 — remove the bypass
Coordinated deletion (mind P1): route `tournaments.py:459-500`; service `submit_completion` `:497-584`; SDK `TournamentCompletionCreateRequest` (`:331` + `__all__` `:17`) after the new path stops using it; `scripts/seed-tournament-local.sh` bypass POST; the submit-asserting tests. **Do NOT delete `cross_write_to_core`** — repurpose/keep it for the D4a PB cross-write (or extract its PB-gated CTE). Remove only the verification-skipping route + XP-on-submit.

### D6 — participation XP on verification
Move `award_participation` out of `tournament_service.submit_completion` (`:572-578`) into:
- **PB path:** inside `verify_completion` tournament side-effect (D4a) after `set_tournament_verified`.
- **Non-PB path:** inside `verify_tournament_completion` (new endpoint service method) and the OCR-match branch.
Always call it on any verification; the `(cycle_id,user_id,'participation')` ledger dedupes (`claim_xp_grant`). Publish deferred XP events post-commit via `publish_xp_events` (existing pattern at `tournament_service.py:580-582`).

---

## New Events / Endpoints / SDK structs proposed

### New RabbitMQ queues (Discretion — add to `infra/rabbitmq/definitions.json` + DLQ + binding per Phase 09-03)
- `api.tournament.completion.created` — non-PB video run → bot Accept/Reject embed.
- `api.tournament.verification.changed` — emitted when a tournament row becomes verified (both paths) → bot posts result/notification.
(Tournament XP continues on the existing `api.xp.grant` queue — do NOT create `api.tournament.xp.grant`.)

### SDK structs (`libs/sdk/src/genjishimada_sdk/tournaments.py`, update `__all__`)
- `TournamentCompletionCreatedEvent` exists (`:441`) but has only `completion_id, cycle_id` — **extend** with `user_id, time, video, screenshot` OR keep slim and have the bot fetch details (consumer-only pattern). Recommend extend for fewer round-trips.
- NEW `TournamentVerificationChangedEvent`: `tournament_completion_id, cycle_id, user_id, verified, time` (and `verified_by` if you add that column).
- After D5, refactor `create_tournament_completion` callers off `TournamentCompletionCreateRequest` (it already takes primitive args at the repo level).

### New API endpoints (`routes/v3/tournaments.py`, scope `tournaments:verify`)
- `PATCH /api/v3/tournaments/completions/{tournament_completion_id:int}/verify`
- `PATCH /api/v3/tournaments/completions/{tournament_completion_id:int}/reject`
- (Optional GET `/api/v3/tournaments/completions/{id}` if the bot fetches details on receipt rather than carrying them in the event.)

### New bot client methods (`apps/bot/extensions/api_service.py`, mirror `verify_completion` at `:1080`)
- `verify_tournament_completion(tc_id)`, `reject_tournament_completion(tc_id)`.

### New in-process event (Discretion — OCR variant)
- `tournament.ocr.requested(tournament_completion_id, cycle_id, user_id, code, time, screenshot)` + listener in `apps/api/events/` → `attempt_tournament_auto_verify_async`.

### New repo methods (`tournaments_repository.py`)
- `get_active_cycle_by_map_id(map_id)` (D1/D2).
- `set_tournament_verified(tournament_completion_id, verified=True)` (both verify paths).
- (Optional) `fetch_tournament_completion(id)` for the verify endpoint + bot detail fetch.

### Schema migration (NEW = `0023`)
- Optional additive `verified_by BIGINT NULL` (+ `verified_at TIMESTAMPTZ NULL`) on `tournaments.completions` to distinguish OCR (BOT_USER_ID) vs mod verifications. LOW priority, additive-only, no rename. (A `UNIQUE(cycle_id,user_id)` migration is ONLY needed if product wants one-row-per-user instead of read-time best — not recommended for this phase.)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Best-per-user tournament time | Python max() loop | `fetch_leaderboard` / `fetch_user_completion` read-time best | Already implemented + indexed |
| XP idempotency | App-level dedupe set | `claim_xp_grant` ledger (`repo:837`) `ON CONFLICT DO NOTHING` | DB-enforced, survives retries |
| PB-gated core cross-write | New CTE | Existing `cross_write_to_core` CTE (`repo:930`) | Already avoids the 0017 trigger |
| OCR check | New OCR client | Existing `/extract` flow (`completions_service.py:308-332`) | Screenshot passed in, reusable |
| Mod Accept/Reject UI | New view framework | Mirror `CompletionsVerificationAccept/RejectButton` (`completions.py:103/155`) | Proven persistent-custom_id pattern |
| Speed-rule enforcement | Python pre-check | `core.enforce_speed_rules_nonlegacy_only` (0017) | Single source of truth |

**Key insight:** ~70-80% wiring of existing components; the only genuinely new construct is the non-PB tournament verification surface (queue + struct + bot view + verify endpoint + OCR variant), which mirrors the completions flow almost 1:1.

---

## Pitfalls

### P1: Duplicated symbol references / line drift
CONTEXT and live code cite the same symbols at slightly different lines. Python keeps the LAST definition. **Re-grep ALL definitions before deleting; re-confirm line numbers at edit time.**

### P2: `tournaments.completions` UNIQUE is `(cycle_id,user_id,inserted_at)`, not `(cycle_id,user_id)`
Multiple rows per (cycle,user) are allowed; best is read-time. Do NOT write an `ON CONFLICT (cycle_id,user_id)` upsert (it would error — no matching constraint). Keep-fastest is satisfied by the leaderboard's best-per-user CTE.

### P3: Phase 9 tournament consumers cover ONLY cycle events
`TournamentHandler` has `cycle_started`/`cycle_completed` only. The non-PB mod-review path needs a NEW consumer + NEW queue + NEW bot view. Use Accept/Reject `custom_id`s distinct from completions'.

### P4: OCR for non-PB must target the tournament row
`attempt_auto_verify_async` ends with `verify_completion_with_pool(completion_id)` against CORE completions. For non-PB there is no core row — route to `verify_tournament_completion(tournament_completion_id)`. The OCR check itself is reusable (screenshot passed in).

### P5: Double XP / double verification across paths
Always call `award_participation` (idempotent ledger); never branch on "already granted". `set_tournament_verified` (TRUE twice) is harmless.

### P6: Atomicity of core-insert + tournament-insert + FK link (PB path)
Wrap core insert + tournament insert + FK link in one `conn.transaction()` (the bypass already used this at `service:521`). All repo methods accept `conn=`.

### P7: Speed-trigger error type for D4b's catch
`insert_completion` (`repo:1512`) catches only Unique/FK; the 0017 speed-trigger `RAISE` propagates as a raw asyncpg error (migration 0012 improved its message). `SlowerThanPendingError` is a DIFFERENT thing (explicit pending-faster precheck at `:443`). **Confirm the trigger's surfaced exception and translate it** so D4b branches only on the speed-trigger case and lets duplicate/FK errors propagate.

### P8: `VerificationChangedEvent` does not carry map_id
Fields: `completion_id, verified, verified_by, reason` (`:639-644`). Do the tournament-verify side-effect inside `verify_completion` (which has completion/map context), not by re-deriving map from the event.

### P9: `cross_write_to_core` is still needed for D4a
D5 removes the bypass, but the PB-path STILL cross-writes to `core.completions`. For the normal PB path the core row already exists (created by `insert_completion`), so set `tournament_completion_id` directly; keep the PB-gated CTE knowledge if you need a separate cross-write path.

---

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `tournaments.completions` rows from the bypass (unverified, possibly cross-written) | None for new flow; backfill explicitly OUT OF SCOPE (Deferred). Existing rows keep working with the leaderboard query. |
| Live service config | RabbitMQ definitions only have `api.tournament.cycle_started/completed` + `api.xp.grant`; the NEW tournament completion/verification queues MUST be added to `infra/rabbitmq/definitions.json` with DLQ + binding (Phase 09-03) | Add 2 queues + 2 DLQs + bindings |
| OS-registered state | pg_cron cycle-transition jobs (migration 0021/Phase 7) | None — Phase 11 doesn't touch scheduling. Verified: no cron change. |
| Secrets/env vars | None new | None. Confirm bot API token carries the new `tournaments:verify` scope. |
| Build artifacts | SDK is a workspace package; editing `genjishimada_sdk.tournaments` requires `just fix`/`just sync` so API + bot resolve struct changes | Run `just fix` after SDK edits (MEMORY: `ModuleNotFoundError` fix). Ensure `tournaments:verify` scope exists in auth scope set / token seeding. |

**New scope alert:** new verify endpoints use `tournaments:verify`. Existing tournament routes use `tournaments:read`/`tournaments:write` (`routes/v3/tournaments.py:70/91`). Confirm the bot token carries the new scope (mirror `completions:verify` grant).

---

## Test Strategy

### How tournament + completion flows are tested
- `apps/api/tests/conftest.py` — API test client; `X-PYTEST-ENABLED=1` makes `BaseService.publish_message` skip real RabbitMQ. Assert on job/DB state or mock publish, not the broker.
- Existing: `tests/services/test_tournament_service.py`, `tests/services/test_tournament_reward_service.py`, `tests/services/test_completions_service.py`, `tests/integration/test_tournaments_integration.py`, `tests/integration/test_tournament_rewards.py`, `tests/integration/test_completions_integration.py`, `tests/repository/tournaments/test_cycle_transitions.py`.
- `apps/api/tests/bot/conftest.py` — inserts `apps/bot` onto `sys.path` and removes it in `finally` (commit `07e8b0d`). Bot handler tests under `apps/api/tests/bot/` (`test_tournament_commands.py`, `test_tournaments_handler.py`, `test_rabbit_dlq_sweep.py`).
- Run targeted: `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` (paths relative to `apps/api`). Multi-file runs need `--no-testmon` (MEMORY: testmon deselects on multi-file). Single-file fine. No `--timeout` flag. Use `-p no:xdist` for targeted runs.
- Full suite: `just test-api`.

### What to test for Phase 11
- **Auto-detect (D1/D2):** normal completion on active-cycle map → tournament row; non-cycle map → none. `get_active_cycle_by_map_id` active vs ended.
- **PB path (D4a):** PB completion → core row + tournament row + `tournament_completion_id` link; core verify → tournament `verified=TRUE` + XP + tournament verification event published (assert via mocked publish / DB).
- **Non-PB path (D4b):** slower-than-PB on cycle map → NO core row (assert `core.completions` unchanged); tournament row created; video → new completion-created tournament event published; no-video → OCR variant; mod verify endpoint sets `verified=TRUE`.
- **Keep-fastest (D3):** two submissions → leaderboard/`fetch_user_completion` returns the faster verified one.
- **XP idempotency (D6):** verify twice / both paths → exactly one `participation` ledger row.
- **Bypass removed (D5):** `POST /cycles/{id}/submit` → 404/405; deleted symbols not importable.

### Pre-existing flaky/stale (NOT regressions — from MEMORY)
- `test_difficulty_exact_filter` — `Hard +` vs `Hard` mismatch (pre-existing).
- `TestFetchMapsFilterCategory::test_filter_by_single_category` — flakes under `-n 4` (cross-worker DB contamination); passes isolated.
- `check_active_cycle_for_category` returns `int | None` (cycle_id), NOT bool — Phase 4 contract (commit `4fc56b6`). Don't write `is True/False` assertions against it.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.3.5 + pytest-asyncio (auto) + pytest-databases[postgres] + pytest-xdist + pytest-testmon |
| Config file | `apps/api/pyproject.toml` (`addopts = "--testmon"`) |
| Quick run | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` |
| Full suite | `just test-api` |

### Phase Requirements → Test Map
| Req | Behavior | Type | Command | Exists? |
|-----|----------|------|---------|---------|
| SC-4 | bypass gone | integration | `pytest tests/integration/test_tournaments_integration.py -p no:xdist` | ✅ rewrite |
| SC-1 | auto-detect by map | unit+int | `pytest tests/services/test_tournament_service.py -p no:xdist` | ✅ extend |
| SC-3 | PB verify propagates | integration | `pytest tests/services/test_tournament_verification.py -p no:xdist` | ❌ Wave 0 |
| SC-2 | non-PB verify (OCR+mod) | integration | `pytest tests/services/test_tournament_verification.py -p no:xdist` | ❌ Wave 0 |
| SC-5/D3 | keep-fastest + XP idempotent | unit | `pytest tests/services/test_tournament_service.py -p no:xdist` | ✅ extend |
| SC-6 | core invariant preserved | integration | `pytest tests/integration/test_completions_integration.py -p no:xdist` | ✅ extend |

### Sampling Rate
- Per task commit: the single most relevant `test_*.py -p no:xdist`.
- Per wave merge: `uv run --directory apps/api pytest tests/services tests/integration tests/bot --no-testmon -p no:xdist`.
- Phase gate: `just test-api` green (mind known flakes).

### Wave 0 Gaps
- [ ] `tests/services/test_tournament_verification.py` — SC-2/SC-3 (PB propagation, non-PB OCR + mod verify endpoint).
- [ ] Fixtures: non-PB submission (pre-seed a faster core completion to trip the 0017 trigger) + tournament completion factory keyed to a cycle map.
- [ ] Bot Accept/Reject view test under `tests/bot/`.

## Security Domain

> `security_enforcement` not disabled in config — treated as enabled.

### Applicable ASVS Categories
| ASVS | Applies | Control |
|------|---------|---------|
| V4 Access Control | yes | New verify/reject endpoints require `tournaments:verify` scope (mirror tournament scopes at `routes/v3/tournaments.py:70/91`); superusers bypass per `middleware/guards.py` |
| V5 Input Validation | yes | `tournament_completion_id:int` typed path param; msgspec validates event/request structs |
| V1/V2 Auth | yes | Bot authenticates via `X-API-KEY`; bot token must carry the new scope |
| V6 Cryptography | no | none introduced |

### Threat Patterns
| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| Player self-verifies tournament run | Elevation of Privilege | `tournaments:verify` scope guard on PATCH endpoints |
| Replay verify → double XP | Tampering | `xp_grants` UNIQUE ledger; idempotent `set_tournament_verified` |
| SQL injection in new lookups | Tampering | asyncpg `$1` positional params only (CLAUDE.md: never f-string SQL) |
| DLQ poisoning on new consumers | DoS | per-queue DLQ + isolated sweep (Phase 09-03, commit `33059e7`) |

---

## Assumptions Log
| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Inject `TournamentService` into `CompletionsService` (vs bare repo) is cleaner DI | D1/D2 | Circular import; mitigate with `TYPE_CHECKING` or inject repo+reward |
| A2 | PB tournament-verify done synchronously inside `verify_completion`, not a consumer | D4a | If a consumer, double-XP/race risk — ledger still protects |
| A3 | OCR variant required for non-PB (verify target differs); OCR `/extract` check itself reusable | D4b | If `attempt_auto_verify_async` has hidden core coupling beyond the final verify call — variant still safest |
| A4 | `cross_write_to_core` / its PB-gated CTE must be PRESERVED for D4a; only bypass route + XP-on-submit removed | D5 | Deleting it breaks PB cross-write |
| A5 | New tournament completion/verification queues must be created (they don't exist) | New events | Building on a non-existent queue would fail silently |
| A6 | Keep-fastest via read-time best-per-user (no upsert) satisfies D3; no `UNIQUE(cycle_id,user_id)` migration needed | D3/P2 | If product wants one row per user, a schema migration is required |
| A7 | `tournaments:verify` scope gates new endpoints; bot token must carry it | Security | Confirm scope naming + token grant |
| A8 | New migration number is `0023` | New structs | If another migration lands first, bump |

## Open Questions
1. Reject semantics for non-PB runs: keep `verified=FALSE` (recommended, simplest) vs add a `rejected` flag vs delete. Deferred ideas exclude reject-notify.
2. Should `TournamentCompletionCreatedEvent` be extended (carry details) or stay slim (bot fetches on receipt, matching the existing consumer-only pattern)? Recommend extend for fewer round-trips.
3. Exact exception surfaced by the 0017 speed trigger from `insert_completion` (P7) — confirm at plan time so D4b catches precisely.
4. Does product require exactly one `tournaments.completions` row per (cycle,user) (schema change) or is read-time best-per-user acceptable (no change)? (D3/A6.)

## Environment Availability
| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (pg_cron image) | tournaments schema, new migration | ✓ (docker-compose.local) | 17 | — |
| RabbitMQ (definitions.json) | tournament event queues | ✓ | mgmt image | — |
| OCR HTTP service (`genjishimada-ocr[-dev]:8000/extract`) | non-PB no-video auto-verify | ✓ (referenced `completions_service.py:308-321`) | in-infra | mod review path |
| uv / just | build, test, SDK sync | ✓ | per repo | — |

No missing dependencies. SDK struct edits require `just fix`/`just sync`.

## Sources
### Primary (HIGH confidence — codebase reads, file:line verified this session)
- `apps/api/services/completions_service.py` (full submit/verify/OCR pipeline)
- `apps/api/services/tournament_service.py` (bypass submit + DI + reward call)
- `apps/api/services/tournament_reward_service.py` (XP ledger; `award_participation` body; `__init__`)
- `apps/api/repository/tournaments_repository.py` (`create_tournament_completion` full body, `fetch_user_completion`, `claim_xp_grant`, `check_active_cycle_for_category`, leaderboard, `cross_write_to_core` header)
- `apps/api/repository/completions_repository.py` (`insert_completion` full body + error translation)
- `apps/api/routes/v3/tournaments.py` (submit route `:459-500`), `apps/api/routes/v3/completions.py` (submit `:97`, providers)
- `apps/api/events/completions.py` (OCR listener full file, `:17`)
- `apps/api/migrations/0020_tournaments.sql` (full schema — completions table, FK, indexes), migration list (highest = 0022)
- `apps/bot/extensions/completions.py` (Accept/Reject buttons + consumers), `tournaments.py` (cycle consumers only), `api_service.py` (method index incl. `verify_completion` `:1080`)
- `libs/sdk/src/genjishimada_sdk/tournaments.py` (`__all__`, completion/response/event structs), `completions.py` (struct index)
- `infra/rabbitmq/definitions.json` (queue list — tournament = cycle-only + `api.xp.grant`)
- `scripts/seed-tournament-local.sh` (header indicates bypass POST usage)
- `.planning/phases/11-tournament-verification-flow/11-CONTEXT.md`, `.planning/ROADMAP.md`, `./CLAUDE.md`, project MEMORY.md

## Metadata
**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; existing components verified.
- Integration map / architecture: HIGH — flows traced to file:line from live source; schema verified from migration DDL.
- D4b design: MEDIUM-HIGH — mirrors proven completions pattern; the only open item is the exact speed-trigger exception (P7/Q3).
- Schema specifics: HIGH — full 0020 DDL read; UNIQUE constraint + column set verified.

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (stable internal codebase; re-verify line numbers if other phases land first)
