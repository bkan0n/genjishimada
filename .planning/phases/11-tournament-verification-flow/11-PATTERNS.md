# Phase 11: Tournament Verification Flow - Pattern Map

**Mapped:** 2026-05-31
**Files analyzed:** 14 (new + modified)
**Analogs found:** 14 / 14

> **READ THIS FIRST — line numbers drift.** RESEARCH Pitfall P1 + the methodology note warn that symbols are cited at slightly different lines across CONTEXT/RESEARCH and that Python keeps the LAST definition. Every line range below was re-verified from live source this session, but the planner MUST re-grep at edit time.
>
> **The phase is NOT a simple "mirror the completion verify pipeline 1:1".** It is a **hybrid** flow:
> - **PB runs** ride the *existing* completion pipeline (`insert_completion` → OCR/mod → `verify_completion`); Phase 11 adds a tournament *side-effect inside* `verify_completion` (no new queue, no new bot embed for PB).
> - **Non-PB runs** (rejected by the 0017 speed trigger, so NO core row) get a **new tournament-native verification surface** — this is where the completion pipeline is mirrored (new queue + SDK event + bot Accept/Reject view + new verify endpoint + OCR variant).
>
> So when this doc says "mirror completions", it specifically means the **non-PB (D4b)** surface. The PB (D4a) path is an *in-place edit* to existing completion code, not a copy.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/repository/tournaments_repository.py` — `get_active_cycle_by_map_id`, `set_tournament_verified`, (opt) `fetch_tournament_completion`; PRESERVE `cross_write_to_core`/`create_tournament_completion` | repository | CRUD / lookup | `tournaments_repository.py` `check_active_cycle_for_category` (L257), `fetch_user_completion` (L1055), `create_tournament_completion` (L885) | exact (same file) |
| `apps/api/services/completions_service.py` — hook tournament logic into `submit_completion` (L413) + tournament side-effect in `verify_completion` (L575); catch speed-trigger | service | event-driven / CRUD | `completions_service.py` `submit_completion` (L413-501), `verify_completion` (L575-652) | exact (same file) |
| `apps/api/services/tournament_service.py` — REMOVE bypass `submit_completion` (L497-584); ADD `verify_tournament_completion`; move `award_participation` off submit | service | event-driven | `completions_service.py` `verify_completion` (L575-652) for the new verify method; existing `submit_completion` (L497) for removal | exact / role-match |
| `apps/api/services/tournament_outbox_service.py` (verify if any submit dependents) | service | event-driven | existing same file | role-match |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` — extend `TournamentCompletionCreatedEvent` (L441); NEW `TournamentVerificationChangedEvent`; update `__all__` (L8-31) | SDK struct / event | event-driven | `genjishimada_sdk/completions.py` `CompletionCreatedEvent` (L325), `VerificationChangedEvent` (L335) | exact |
| `apps/api/events/completions.py` + `apps/api/events/schemas.py` — NEW `tournament.ocr.requested` listener + event schema | event listener | event-driven | `events/completions.py` `handle_ocr_verification` (L17-40); `events/schemas.py` `OcrVerificationRequestedEvent` | exact (same files) |
| `apps/api/services/completions_service.py` — NEW `attempt_tournament_auto_verify_async` (OCR variant) | service | request-response (HTTP OCR) | `attempt_auto_verify_async` (L281-412) | exact (same file) |
| `infra/rabbitmq/definitions.json` — NEW `api.tournament.completion.created` + `api.tournament.verification.changed` (+ 2 DLQs) | config | pub-sub | existing `api.tournament.cycle_started` block (L356-373) + its DLQ | exact |
| `apps/api/routes/v3/tournaments.py` — NEW verify/reject endpoints; REMOVE bypass submit route (L459-503) | route/controller | request-response | `routes/v3/completions.py` verify handler; same-file `submit_completion` route (L463-503) for removal | exact / role-match |
| `apps/bot/extensions/tournaments.py` — NEW consumer(s) + Accept/Reject `ui.View` | bot extension | event-driven | `apps/bot/extensions/completions.py` `_process_create_submission_message` (L562) + `CompletionVerificationView` (L299) + Accept/Reject buttons (L103/L155) | exact |
| `apps/bot/extensions/api_service.py` — NEW `verify_tournament_completion`, `reject_tournament_completion` | bot client | request-response | `api_service.py` `verify_completion` (~L1080) | exact |
| `scripts/seed-tournament-local.sh` — replace bypass POST with normal completion POST | script | n/a | existing seed script | role-match |
| `apps/api/tests/services/test_tournament_verification.py` (NEW) + extend `test_tournament_service.py`, `test_completions_integration.py`, `test_tournaments_integration.py` | test | request-response / event-driven | `tests/services/test_tournament_service.py`, `tests/integration/test_tournaments_integration.py` | exact / role-match |
| `apps/api/tests/bot/test_tournaments_handler.py` — NEW Accept/Reject view test; rewrite submit-asserting cases | test | event-driven | `tests/bot/test_tournaments_handler.py` (existing cycle-handler tests, stubbed `queue_consumer` at L96-112) | exact (same file) |

