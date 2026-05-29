# Phase 4: Config & Category Management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 04-Config & Category Management
**Areas discussed:** Auth scopes, Route path structure, Service class design, Category mutation safety, Config PATCH handling, Error-to-HTTP mapping
**Mode:** --auto (all decisions auto-selected)

---

## Auth Scopes

| Option | Description | Selected |
|--------|-------------|----------|
| tournaments:read / tournaments:write | Follows existing maps:read/maps:write pattern | [auto] |
| tournaments:admin (single scope) | All tournament operations under one scope | |
| tournaments:config + tournaments:categories | Separate scopes per sub-resource | |

**User's choice:** [auto] tournaments:read / tournaments:write (recommended default)
**Notes:** Matches existing codebase convention. Superusers bypass all scope checks.

---

## Route Path Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single TournamentsController at /tournaments | Config and categories as sub-paths, matches StoreController pattern | [auto] |
| Separate TournamentConfigController + TournamentCategoriesController | Split controllers per resource | |
| Nested under /admin/tournaments | Admin-specific prefix | |

**User's choice:** [auto] Single TournamentsController (recommended default)
**Notes:** Consistent with single-controller-per-domain pattern. Auto-discovered by routes/v3/__init__.py.

---

## Service Class Design

| Option | Description | Selected |
|--------|-------------|----------|
| Single TournamentService | One service covering config + categories, matches one-per-domain pattern | [auto] |
| TournamentConfigService + TournamentCategoryService | Split services per concern | |

**User's choice:** [auto] Single TournamentService (recommended default)
**Notes:** Phase scope is small enough for one service. Future phases add methods to the same service.

---

## Category Mutation Safety

| Option | Description | Selected |
|--------|-------------|----------|
| Check-then-act in same connection | Acquire conn, check active cycle, raise if locked, then mutate | [auto] |
| Serializable transaction isolation | Full serializable for TOCTOU prevention | |
| Database-level trigger/constraint | Let Postgres enforce the lock rule | |

**User's choice:** [auto] Check-then-act in same connection (recommended default)
**Notes:** Same connection avoids most races. Phase 7's advisory lock handles concurrent transition edge cases.

---

## Config PATCH Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Iterate UNSET fields, build dict | Matches store_service.py pattern | [auto] |
| Pass struct directly to repo | Repo handles UNSET logic | |

**User's choice:** [auto] Iterate UNSET fields, build dict (recommended default)
**Notes:** Config row seeded by migration. Service-level UNSET handling matches existing store pattern.

---

## Error-to-HTTP Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Three-tier with specific domain exceptions | CategoryNotFoundError->404, CategoryLockedError->409, name duplicate->409 | [auto] |
| Generic error handler decorator | Use handle_db_exceptions (legacy pattern) | |

**User's choice:** [auto] Three-tier with specific domain exceptions (recommended default)
**Notes:** Legacy decorator is an anti-pattern. New CategoryNameExistsError needed in exceptions module.

---

## Claude's Discretion

- Exact service method signatures and return types
- Whether list_categories supports optional is_active filter
- Controller docstrings and summary/description text
- Controller tags naming ("Tournaments" vs "Tournament")

## Deferred Ideas

None — discussion stayed within phase scope.
