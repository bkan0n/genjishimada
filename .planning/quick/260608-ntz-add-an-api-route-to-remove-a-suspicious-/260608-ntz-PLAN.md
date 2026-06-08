---
phase: quick
plan: 260608-ntz
type: execute
wave: 1
depends_on: []
files_modified:
  - libs/sdk/src/genjishimada_sdk/completions.py
  - apps/api/repository/completions_repository.py
  - apps/api/services/completions_service.py
  - apps/api/routes/v3/completions.py
  - apps/bot/extensions/api_service.py
autonomous: true
requirements: [QUICK-REMOVE-SUSPICIOUS-FLAG]
must_haves:
  truths:
    - "A DELETE /completions/suspicious request removes the suspicious flag for the completion identified by message_id or verification_id"
    - "Requesting removal for a completion that has no flag returns a clean success (no flag deleted) rather than a 500"
    - "The removal route mirrors the existing POST /suspicious route exactly (same controller, same identifier model, same exception translation style)"
  artifacts:
    - path: "libs/sdk/src/genjishimada_sdk/completions.py"
      provides: "SuspiciousCompletionDeleteRequest msgspec struct"
      contains: "class SuspiciousCompletionDeleteRequest"
    - path: "apps/api/repository/completions_repository.py"
      provides: "delete_suspicious_flag_by_message method (delete by message_id/verification_id)"
      contains: "delete_suspicious_flag_by_message"
    - path: "apps/api/services/completions_service.py"
      provides: "remove_suspicious_flags service method"
      contains: "remove_suspicious_flags"
    - path: "apps/api/routes/v3/completions.py"
      provides: "DELETE /suspicious route handler"
      contains: "delete_suspicious_flags"
  key_links:
    - from: "apps/api/routes/v3/completions.py"
      to: "CompletionsService.remove_suspicious_flags"
      via: "svc.remove_suspicious_flags(data)"
      pattern: "svc\\.remove_suspicious_flags"
    - from: "apps/api/services/completions_service.py"
      to: "CompletionsRepository.delete_suspicious_flag_by_message"
      via: "repo method call"
      pattern: "delete_suspicious_flag_by_message"
---

<objective>
Add an API route to REMOVE a suspicious flag from a completion, mirroring the existing add route (`POST /completions/suspicious`) exactly.

Purpose: The tournament verification system (commit 5bf0d7a) added the ability to flag a completion as suspicious via `POST /completions/suspicious` using `message_id`/`verification_id`. There is no standalone REST route to remove a flag by the same identifier model — the only removal path today is the combined `CompletionModerateRequest` (`unmark_suspicious`) flow. This adds a symmetric `DELETE /completions/suspicious` route.

Output: New SDK request struct, repository delete-by-message method, service method, DELETE route handler, and bot API client method.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Existing ADD-route conventions the removal route MUST mirror. Use these directly. -->

The existing ADD route resolves a completion from message_id OR verification_id (NOT completion_id).
SuspiciousCompletionCreateRequest (libs/sdk/src/genjishimada_sdk/completions.py:361):
```python
class SuspiciousCompletionCreateRequest(Struct):
    context: str
    flag_type: SuspiciousFlag
    flagged_by: int
    message_id: int | None = None
    verification_id: int | None = None
```

Repository insert (apps/api/repository/completions_repository.py:1736) resolves completion via CTE:
```sql
WITH message_to_completion_id AS (
  SELECT id FROM core.completions
  WHERE ($1::bigint IS NOT NULL AND message_id = $1::bigint)
     OR ($1::bigint IS NULL     AND verification_id = $2::bigint)
  LIMIT 1
)
```

Existing delete-by-completion-id method (apps/api/repository/completions_repository.py:1996) — used only by the moderate flow, returns deleted count:
```python
async def delete_suspicious_flag(self, completion_id: int, *, conn=None) -> int
```

Controller route (apps/api/routes/v3/completions.py:229) — note: NO explicit required_scopes opt (relies on global guard):
```python
@post(path="/suspicious", summary="Set Suspicious Flag", ...)
async def set_suspicious_flags(self, svc, data: SuspiciousCompletionCreateRequest) -> None:
    if not data.message_id and not data.verification_id:
        raise CustomHTTPException(detail="One of message_id or verification_id must be used.", status_code=HTTP_400_BAD_REQUEST)
    return await svc.set_suspicious_flags(data)
```