> **Migration:** RESEARCH marks a new `0023` migration (additive `verified_by`/`verified_at` on `tournaments.completions`) as LOW priority / optional. Treat as optional — only needed if the planner wants to distinguish OCR (BOT_USER_ID) vs mod verifications. Analog for a migration file: `apps/api/migrations/0020_tournaments.sql` / `0022_tournament_xp_grants.sql`.

---

## Pattern Assignments

### `apps/api/repository/tournaments_repository.py` (repository, CRUD/lookup)

**Analog:** same file — `check_active_cycle_for_category` (L257), `fetch_user_completion` (L1055), `create_tournament_completion` (L885), `cross_write_to_core` (L930).

**`get_active_cycle_by_map_id` (NEW, D1/D2).** Mirror the `_get_connection(conn)` + `fetchrow` + positional-param convention used everywhere in this file (e.g. `fetch_category` L148, `check_active_cycle_for_category` L257). Index `idx_cycles_map_id` (migration 0020:72) already exists. RESEARCH §D1 gives the exact query:

```python
async def get_active_cycle_by_map_id(self, map_id: int, *, conn: Connection | None = None) -> dict | None:
    _conn = self._get_connection(conn)
    return await _conn.fetchrow(
        "SELECT id, category_id, map_id, status FROM tournaments.cycles "
        "WHERE map_id = $1 AND status = 'active' LIMIT 1",
        map_id,
    )
```

**`set_tournament_verified` (NEW, both verify paths).** Mirror `update_completion_verified` shape from completions (`completions_repository.py:1894`) — a targeted `UPDATE ... WHERE id=$1` with `_get_connection(conn)`. Table has NO `verified_by`/`verified_at` (migration 0020:86-99) unless the optional 0023 migration adds them:

```python
async def set_tournament_verified(self, tournament_completion_id: int, verified: bool = True,
                                  *, conn: Connection | None = None) -> dict | None:
    _conn = self._get_connection(conn)
    row = await _conn.fetchrow(
        "UPDATE tournaments.completions SET verified = $2 WHERE id = $1 "
        "RETURNING id, cycle_id, user_id, time",
        tournament_completion_id, verified,
    )
    return dict(row) if row else None
```

**PRESERVE (do NOT delete) `cross_write_to_core` (L930) and `create_tournament_completion` (L885)** — RESEARCH P9/A4: the PB path still cross-writes and still inserts tournament rows. `create_tournament_completion` (L885-928) is a plain `INSERT ... RETURNING *` with NO `ON CONFLICT` (P2 — the UNIQUE is `(cycle_id,user_id,inserted_at)`, multiple rows allowed, best computed at read time). Its error translation (UniqueViolation/FK/Check → domain errors, L915-928) is the template if you add any new insert.

**Constraint:** asyncpg `$1` positional params only, never f-string SQL (CLAUDE.md; one f-string `set_clauses` exception exists in `update_config` L75 but field names are code-controlled, not user input — do not copy that for value interpolation).

---

### `apps/api/services/completions_service.py` (service — modify `submit_completion` L413 and `verify_completion` L575)

**Analog:** same file.

