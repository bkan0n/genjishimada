---
phase: quick
plan: 260608-ntz
subsystem: completions
tags: [api, completions, suspicious-flags, moderation]
requires:
  - "POST /completions/suspicious (commit 5bf0d7a)"
provides:
  - "DELETE /completions/suspicious route"
  - "SuspiciousCompletionDeleteRequest SDK struct"
  - "CompletionsRepository.delete_suspicious_flag_by_message"
  - "CompletionsService.remove_suspicious_flags"
  - "APIService.remove_suspicious_flags bot client"
affects:
  - libs/sdk/src/genjishimada_sdk/completions.py
  - apps/api/repository/completions_repository.py
  - apps/api/services/completions_service.py
  - apps/api/routes/v3/completions.py
  - apps/bot/extensions/api_service.py
  - apps/api/tests/integration/test_completions_integration.py
tech-stack:
  added: []
  patterns: [three-layer-controller-service-repository, msgspec-structs, asyncpg-cte-identifier-resolution]
key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/completions.py
    - apps/api/repository/completions_repository.py
    - apps/api/services/completions_service.py
    - apps/api/routes/v3/completions.py
    - apps/bot/extensions/api_service.py
    - apps/api/tests/integration/test_completions_integration.py
decisions:
  - "Mirrored POST /suspicious exactly: same controller, same message_id/verification_id identifier model, same 400 guard, no explicit required_scopes."
  - "DELETE route uses status_code=200 (not default 204) so the deleted-flag count can be returned in the body."
  - "Repository delete returns 0 for a non-existent flag (no try/except) — deletion never violates unique/FK constraints, matching the moderate-flow unmark behavior."
metrics:
  duration: ~30m
  completed: 2026-06-08
---

# Quick Task 260608-ntz: Add API Route to Remove a Suspicious Flag Summary

Adds a symmetric `DELETE /completions/suspicious` route that removes a suspicious flag identified by `message_id`/`verification_id`, mirroring the existing `POST /completions/suspicious` add route across all four layers (SDK struct, repository, service, controller) plus a bot API client method.

## What Was Built

- **SDK** (`libs/sdk/src/genjishimada_sdk/completions.py`): `SuspiciousCompletionDeleteRequest(Struct)` with optional `message_id`/`verification_id`, exported in `__all__`.
- **Repository** (`apps/api/repository/completions_repository.py`): `delete_suspicious_flag_by_message(message_id, verification_id, *, conn=None) -> int`. Resolves the completion id via the SAME `message_to_completion_id` CTE used by `insert_suspicious_flag`, then `DELETE FROM users.suspicious_flags WHERE completion_id IN (...)`. Parses the asyncpg status tag (`result.split()[-1]`) to return the deleted-row count; returns 0 when nothing matched. No constraint-violation try/except (per CLAUDE.md "let exceptions propagate").
- **Service** (`apps/api/services/completions_service.py`): `remove_suspicious_flags(data) -> int` delegating to the repo method. No exception translation (delete-of-nonexistent returns 0, consistent with the moderate flow's `unmark_suspicious`).
- **Controller** (`apps/api/routes/v3/completions.py`): added `delete` to the litestar import, imported the new struct, and added a `delete_suspicious_flags` handler with `@delete(path="/suspicious", status_code=200)` and the identical "one of message_id or verification_id must be used" 400 guard. No explicit `required_scopes` (matches the sibling add route).
- **Bot client** (`apps/bot/extensions/api_service.py`): `remove_suspicious_flags(data)` using `Route("DELETE", "/completions/suspicious")` and `self._request(r, data=data)`, mirroring `set_suspicious_flags`.
- **Tests** (`apps/api/tests/integration/test_completions_integration.py`): `TestRemoveSuspiciousFlag` with happy-path removal (asserts 200 + count 1 + flag no longer listed via GET), no-flag case (200 + count 0), and missing-identifier guard (400).

## Verification

- `just lint-all` (sdk + api + bot format/lint/typecheck): all clean, 0 errors.
- `uv run --package genjishimada-api pytest apps/api/tests/integration/test_completions_integration.py -k suspicious -q`: **6 passed** (3 pre-existing + 3 new).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Integration test must set `message_id` on the completion row before flagging**
- **Found during:** Task 3
- **Issue:** The plan suggested reusing existing fixtures/helpers to create a completion + suspicious flag. In practice, `POST /completions/` creates the completion with `message_id = NULL` (message_id is attached later during verification). Because `POST /completions/suspicious` resolves the completion by `message_id` via `INSERT ... SELECT`, flagging a freshly-submitted completion silently inserts zero rows (the SELECT matches nothing — no FK error), so the GET listed no flag and the removal could not be exercised end-to-end.
- **Fix:** Each test acquires `asyncpg_pool` and runs `UPDATE core.completions SET message_id=$1 WHERE id=$2` after submission (the same field verification would populate), so the add/remove identifier model resolves correctly. This is the minimal, realistic state needed; it does not change any production code.
- **Files modified:** apps/api/tests/integration/test_completions_integration.py
- **Commit:** 66c0b11

## Commits

- `da91d30` feat(quick-260608-ntz): add SuspiciousCompletionDeleteRequest struct and delete-by-message repo method
- `d48d8f9` feat(quick-260608-ntz): add DELETE /completions/suspicious route and service method
- `66c0b11` feat(quick-260608-ntz): add bot remove_suspicious_flags client + integration tests

## Self-Check: PASSED