Service (apps/api/services/completions_service.py:1208) translates repo exceptions to domain exceptions (UniqueConstraintViolationError -> DuplicateFlagError, ForeignKeyViolationError -> CompletionNotFoundError).

Bot client (apps/bot/extensions/api_service.py:1307) uses `Route("POST", "/completions/suspicious")` and `self._request(...)`.

`delete` is NOT yet imported in the controller — it imports `get, patch, post, put` from litestar (line 27).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add SDK request struct + repository delete-by-message method</name>
  <files>libs/sdk/src/genjishimada_sdk/completions.py, apps/api/repository/completions_repository.py</files>
  <action>
In libs/sdk/src/genjishimada_sdk/completions.py: add a new `SuspiciousCompletionDeleteRequest(Struct)` immediately after `SuspiciousCompletionCreateRequest` (around line 377). Fields: `message_id: int | None = None`, `verification_id: int | None = None`. Add a Google-style docstring describing it as the payload for removing a suspicious flag, identified by either message_id or verification_id. Add `"SuspiciousCompletionDeleteRequest"` to the `__all__` list near the top (alongside the existing `"SuspiciousCompletionCreateRequest"` entry, keeping alphabetical/existing ordering consistent with neighbors).

In apps/api/repository/completions_repository.py: add a new method `delete_suspicious_flag_by_message` placed right after the existing `delete_suspicious_flag` method (around line 2018). Signature mirrors the insert's identifier model:
`async def delete_suspicious_flag_by_message(self, message_id: int | None, verification_id: int | None, *, conn: Connection | None = None) -> int`.
Use `_conn = self._get_connection(conn)`. Resolve the completion id with the SAME CTE shape used by `insert_suspicious_flag` (lines 1757-1768) — a `message_to_completion_id` CTE matching message_id OR verification_id — then DELETE from `users.suspicious_flags WHERE completion_id IN (SELECT id FROM message_to_completion_id)`. Use `_conn.execute(...)` and parse the returned status tag (e.g. `result.split()[-1]`) to return the number of rows deleted as `int`, returning 0 when nothing matched. Do NOT add try/except for constraint violations — deletion does not violate unique/FK constraints and missing rows must return 0, not error (per CLAUDE.md "let exceptions propagate" guidance). Add a Google-style docstring (Args + Returns).
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just lint-sdk && uv run --package genjishimada-api python -c "import ast,sys; src=open('apps/api/repository/completions_repository.py').read(); ast.parse(src); sys.exit(0 if 'delete_suspicious_flag_by_message' in src else 1)"</automated>
  </verify>
  <done>SuspiciousCompletionDeleteRequest exists in SDK and is exported in __all__; delete_suspicious_flag_by_message exists in the repository and parses cleanly; lint-sdk passes.</done>
</task>

<task type="auto">
  <name>Task 2: Add service method + DELETE controller route</name>
  <files>apps/api/services/completions_service.py, apps/api/routes/v3/completions.py</files>
  <action>