**Hook into `submit_completion` (L413-501).** Verified shape of the existing method:
- map-existence check (L433-435), then `async with self._pool.acquire() as conn, conn.transaction():` (L437);
- pending-faster precheck → `SlowerThanPendingError` BEFORE insert (L438-446);
- `insert_completion(...)` at L449 (this is where the 0017 speed trigger fires for non-PB);
- no-video + not suspicious → emit in-process OCR `request.app.emit("completion.ocr.requested", OcrVerificationRequestedEvent(...))` (L478-492) and return early;
- else (video/suspicious) → `publish_message(routing_key="api.completion.submission", data=CompletionCreatedEvent(completion_id), idempotency_key=...)` (L494-501).

Phase 11 inserts a tournament branch after the core insert: resolve `map_id` (add a `lookup_map_id(code)` repo call — RESEARCH §D1/D2 hook note), call `get_active_cycle_by_map_id`. **PB** (insert succeeded) → insert tournament row + set `core.completions.tournament_completion_id` link, all inside the SAME `conn.transaction()` (P6). **Non-PB** → see speed-trigger catch below.

**Speed-trigger catch (D4b, P7).** `insert_completion` (`completions_repository.py:1512`) catches ONLY `UniqueViolationError`/`ForeignKeyViolationError` (L1560-1574 region) — the 0017 trigger `RAISE` propagates as a raw asyncpg error. The catch must branch ONLY on the trigger case and let dup/FK propagate:

```python
try:
    completion_id = await self._completions_repo.insert_completion(...)   # PB path
except <SpeedTriggerError>:   # CONFIRM exact type from migrations 0012/0017 at plan time — NOT SlowerThanPendingError
    completion_id = None      # non-PB: no core row; route to tournament-native verification
```

**Tournament side-effect inside `verify_completion` (L575-652) — D4a.** Verified shape: `check_completion_exists` (L600), `fetch_completion_for_moderation` (L604, returns user_id/code/old_time/old_verified), `update_verification` (L612), quest progress (L624-637), then `VerificationChangedEvent(completion_id, verified, verified_by, reason)` published on `api.completion.verification` (L639-651). **The event has NO map_id** (P8) — so resolve map+cycle here (you have `code`), and if the core row links a `tournament_completion_id`, call `set_tournament_verified` + `award_participation` in the same `conn`, then publish `TournamentVerificationChangedEvent`. Do NOT do this via a bot consumer.

**`attempt_tournament_auto_verify_async` (NEW, OCR variant) mirrors `attempt_auto_verify_async` (L281-412).** Copy the OCR HTTP block verbatim (L307-332): hostname switch, `aiohttp.ClientSession().post(f"http://{hostname}:8000/extract", json={image_url, code, time, names})`, `msgspec.json.decode(..., type=OcrResponse)`, three-way match (L330-332). ONLY the terminal differs (P4): on match call `verify_tournament_completion(tournament_completion_id)` instead of `verify_completion_with_pool(completion_id)` (L340); on mismatch publish the NEW tournament-completion-created event (mod review) instead of `CompletionCreatedEvent` (L361-366). Idempotency key shape mirrors L305 (`f"tournament:submission:{user_id}:{tc_id}"`).

---

### `apps/api/services/tournament_service.py` (service — remove bypass, add verify)

**Analog:** existing `submit_completion` (L497-584, to remove) + `completions_service.py` `verify_completion` (L575) for the new method.

**REMOVE the bypass `submit_completion` (L497-584).** Verified body: `fetch_cycle`→Cycle errors (L522-529); `fetch_user_completion`→`SlowerTimeError` keep-fastest gate (L531-537); `create_tournament_completion` (L541); `cross_write_to_core` (L551); `award_participation` on first completion (L573); `publish_xp_events` post-commit (L580-582). RESEARCH §D5: delete the verification-skipping path + XP-on-submit; KEEP `cross_write_to_core` for the PB path.

**`verify_tournament_completion` (NEW, D4b + D6).** No existing analog in this file — mirror `completions_service.py` `verify_completion`'s structure: acquire conn + transaction, `set_tournament_verified`, `award_participation` (idempotent — P5), then `publish_message(routing_key="api.tournament.verification.changed", data=TournamentVerificationChangedEvent(...), idempotency_key=...)`, flush deferred XP via `publish_xp_events` post-commit (existing pattern L580-582).

