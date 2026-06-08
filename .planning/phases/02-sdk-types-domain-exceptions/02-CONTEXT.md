# Phase 2: SDK Types & Domain Exceptions - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Define shared msgspec Structs (request, response, and event types) in a new `tournaments.py` SDK module, and create a domain exception hierarchy in `services/exceptions/tournaments.py` for the tournament system. No API routes, no services, no repositories -- just the shared type definitions and exception classes that downstream layers import.

</domain>

<decisions>
## Implementation Decisions

### SDK Module Organization
- **D-01:** Single `tournaments.py` file in `libs/sdk/src/genjishimada_sdk/` following the one-file-per-domain pattern. Existing SDK modules (completions.py, maps.py, store.py) each cover their entire domain in one file. Tournament structs (~20-30 types) fit comfortably in this pattern.
- **D-02:** Add `tournaments.py` to the SDK `__all__` exports and verify it imports cleanly from both API and bot packages.

### Event Type Scope
- **D-03:** Define ALL tournament RabbitMQ event types upfront in the SDK module, not incrementally per phase. Struct definitions are lightweight and having them available from Phase 3 onward prevents SDK churn. Events to define:
  - `TournamentCycleStartedEvent` -- new cycle activated (consumed by bot for announcements)
  - `TournamentCycleCompletedEvent` -- cycle finalized with results (consumed by bot for results/champion transfer)
  - `TournamentCompletionCreatedEvent` -- new tournament submission (consumed by bot for Discord message)
  - `TournamentXpGrantEvent` -- XP rewards to distribute (consumed via existing `api.xp.grant` or new tournament queue)

### Response Type Granularity
- **D-04:** Follow the existing completions pattern with distinct types for distinct use cases rather than one-size-fits-all with optional fields. Types to define:
  - `TournamentConfigResponse` -- singleton config read
  - `TournamentConfigPatchRequest` -- singleton config update
  - `TournamentCategoryResponse` -- full category with XP config
  - `TournamentCategoryCreateRequest` / `TournamentCategoryPatchRequest` -- category CRUD
  - `TournamentCycleResponse` -- cycle with status, map info, timestamps
  - `TournamentLeaderboardEntryResponse` -- ranked entry (user, time, rank, verified)
  - `TournamentCompletionCreateRequest` -- submission payload
  - `TournamentCompletionResponse` -- full submission record after create
  - `TournamentStreakResponse` -- user streak data
  - `TournamentCycleResultsResponse` -- cycle results with standings (for archive/history)
- **D-05:** Use `UNSET`/`UnsetType` pattern for PATCH request fields, matching `CompletionPatchRequest` convention.

### Exception Hierarchy
- **D-06:** Follow three-tier exception pattern: one `TournamentsError(DomainError)` base class in `services/exceptions/tournaments.py`, with specific subclasses for each distinct business rule violation:
  - `CategoryNotFoundError` -- category ID doesn't exist
  - `CycleNotFoundError` -- cycle ID doesn't exist
  - `CycleNotActiveError` -- submission attempted on non-active cycle
  - `DuplicateTournamentCompletionError` -- user already submitted for this cycle (speed enforcement is per-cycle fresh slate, but duplicate check exists)
  - `CategoryLockedError` -- category modification attempted during active cycle
  - `MapNotEligibleError` -- map is on cooldown or doesn't match category difficulties
  - `NoCycleActiveError` -- operation requires an active cycle but none exists
  - `CycleAlreadyActiveError` -- attempting to start a cycle when one is already active for the category
- **D-07:** Repository exception mappings in `repository/exceptions.py` already cover `UniqueConstraintViolationError`, `ForeignKeyViolationError`, and `CheckConstraintViolationError` generically. No new repository exception types needed -- tournament repository methods will raise existing types, and the tournament service will translate constraint names to domain exceptions.

### Naming Conventions
- **D-08:** SDK struct prefix is `Tournament` (e.g., `TournamentCycleResponse`, `TournamentCompletionCreateRequest`). This avoids collision with existing `CompletionResponse`, `CompletionCreateRequest`, etc.
- **D-09:** Domain exception module at `services/exceptions/tournaments.py` with base `TournamentsError(DomainError)`.

### Claude's Discretion
- Exact field names on SDK structs -- follow existing SDK patterns (snake_case, matching DB column names where sensible)
- Struct field ordering -- required fields first, optional/defaulted fields last (msgspec convention)
- Whether to define JSONB sub-structs for `placement_xp` and `streak_xp` arrays vs using `list[dict]` -- sub-structs preferred for type safety

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing SDK Patterns
- `libs/sdk/src/genjishimada_sdk/completions.py` -- Reference for struct naming, Event/Request/Response patterns, UNSET usage, __all__ exports
- `libs/sdk/src/genjishimada_sdk/maps.py` -- Reference for Literal types, Annotated validators, shared type aliases
- `libs/sdk/src/genjishimada_sdk/store.py` -- Reference for config/store domain structs (closest to tournament config)
- `libs/sdk/src/genjishimada_sdk/__init__.py` -- Package exports that need updating

### Existing Exception Patterns
- `apps/api/services/exceptions/completions.py` -- Reference for domain exception hierarchy (base error + specific errors with context kwargs)
- `apps/api/services/exceptions/maps.py` -- Reference for exception density and naming conventions
- `apps/api/repository/exceptions.py` -- Repository exception base classes (no changes needed, just reference)
- `apps/api/utilities/errors.py` -- `DomainError` base class definition

### Database Schema (from Phase 1)
- `apps/api/migrations/0020_tournaments.sql` -- Table definitions, column types, constraints, and indexes that SDK structs must mirror
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` -- Phase 1 decisions (D-01 through D-10) that constrain type definitions

### Project Planning
- `.planning/PROJECT.md` -- Constraints section (tech stack, data integrity, bot pattern)
- `.planning/REQUIREMENTS.md` -- Full v1 requirement list with IDs
- `.planning/ROADMAP.md` -- Phase 2 success criteria (4 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `DifficultyTop` / `DifficultyAll` types from `genjishimada_sdk/difficulties.py` -- tournament categories reference these for difficulty groupings
- `OverwatchCode` / `GuideURL` annotated types from `genjishimada_sdk/maps.py` -- reuse for map code references in tournament structs
- `JobStatusResponse` from `genjishimada_sdk/internal.py` -- reuse for tournament submission job responses
- `UNSET` / `UnsetType` from `msgspec` -- standard PATCH request pattern

### Established Patterns
- SDK modules define `__all__` tuple at top for explicit public API
- Structs use `kw_only=True` where all fields have defaults (see `CompletionModerateRequest`)
- Events are minimal structs with only the IDs/data needed for the consumer
- Response structs mirror DB columns closely but use Python types (float for numeric, bool for boolean, dt.datetime for timestamptz)
- JSONB columns can map to typed sub-structs for validation (e.g., `placement_xp` -> `list[PlacementXpTier]`)

### Integration Points
- `libs/sdk/src/genjishimada_sdk/__init__.py` needs import of new `tournaments` module
- Domain exceptions register at `apps/api/services/exceptions/tournaments.py` (new file)
- No changes to `apps/api/services/exceptions/__init__.py` needed (no barrel file for exceptions)

</code_context>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 2-SDK Types & Domain Exceptions*
*Context gathered: 2026-05-29*