In apps/api/services/completions_service.py: import `SuspiciousCompletionDeleteRequest` in the existing genjishimada_sdk.completions import block (near line 28-29 where `SuspiciousCompletionCreateRequest`/`SuspiciousCompletionResponse` are imported). Add an `async def remove_suspicious_flags(self, data: SuspiciousCompletionDeleteRequest) -> int` method directly after `set_suspicious_flags` (around line 1226). It calls `await self._completions_repo.delete_suspicious_flag_by_message(message_id=data.message_id, verification_id=data.verification_id)` and returns the deleted count. Google-style docstring (Returns: number of flags removed). No exception translation needed (deletion of a non-existent flag returns 0, matching the moderate flow's `unmark_suspicious` behavior at lines 1406-1411).

In apps/api/routes/v3/completions.py:
1. Add `delete` to the litestar import on line 27 (`from litestar import Controller, Request, Response, delete, get, patch, post, put`).
2. Add `SuspiciousCompletionDeleteRequest` to the genjishimada_sdk.completions import block (lines 8-23).
3. Add a `delete_suspicious_flags` route handler immediately after `set_suspicious_flags` (after line 242). Use `@delete(path="/suspicious", summary="Remove Suspicious Flag", description="Remove an existing suspicious flag from a completion.", status_code=200)` (explicit 200 so a body/return value is allowed; default litestar DELETE is 204 No Content). Handler signature: `async def delete_suspicious_flags(self, svc: CompletionsService, data: SuspiciousCompletionDeleteRequest) -> int:`. Mirror the add route's identifier guard exactly: if `not data.message_id and not data.verification_id`, raise `CustomHTTPException(detail="One of message_id or verification_id must be used.", status_code=HTTP_400_BAD_REQUEST)`. Then `return await svc.remove_suspicious_flags(data)`. Do NOT add `opt={"required_scopes": ...}` — the sibling `set_suspicious_flags` route has none, so the removal route matches it.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just lint-api</automated>
  </verify>
  <done>remove_suspicious_flags service method exists; DELETE /suspicious route handler exists with the same identifier guard as the add route and uses status_code 200; lint-api (format + lint + typecheck) passes.</done>
</task>

<task type="auto">
  <name>Task 3: Add bot API client method + integration test</name>
  <files>apps/bot/extensions/api_service.py, apps/api/tests/integration/test_completions_integration.py</files>
  <action>
In apps/bot/extensions/api_service.py: import `SuspiciousCompletionDeleteRequest` in the existing genjishimada_sdk.completions import block (near line 38). Add a `remove_suspicious_flags` method directly after `set_suspicious_flags` (after line 1318), mirroring it: `def remove_suspicious_flags(self, data: SuspiciousCompletionDeleteRequest) -> Response[...]:` using `r = Route("DELETE", "/completions/suspicious")` and `return self._request(r, ...)`. Match the exact `_request` call shape and return-type annotation style used by `set_suspicious_flags` (inspect lines 1307-1318 and reuse the same pattern; pass the encoded `data` the same way the add method does). Google-style docstring.

In apps/api/tests/integration/test_completions_integration.py: add an async test that (1) creates a completion + suspicious flag via the existing fixtures/helpers used by the current suspicious-flag tests in this file (search for the existing `suspicious` test setup to reuse fixtures), (2) issues `DELETE /completions/suspicious` (use the test client used elsewhere in this file) with a `message_id` or `verification_id` JSON body, (3) asserts a 200 response and that the deleted count is 1, and (4) asserts a follow-up GET `/completions/suspicious?user_id=...` no longer returns the flag. Also add a case asserting that deleting when no flag exists returns 200 with count 0. Follow the existing test conventions in this file (test files are exempt from lint, so style is flexible — match neighboring tests).
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --package genjishimada-api pytest apps/api/tests/integration/test_completions_integration.py -k suspicious -x -q</automated>
  </verify>
  <done>Bot client has remove_suspicious_flags using DELETE /completions/suspicious; integration test for removal passes (both the happy path and the no-flag count-0 case).</done>
</task>

</tasks>

<verification>
- `just lint-all` passes (sdk + api + bot formatting, lint, typecheck).
- `uv run --package genjishimada-api pytest apps/api/tests/integration/test_completions_integration.py -k suspicious -q` passes.
- Manual: with API running, `curl -X DELETE http://localhost:8000/api/v3/content/.../completions/suspicious` (correct prefix per app config) with `{"message_id": <id>}` returns 200 and removes the flag; the matching GET no longer lists it.
</verification>

<success_criteria>
- DELETE /completions/suspicious route exists, mirrors POST /suspicious (same controller, same message_id/verification_id identifier model, same 400 guard, same lack of explicit scopes).
- Removing a non-existent flag returns 200 with count 0 (no 500, no error) — consistent with the moderate flow's unmark behavior.
- New SDK struct, repo method, service method, and bot client method all follow Genji's three-layer + msgspec conventions.
- No RabbitMQ event added (the add route publishes none; removal stays symmetric).
</success_criteria>

<output>
Create `.planning/quick/260608-ntz-add-an-api-route-to-remove-a-suspicious-/260608-ntz-SUMMARY.md` when done.
</output>