**DI note (RESEARCH §DI wiring + A1):** `CompletionsService.__init__(pool, state, completions_repo)` (L78) has no tournament dep; provider `provide_completions_service(state, completions_repo)` (L922). To reach tournament logic from the completion submit path, inject `TournamentService` (or `TournamentRepository` + `TournamentRewardService`) via `TYPE_CHECKING`-guarded import to avoid circular import (CLAUDE.md "Circular imports avoided via TYPE_CHECKING"). `provide_tournament_service` already exists (L629).

---

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (SDK struct/event)

**Analog:** `genjishimada_sdk/completions.py` `CompletionCreatedEvent` (L325) + `VerificationChangedEvent` (L335).

`CompletionCreatedEvent` (the RabbitMQ-event template) and `VerificationChangedEvent` are plain `msgspec.Struct`s. The existing `TournamentCompletionCreatedEvent` (this file, L441) currently carries only `completion_id, cycle_id`.

**Extend `TournamentCompletionCreatedEvent`** with `user_id, time, video, screenshot` (RESEARCH §SDK structs, recommended "extend for fewer round-trips") OR keep slim + bot fetches on receipt (matches the cycle-consumer "consumer-only" docstring in `apps/bot/extensions/tournaments.py:1-20`). **NEW `TournamentVerificationChangedEvent`:** `tournament_completion_id, cycle_id, user_id, verified, time` (+ `verified_by` only if the optional 0023 migration lands).

**`__all__` is a sorted tuple (L8-31).** Add `"TournamentVerificationChangedEvent"` keeping alphabetical order (mirror the completions.py `__all__` L10-34 convention). Event types live in the `# Event types (RabbitMQ)` section starting L399.

> **SDK is a workspace package** — after editing run `just fix`/`just sync` or API+bot get `ModuleNotFoundError: genjishimada_sdk` (project MEMORY).

---

### `apps/api/events/completions.py` + `apps/api/events/schemas.py` (in-process listener)

**Analog:** same files — `handle_ocr_verification` listener (`events/completions.py` L17-40) + `OcrVerificationRequestedEvent` (`events/schemas.py`).

The OCR listener pattern is tiny and exact:

```python
@listener("completion.ocr.requested")
async def handle_ocr_verification(event, svc, users, notifications) -> None:
    await svc.attempt_auto_verify_async(
        completion_id=event.completion_id, user_id=event.user_id, code=event.code,
        time=event.time, screenshot=event.screenshot, users=users, notifications=notifications,
    )
```

**NEW `tournament.ocr.requested`** listener mirrors this 1:1, dispatching to `svc.attempt_tournament_auto_verify_async(...)` with `tournament_completion_id` added. Add a matching `TournamentOcrVerificationRequestedEvent` to `events/schemas.py` mirroring `OcrVerificationRequestedEvent`. Listeners are auto-discovered by `apps/api/events/__init__.py` scanning for `EventListener` instances (CLAUDE.md Module Design) — no manual registration.

---

### `infra/rabbitmq/definitions.json` (config, pub-sub)

**Analog:** existing `api.tournament.cycle_started` queue + DLQ (this file, L356-373).

**Queue-naming convention is dotted, NOT a separate `.verification` segment style** — existing tournament queues are `api.tournament.cycle_started` / `api.tournament.cycle_completed`. RESEARCH §New queues names the two new ones `api.tournament.completion.created` and `api.tournament.verification.changed`. Each needs: a main queue with `x-dead-letter-exchange: ""`, `x-dead-letter-routing-key: "<name>.dlq"`, `x-queue-type: "classic"`, PLUS a standalone `<name>.dlq` queue. Copy the exact block:

```json
{
  "name": "api.tournament.cycle_started",
  "vhost": "/",
  "durable": true,
  "auto_delete": false,
  "arguments": {
    "x-dead-letter-exchange": "",
    "x-dead-letter-routing-key": "api.tournament.cycle_started.dlq",
    "x-queue-type": "classic"
  }
},
{
  "name": "api.tournament.cycle_started.dlq",
  "vhost": "/",
  "durable": true,
  "auto_delete": false,
  "arguments": { "x-queue-type": "classic" }
}
```

