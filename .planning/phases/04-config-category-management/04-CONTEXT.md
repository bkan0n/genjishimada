# Phase 4: Config & Category Management - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the service and controller layer for tournament configuration and category CRUD. Admins can GET/PATCH the global config singleton and create/list/update/delete difficulty-based tournament categories through REST API endpoints. Category mutations are rejected when an active cycle exists. Non-admin requests are rejected by scope guard.

</domain>

<decisions>
## Implementation Decisions

### Auth Scopes
- **D-01:** Tournament endpoints use `tournaments:read` for GET operations and `tournaments:write` for all mutations (POST/PATCH/DELETE). Follows the existing `maps:read`/`maps:write` and `store:read`/`store:write` pattern. Superusers bypass scope checks as usual.

### Route Structure
- **D-02:** Single `TournamentsController(Controller)` at path `/tournaments` in `apps/api/routes/v3/tournaments.py`. Config endpoints under `/tournaments/config`, category endpoints under `/tournaments/categories` and `/tournaments/categories/{category_id}`. Matches single-controller-per-domain pattern (StoreController at `/store`).
- **D-03:** Endpoints to implement:
  - `GET /tournaments/config` — Read config singleton
  - `PATCH /tournaments/config` — Update config fields
  - `POST /tournaments/categories` — Create category
  - `GET /tournaments/categories` — List all categories
  - `GET /tournaments/categories/{category_id}` — Get single category
  - `PATCH /tournaments/categories/{category_id}` — Update category
  - `DELETE /tournaments/categories/{category_id}` — Delete category

### Service Class Design
- **D-04:** Single `TournamentService(BaseService)` in `apps/api/services/tournament_service.py`. Receives `Pool`, `State`, and `TournamentRepository` via constructor. Provider function `provide_tournament_service(state, tournament_repo)` at file bottom. One service per domain matching existing pattern.

### Category Mutation Safety
- **D-05:** For category update and delete, the service acquires a pool connection, calls `check_active_cycle_for_category(category_id)` within the same connection, and raises `CategoryLockedError(category_id, cycle_id)` if an active cycle exists. Only then does it proceed with the mutation. This prevents TOCTOU races by using the same connection (not necessarily a serializable transaction — the advisory lock in Phase 7 handles concurrent transitions).
- **D-06:** Category creation does NOT require an active cycle check — new categories start without cycles.
- **D-07:** Category delete is a hard DELETE. The active cycle guard prevents deletion of categories with running cycles. Categories with only completed/no cycles can be safely deleted (ON DELETE CASCADE handles orphaned cycle records if needed, or FK constraints prevent deletion if cycles reference the category).

### Config PATCH Handling
- **D-08:** Service iterates `TournamentConfigPatchRequest` fields, builds a dict of non-UNSET values, passes to `repository.update_config(updates)`. Matches existing store config PATCH pattern in `store_service.py`.
- **D-09:** Config row is assumed to always exist — seeded by migration `0020_tournaments.sql` (`INSERT INTO tournaments.config`). No empty-config fallback needed.

### Error-to-HTTP Mapping
- **D-10:** Controller catches domain exceptions and maps to HTTP status codes:
  - `CategoryNotFoundError` -> 404 Not Found
  - `CategoryLockedError` -> 409 Conflict (category cannot be modified during active cycle)
  - Category name uniqueness violation -> Service catches `UniqueConstraintViolationError` from repo, translates to a domain exception (e.g., `CategoryNameExistsError`), controller maps to 409 Conflict
- **D-11:** A new `CategoryNameExistsError(TournamentsError)` should be added to `services/exceptions/tournaments.py` for the category name uniqueness case. The repo raises generic `UniqueConstraintViolationError`; the service translates it based on `constraint_name`.