This is the Phase 09-03 DLQ pattern (commits `4c31fa4`/`33059e7`) — every queue gets its own DLQ so the per-queue isolated sweep cannot be poisoned. Tournament XP stays on the generic `api.xp.grant` queue — do NOT add `api.tournament.xp.grant` (RESEARCH §New queues).

---

### `apps/api/routes/v3/tournaments.py` (route/controller)

**Analog:** `routes/v3/completions.py` verify handler (`PATCH /completions/{id}/verify`) + same-file controller conventions.

**Controller conventions (this file):** `class TournamentsController(litestar.Controller)` with `tags`, `path="/tournaments"`, a `dependencies` dict of `Provide(provide_*)` (L54-63); every handler declares `opt={"required_scopes": {...}}` — `tournaments:read` (L70) or `tournaments:write` (L91); bodies use `Annotated[T, Body(title=...)]`; domain exceptions caught and re-raised as `CustomHTTPException`.

**NEW verify/reject endpoints** — `PATCH /tournaments/completions/{tournament_completion_id:int}/verify` and `/reject`, scope `tournaments:verify` (NEW scope — RESEARCH Security §; confirm bot token carries it). Mirror the `@litestar.patch(... opt={"required_scopes": {"tournaments:verify"}})` decorator + thin delegation to `tournament_service.verify_tournament_completion(...)`. Typed `:int` path param (V5 input validation).

**REMOVE the bypass submit route (L463-503):** `@litestar.post(path=".../submit", opt={"required_scopes": {"tournaments:write"}})` → `submit_completion` (L465) taking `TournamentCompletionCreateRequest`, returning `TournamentCompletionResponse`, catching `CycleNotFoundError/CycleNotActiveError/SlowerTimeError`. After SC-4 this route must 404/405.

---

### `apps/bot/extensions/tournaments.py` (bot extension, event-driven)

**Analog:** `apps/bot/extensions/completions.py` — `_process_create_submission_message` (L562) consumer + `CompletionVerificationView(ui.LayoutView)` (L299) + `CompletionsVerificationAcceptButton` (L103) / `CompletionsVerificationRejectButton` (L155).

**This file already has the right cog shape:** `TournamentHandler(BaseHandler)` (L68) registered as PUBLIC `bot.tournaments` (private `_`-prefixed attrs are skipped by `RabbitHandler`'s `dir(bot)` walk — see file docstring L1-20). `_resolve_channels` (L73) caches channels. Existing consumers use `@queue_consumer("api.tournament.cycle_started", struct_type=..., idempotent=True)` (L79).

**NEW consumer** mirrors `_process_create_submission_message` (L562-571): `@queue_consumer("api.tournament.completion.created", struct_type=TournamentCompletionCreatedEvent, idempotent=True)`, fetch details (or read from extended event), build the Accept/Reject view, send to the verification channel.

**Accept/Reject view** mirrors `CompletionVerificationView` (L299-355, a `ui.LayoutView` with `ui.Container`/`ui.Section`/`ui.MediaGallery`/`ui.ActionRow`) and the two buttons. Verified button pattern (`CompletionsVerificationAcceptButton` L103-153):

```python
class CompletionsVerificationAcceptButton(ui.Button):
    def __init__(self) -> None:
        super().__init__(style=ButtonStyle.green, label="Accept", custom_id="completions:accept")
    async def callback(self, itx: GenjiItx) -> None:
        await itx.response.defer(ephemeral=True, thinking=True)
        for c in self.view.walk_children():
            if isinstance(c, ui.Button):
                c.disabled = True
        if itx.message:
            await itx.message.edit(view=self.view)
        job_status = await self.view.bot.api.verify_completion(self.view.data.id, data=...)
        job = await poll_job_until_complete(itx.client.api, job_status.id)
```

Tournament version: `custom_id="tournament:accept"` / `"tournament:reject"` — **DISTINCT** from `"completions:accept"`/`"completions:reject"` (P3: persistent custom_ids must not collide). Callback → `self.view.bot.api.verify_tournament_completion(tc_id)` / `reject_tournament_completion(tc_id)`. Reject can reuse `RejectionReasonModal` (L84). Bot NEVER writes the DB — only API calls (CLAUDE.md; P3).

---

### `apps/bot/extensions/api_service.py` (bot client)

**Analog:** `verify_completion` (~L1080, `PATCH /completions/{id}/verify`) + `submit_completion` (~L1031).

Add `verify_tournament_completion(tc_id)` → `PATCH /tournaments/completions/{tc_id}/verify` and `reject_tournament_completion(tc_id)` → `.../reject`, mirroring the existing `verify_completion` request wrapper exactly (same auth header / job-status return shape).

---

### `apps/api/tests/services/test_tournament_verification.py` (NEW) + extensions (test)

**Analog:** `tests/services/test_tournament_service.py`, `tests/integration/test_tournaments_integration.py`.

**Conventions:** pytest-asyncio (auto), `X-PYTEST-ENABLED=1` header makes `BaseService.publish_message` skip real RabbitMQ — assert on DB/job state, not the broker (RESEARCH Test Strategy; CLAUDE.md Testing). Targeted run `uv run --directory apps/api pytest tests/services/test_tournament_verification.py -v -p no:xdist`; multi-file runs need `--no-testmon` (MEMORY).

**Wave 0 gaps (RESEARCH):** new `test_tournament_verification.py` covering SC-2 (non-PB OCR + mod verify endpoint) and SC-3 (PB propagation); fixtures — a non-PB submission needs a pre-seeded faster core completion to trip the 0017 trigger, plus a tournament-completion factory keyed to a cycle map. Rewrite submit-asserting cases in `test_tournament_service.py`, `test_completions_integration.py`, `test_tournaments_integration.py`, `test_cycle_transitions.py`, `test_tournament_rewards.py` (RESEARCH §Bypass to remove enumerates them).

Do NOT write `is True/False` assertions against `check_active_cycle_for_category` (returns `int | None`, not bool — MEMORY/Phase-4 contract). Known flakes (`test_difficulty_exact_filter`, `TestFetchMapsFilterCategory` under `-n 4`) are pre-existing, not regressions.

---

### `apps/api/tests/bot/test_tournaments_handler.py` (test, event-driven)

**Analog:** same file — existing cycle-handler tests.

Pattern (verified L96-160): a local stub `_queue_consumer(queue_name, *, struct_type, idempotent=False, **_)` returns the raw handler unwrapped (attaching `_struct_type`/`_idempotent`), so tests invoke the handler **body** with an already-decoded event. `_make_handler` does `object.__new__(TournamentHandler)` and injects `bot=SimpleNamespace(api=mock_api)` + a fake channel. `apps/api/tests/bot/conftest.py` puts `apps/bot` on `sys.path` and removes it in `finally` (commit `07e8b0d`).

Add: a test that invokes the new Accept/Reject consumer body with a `TournamentCompletionCreatedEvent`, asserting the fake channel `send` got a view, and (mocking `bot.api`) that Accept/Reject buttons call `verify_tournament_completion`/`reject_tournament_completion`.

---

## Shared Patterns

### RabbitMQ publish (idempotency-enforced)
**Source:** `apps/api/services/base.py` `IGNORE_IDEMPOTENCY` set (L28) + `publish_message` guard `if routing_key not in IGNORE_IDEMPOTENCY and not idempotency_key: raise ...` (L75).
**Apply to:** every new publish — `api.tournament.completion.created`, `api.tournament.verification.changed`. These are NOT in `IGNORE_IDEMPOTENCY`, so `publish_message(...)` MUST pass an `idempotency_key`. Mirror the completion shapes: `f"tournament:submission:{user_id}:{tc_id}"` and `f"tournament:verify:{tc_id}"` (cf. `completions_service.py` L305, L645).

### Idempotent XP grant on verification (D6)
**Source:** `tournament_reward_service.py` `award_participation` (L136) → `_grant_xp(reason_key="participation")`; ledger `claim_xp_grant` (`tournaments_repository.py:837`) does `ON CONFLICT (cycle_id,user_id,reason) DO NOTHING RETURNING id`.
**Apply to:** both verify paths (PB side-effect in `verify_completion`; non-PB `verify_tournament_completion`). Call unconditionally — never branch on "already granted" (P5). Flush deferred events post-commit via `publish_xp_events` (existing `tournament_service.py` L580-582).

### Optional connection injection + single transaction (P6)
**Source:** `BaseRepository._get_connection(conn)` — every repo method (e.g. `tournaments_repository.py` L148, L257). Service transaction: `async with self._pool.acquire() as conn, conn.transaction():` (`completions_service.py` L437, `tournament_service.py` L521).
**Apply to:** PB path must wrap core-insert + tournament-insert + FK link in one transaction; pass `conn=` through `set_tournament_verified` → `award_participation`.

### Domain → HTTP error translation
**Source:** controllers catch domain errors → `CustomHTTPException` (`routes/v3/tournaments.py`); repos translate asyncpg → `repository.exceptions` (`create_tournament_completion` L915-928).
**Apply to:** new verify endpoints + the speed-trigger catch (P7 — catch ONLY the trigger case, let dup/FK propagate; use `from e`).

### Bot never writes DB
**Source:** CLAUDE.md Architectural Constraints; completions Accept/Reject buttons call `self.view.bot.api.verify_completion` (L122, L174).
**Apply to:** tournament Accept/Reject view → API calls only.

### Persistent custom_id uniqueness (P3)
**Source:** `completions.py` `custom_id="completions:accept"` (L108) / `"completions:reject"` (L160).
**Apply to:** tournament buttons MUST use distinct `"tournament:accept"`/`"tournament:reject"`.

---

## No Analog Found

None. Every Phase 11 file maps onto an existing completion-domain or tournament-domain analog. The non-PB verification surface mirrors completions ~1:1 (queue + SDK event + bot view + verify endpoint + OCR variant); the PB path and bypass removal are in-place edits to existing tournament/completion code.

---

## Key Risks the Planner Must Resolve at Edit Time (from RESEARCH)

1. **P7 / Open Q3:** exact exception surfaced by the 0017 speed trigger from `insert_completion` — needed so D4b catches precisely (NOT `SlowerThanPendingError`). Inspect migrations `0012`/`0017`.
2. **P2 / A6:** `tournaments.completions` UNIQUE is `(cycle_id,user_id,inserted_at)` — NO `ON CONFLICT (cycle_id,user_id)` upsert is possible; keep-fastest is read-time via `fetch_leaderboard`/`fetch_user_completion`.
3. **A7:** new `tournaments:verify` scope must exist in the auth scope set + bot token grant (mirror `completions:verify`).
4. **A8:** new migration number is `0023` (bump if another lands first).
5. **P1:** re-grep all symbol definitions/line numbers before editing — they drift.

---

## Metadata

**Analog search scope:** `apps/api/{routes/v3,services,repository,events,tests,tests/bot}`, `apps/bot/extensions`, `libs/sdk/src/genjishimada_sdk`, `infra/rabbitmq`, `scripts`.
**Files scanned (read this session):** completions_service.py (submit/verify/OCR), completions_repository.py (insert_completion, update_verification), tournament_service.py (submit_completion, __init__, DI), tournaments_repository.py (create_tournament_completion, cross_write_to_core, check_active_cycle_for_category, fetch_user_completion), tournament_reward_service.py (award_participation), routes/v3/tournaments.py (controller + bypass route), bot/extensions/completions.py (Accept/Reject view + consumers + buttons), bot/extensions/tournaments.py (TournamentHandler cycle consumers), bot/extensions/_queue_registry.py (queue_consumer), bot/extensions/api_service.py (verify_completion), sdk/tournaments.py (__all__, events), sdk/completions.py (CompletionCreatedEvent, VerificationChangedEvent, __all__), events/completions.py + events/schemas.py (OCR listener), services/base.py (IGNORE_IDEMPOTENCY, publish_message), infra/rabbitmq/definitions.json (tournament queues), tests/services/test_tournament_service.py, tests/integration/test_tournaments_integration.py, tests/bot/test_tournaments_handler.py.
**Pattern extraction date:** 2026-05-31