### Claude's Discretion
- Exact method signatures on the service (parameter names, return types) — follow existing service patterns
- Whether `list_categories` returns all categories or supports optional `is_active` filter — either approach is fine, filter is a bonus
- Controller docstrings and summary/description text — follow existing style
- Whether to add `tags = ["Tournaments"]` or `tags = ["Tournament"]` on the controller — pick whichever reads better

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Service+Controller Patterns
- `apps/api/services/store_service.py` — Reference for config singleton PATCH pattern, service class structure with repository injection
- `apps/api/routes/v3/store.py` — Reference for controller with config + CRUD endpoints, scope-based auth, exception-to-HTTP mapping
- `apps/api/services/base.py` — `BaseService` base class with `_pool`, `_state`, `publish_message()`
- `apps/api/services/maps_service.py` — Reference for service with repository injection, transaction patterns
- `apps/api/routes/v3/maps.py` — Reference for CRUD controller with `maps:read`/`maps:write` scopes

### Tournament Domain (from prior phases)
- `apps/api/repository/tournaments_repository.py` — All repository methods this service wraps (fetch_config, update_config, create_category, fetch_categories, update_category, delete_category, check_active_cycle_for_category)
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — All request/response/event Structs (TournamentConfigResponse, TournamentConfigPatchRequest, TournamentCategoryCreateRequest, TournamentCategoryPatchRequest, TournamentCategoryResponse)
- `apps/api/services/exceptions/tournaments.py` — Domain exceptions (CategoryNotFoundError, CategoryLockedError, TournamentsError base)
- `apps/api/migrations/0020_tournaments.sql` — Schema definition, config seed row, constraint names

### Framework Patterns
- `apps/api/routes/v3/__init__.py` — Auto-discovers Controller subclasses (no manual registration needed)
- `apps/api/middleware/guards.py` — Scope guard implementation (required_scopes opt)
- `apps/api/repository/exceptions.py` — UniqueConstraintViolationError, ForeignKeyViolationError, extract_constraint_name()
- `apps/api/utilities/errors.py` — DomainError base class, CustomHTTPException

### Prior Phase Context
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` — D-05/D-06 (XP per-category, global config only blacklist_weeks), D-08 (singleton CHECK pattern)
- `.planning/phases/02-sdk-types-domain-exceptions/02-CONTEXT.md` — D-04 (distinct types per use case), D-05 (UNSET pattern for PATCH), D-06/D-07 (three-tier exception pattern)
- `.planning/phases/03-repository-layer/03-CONTEXT.md` — D-01/D-02 (single repo file, provider), D-08/D-09 (all repo methods exist), D-10/D-11 (exception handling at repo level)

### Project Planning
- `.planning/PROJECT.md` — Constraints section (no ORM, bot never writes to DB, existing patterns)
- `.planning/REQUIREMENTS.md` — CYCLE-02, CYCLE-03, CYCLE-08, ADM-01, ADM-02 (requirements this phase covers)
- `.planning/ROADMAP.md` — Phase 4 success criteria (4 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseService` from `services/base.py` — base class with pool, state, and publish_message()
- `TournamentRepository` from `repository/tournaments_repository.py` — all data access methods ready to be wrapped
- `CustomHTTPException` from `utilities/errors.py` — standard HTTP error response
- `Provide` from `litestar.di` — dependency injection helper for controller dependencies dict
- Existing domain exceptions in `services/exceptions/tournaments.py` — CategoryNotFoundError, CategoryLockedError already defined

### Established Patterns
- Controller declares `dependencies` dict mapping DI names to `Provide(provide_*)` factories
- Service receives `Pool`, `State`, and repository via constructor; provider function at file bottom
- PATCH operations: iterate struct fields, skip UNSET, build update dict, pass to repo
- Transaction pattern: `async with self._pool.acquire() as conn, conn.transaction():`
- Controller catches domain exceptions in try/except, raises CustomHTTPException with status code
- Route auto-discovery: any Controller subclass in `routes/v3/*.py` is auto-mounted

### Integration Points
- `apps/api/routes/v3/tournaments.py` — new file, auto-discovered by `routes/v3/__init__.py`
- `apps/api/services/tournament_service.py` — new file for business logic
- `apps/api/services/exceptions/tournaments.py` — may need `CategoryNameExistsError` added
- No RabbitMQ publishing needed in this phase — config/category CRUD is synchronous

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Config & Category Management*
*Context gathered: 2026-05-29*
