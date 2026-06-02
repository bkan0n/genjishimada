# Phase 2: SDK Types & Domain Exceptions - Research

**Researched:** 2026-05-29
**Domain:** msgspec Struct definitions, domain exception hierarchy, shared type contract
**Confidence:** HIGH

## Summary

Phase 2 is a pure type-definition phase -- no runtime behavior, no database access, no API routes. It creates two artifacts: (1) a `tournaments.py` module in the SDK with ~25 msgspec Structs covering request, response, and event types that mirror the Phase 1 database schema, and (2) a `tournaments.py` module in the API's `services/exceptions/` directory with domain exception classes.

The codebase has extremely well-established patterns for both artifacts. Every existing domain (completions, maps, store, xp) follows the same structural template: `__all__` tuple at top, Google-style docstrings with `Attributes:` sections, required fields first then defaulted fields, `UNSET`/`UnsetType` for PATCH requests, `kw_only=True` on fully-defaulted PATCH structs. The exception hierarchy is equally standardized: one `{Domain}Error(DomainError)` base per domain, specific subclasses with `__init__` accepting context parameters, Google-style docstrings.

One naming collision was discovered: `CategoryNotFoundError` already exists in `services/exceptions/content.py` and is exported from the exceptions `__init__.py`. The tournament domain's version must be either prefixed (e.g., `TournamentCategoryNotFoundError`) or aliased on import. The existing codebase already handles this pattern with `MapNotFoundError` which exists in both `completions.py` and `maps.py` and is aliased as `CompletionsMapNotFoundError` in the barrel `__init__.py`.

**Primary recommendation:** Follow existing patterns exactly. The SDK module is a single `tournaments.py` file with typed sub-structs for JSONB columns (`PlacementXpTier`, `StreakXpTier`). Domain exceptions use the `TournamentCategoryNotFoundError` prefixed naming to avoid collision with the existing `content.CategoryNotFoundError`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single `tournaments.py` file in `libs/sdk/src/genjishimada_sdk/` following the one-file-per-domain pattern
- **D-02:** Add `tournaments.py` to the SDK `__all__` exports and verify it imports cleanly from both API and bot packages
- **D-03:** Define ALL tournament RabbitMQ event types upfront in the SDK module (TournamentCycleStartedEvent, TournamentCycleCompletedEvent, TournamentCompletionCreatedEvent, TournamentXpGrantEvent)
- **D-04:** Follow the existing completions pattern with distinct types for distinct use cases. Types to define: TournamentConfigResponse, TournamentConfigPatchRequest, TournamentCategoryResponse, TournamentCategoryCreateRequest, TournamentCategoryPatchRequest, TournamentCycleResponse, TournamentLeaderboardEntryResponse, TournamentCompletionCreateRequest, TournamentCompletionResponse, TournamentStreakResponse, TournamentCycleResultsResponse
- **D-05:** Use `UNSET`/`UnsetType` pattern for PATCH request fields, matching `CompletionPatchRequest` convention
- **D-06:** Three-tier exception pattern: one `TournamentsError(DomainError)` base class in `services/exceptions/tournaments.py`, with specific subclasses: CategoryNotFoundError, CycleNotFoundError, CycleNotActiveError, DuplicateTournamentCompletionError, CategoryLockedError, MapNotEligibleError, NoCycleActiveError, CycleAlreadyActiveError
- **D-07:** No new repository exception types needed -- existing `UniqueConstraintViolationError`, `ForeignKeyViolationError`, `CheckConstraintViolationError` cover tournament needs
- **D-08:** SDK struct prefix is `Tournament` (e.g., `TournamentCycleResponse`)
- **D-09:** Domain exception module at `services/exceptions/tournaments.py` with base `TournamentsError(DomainError)`

### Claude's Discretion
- Exact field names on SDK structs -- follow existing SDK patterns (snake_case, matching DB column names where sensible)
- Struct field ordering -- required fields first, optional/defaulted fields last (msgspec convention)
- Whether to define JSONB sub-structs for `placement_xp` and `streak_xp` arrays vs using `list[dict]` -- sub-structs preferred for type safety

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SDK type definitions | Shared library (libs/sdk) | -- | Types are imported by both API and bot; must be in the shared package |
| Domain exceptions | API service layer | -- | Exceptions are raised by API services and caught by API controllers; bot never uses them |
| Repository exceptions | API repository layer | -- | Already generic; no new types needed per D-07 |
| SDK `__init__.py` update | Shared library (libs/sdk) | -- | Package-level export for the new module |
| Exceptions `__init__.py` update | API service layer | -- | Barrel file re-exports for import convenience |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| msgspec | 0.20.0 (installed) | Struct definitions, UNSET/UnsetType, Meta validators | [VERIFIED: `python3 -c "import msgspec; print(msgspec.__version__)"` returns 0.20.0] Already the project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing (stdlib) | Python 3.13 | Literal, Annotated, TYPE_CHECKING | Type annotations for cycle_frequency, status literals |
| datetime (stdlib) | Python 3.13 | dt.datetime for timestamp fields | Response structs with timestamptz columns |

### Alternatives Considered
None -- this phase uses only what is already in the project. No new packages needed.

**Installation:**
No new packages required. All dependencies (`msgspec>=0.19.0`) are already in `libs/sdk/pyproject.toml`.

## Architecture Patterns

### System Architecture Diagram

```
libs/sdk/src/genjishimada_sdk/tournaments.py
    |
    |-- Imports from: difficulties.py (DifficultyTop)
    |                  maps.py (OverwatchCode, GuideURL, OverwatchMap)
    |                  internal.py (JobStatusResponse)
    |
    +-- Consumed by: apps/api (repository, service, controller layers)
    |                 apps/bot (queue consumers, API response handling)
    |
apps/api/services/exceptions/tournaments.py
    |
    |-- Imports from: utilities/errors.py (DomainError)
    |
    +-- Consumed by: apps/api/services/tournaments_service.py (Phase 4+)
    |                 apps/api/routes/v3/tournaments.py (Phase 4+)
    |
    +-- Registered in: apps/api/services/exceptions/__init__.py (barrel exports)
```

### Recommended Project Structure

```
libs/sdk/src/genjishimada_sdk/
    tournaments.py               # NEW: ~25 msgspec Structs

apps/api/services/exceptions/
    tournaments.py               # NEW: TournamentsError + 8 specific exceptions
    __init__.py                  # MODIFIED: add tournament exception imports
```

### Pattern 1: SDK Module Structure
**What:** Every SDK domain module follows a rigid template: `__all__` tuple, imports from sibling modules, class definitions with Google-style docstrings.
**When to use:** Always when creating a new SDK module.
**Example:**
```python
# Source: libs/sdk/src/genjishimada_sdk/completions.py (verified codebase pattern)
import datetime as dt
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

from .difficulties import DifficultyTop
from .maps import GuideURL, OverwatchCode

__all__ = (
    "TournamentConfigResponse",
    "TournamentCategoryResponse",
    # ... all public names
)


class TournamentConfigResponse(Struct):
    """Tournament global configuration.

    Attributes:
        blacklist_weeks: Number of weeks a map is excluded after use.
        created_at: When the config was created.
        updated_at: When the config was last updated.
    """

    blacklist_weeks: int
    created_at: dt.datetime
    updated_at: dt.datetime
```

### Pattern 2: PATCH Request with UNSET
**What:** PATCH request structs use `UNSET`/`UnsetType` to distinguish "not provided" from "set to null".
**When to use:** Any PATCH/partial-update endpoint.
**Example:**
```python
# Source: libs/sdk/src/genjishimada_sdk/completions.py lines 238-255 (verified)
class TournamentConfigPatchRequest(Struct, kw_only=True):
    """Partial update for tournament config.

    Attributes:
        blacklist_weeks: Number of weeks for map cooldown.
    """

    blacklist_weeks: int | UnsetType = UNSET
```

### Pattern 3: JSONB Sub-Structs
**What:** JSONB columns with structured data are modeled as typed sub-structs instead of `list[dict]`.
**When to use:** When a JSONB column has a known, stable shape (like `placement_xp` = `[{place: N, xp: N}]`).
**Example:**
```python
# Follows pattern from store.py QuestRequirements (verified codebase pattern)
class PlacementXpTier(Struct):
    """Single placement-based XP reward tier.

    Attributes:
        place: Placement position (1st, 2nd, etc.).
        xp: XP amount awarded for this placement.
    """

    place: int
    xp: int


class StreakXpTier(Struct):
    """Single streak-based XP reward threshold.

    Attributes:
        threshold: Number of consecutive cycles required.
        xp: XP amount awarded at this threshold.
    """

    threshold: int
    xp: int
```

### Pattern 4: Domain Exception Hierarchy
**What:** Each domain has one base error extending `DomainError`, with specific subclasses for each business rule violation.
**When to use:** Every new service domain.
**Example:**
```python
# Source: apps/api/services/exceptions/completions.py (verified codebase pattern)
from utilities.errors import DomainError


class TournamentsError(DomainError):
    """Base for tournaments domain errors."""


class CycleNotFoundError(TournamentsError):
    """Cycle ID does not exist."""

    def __init__(self, cycle_id: int) -> None:
        super().__init__("Cycle not found.", cycle_id=cycle_id)
```

### Pattern 5: Event Struct (Minimal)
**What:** RabbitMQ event structs carry only the IDs/data the consumer needs, not full response objects.
**When to use:** When defining structs for RabbitMQ messages.
**Example:**
```python
# Source: libs/sdk/src/genjishimada_sdk/completions.py line 325-332 (verified)
class TournamentCompletionCreatedEvent(Struct):
    """Event emitted when a tournament completion is created.

    Attributes:
        completion_id: Identifier of the tournament completion.
        cycle_id: Identifier of the tournament cycle.
    """

    completion_id: int
    cycle_id: int
```

### Anti-Patterns to Avoid

- **Optional-field bloat:** Do not create one "universal" response struct with optional fields for everything. Use distinct types per use case (D-04). Example: `TournamentCycleResponse` for cycle details vs `TournamentCycleResultsResponse` for archived results with standings.
- **`list[dict]` for structured JSONB:** The `store.py` `QuestRequirements` struct proves that typed sub-structs work. Using `list[dict]` loses all type safety and forces downstream code to do runtime checks. Use `list[PlacementXpTier]` and `list[StreakXpTier]`.
- **Importing `from __future__ import annotations`:** The completions SDK module does NOT use it (it uses concrete types). The maps SDK module DOES use it. Either is acceptable, but be consistent within the module. Since tournaments will have no circular imports and no forward references, omitting it is cleaner (matches completions.py).
- **Forgetting `__all__`:** Every SDK module MUST define `__all__` as a tuple. Omitting it breaks the explicit public API pattern used by all other modules.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Partial update semantics | Custom nullable field tracking | msgspec `UNSET`/`UnsetType` | Built-in sentinel that serialization ignores correctly |
| Field validation (ranges, patterns) | Runtime validation in `__post_init__` | `Annotated[type, Meta(ge=X, le=Y)]` | msgspec validates on decode automatically |
| Cycle status enumeration | String constants scattered in code | `Literal["pending", "active", "finalizing", "completed"]` | Type checker enforces valid values at compile time |
| JSON sub-struct encoding | Manual dict building | msgspec Struct for JSONB columns | Automatic encode/decode with asyncpg JSONB codec |

**Key insight:** msgspec handles serialization, validation, and encoding automatically. The SDK types need zero runtime logic -- they are pure data definitions.

## Common Pitfalls

### Pitfall 1: Naming Collision with content.CategoryNotFoundError
**What goes wrong:** The tournament domain defines `CategoryNotFoundError` per D-06, but `services/exceptions/content.py` already exports `CategoryNotFoundError` and it is already in the barrel `__init__.py`.
**Why it happens:** Different domains have similar entity names ("category" is used in both content and tournaments).
**How to avoid:** Either (a) prefix the tournament version as `TournamentCategoryNotFoundError` in the class definition itself, or (b) keep it as `CategoryNotFoundError` in `tournaments.py` and alias it in the barrel `__init__.py` as `TournamentsCategoryNotFoundError`. The existing codebase uses approach (b) for `MapNotFoundError` -- it exists in both `completions.py` and `maps.py`, with the completions version aliased as `CompletionsMapNotFoundError` in `__init__.py`.
**Warning signs:** Import error or name shadowing when trying to use both exceptions in the same controller or test file.
**Recommendation:** Use approach (b) -- keep `CategoryNotFoundError` in the `tournaments.py` file (matching D-06 naming), but alias it in `__init__.py` as `TournamentsCategoryNotFoundError` to match the established pattern (`CompletionsMapNotFoundError`, `ChangeRequestsMapNotFoundError`, `UsersUserNotFoundError`).

### Pitfall 2: Field Type Mismatch with Database Schema
**What goes wrong:** SDK response struct declares a field as `int` but the DB column is `numeric(10,2)` which maps to `float` via the project's asyncpg codec.
**Why it happens:** Not cross-referencing the migration file carefully.
**How to avoid:** Map every SDK struct field to the corresponding DB column type:
- `int` / `bigint` -> `int`
- `numeric(10,2)` -> `float` (project-wide codec converts numeric -> float)
- `text` -> `str`
- `text[]` -> `list[str]`
- `timestamptz` -> `dt.datetime`
- `boolean` -> `bool`
- `jsonb` -> typed sub-struct
- `bigint` (Discord IDs) -> `int` (Python handles arbitrary precision)
**Warning signs:** `msgspec.ValidationError` at runtime when decoding query results.

### Pitfall 3: Missing `__all__` Entries
**What goes wrong:** A struct is defined but not exported in `__all__`, making it invisible to consumers doing `from genjishimada_sdk.tournaments import *`.
**Why it happens:** Adding a struct and forgetting to update the tuple at the top of the file.
**How to avoid:** Write `__all__` first with all planned type names, then define the classes. Verify count matches.
**Warning signs:** `ImportError` or linter warnings about unused symbols.

### Pitfall 4: Forgetting kw_only=True on PATCH Structs
**What goes wrong:** A PATCH struct with all-UNSET defaults can be instantiated positionally, which is confusing and error-prone.
**Why it happens:** `Struct` defaults to positional construction.
**How to avoid:** Use `kw_only=True` on any struct where ALL fields have defaults (all UNSET). This matches `CompletionModerateRequest` pattern.
**Warning signs:** Accidental positional instantiation in tests or service code.

### Pitfall 5: Docstring Style Violations
**What goes wrong:** Ruff D-rules fail because docstrings use wrong convention.
**Why it happens:** Using numpy or restructured text style instead of Google convention.
**How to avoid:** Follow Google docstring convention (enforced in `pyproject.toml`). Every public class needs a summary line, `Attributes:` section with indented `name: Description.` entries. Every `__init__` docstring is exempt (D107 ignored).
**Warning signs:** `ruff check` failures on D-rules.

## Code Examples

Verified patterns from codebase analysis:

### Complete SDK Module Template
```python
# Source: Pattern derived from completions.py, maps.py, store.py (verified codebase)
import datetime as dt
from typing import Literal

from msgspec import UNSET, Meta, Struct, UnsetType

from .difficulties import DifficultyTop

__all__ = (
    "PlacementXpTier",
    "StreakXpTier",
    "TournamentCategoryCreateRequest",
    "TournamentCategoryPatchRequest",
    "TournamentCategoryResponse",
    # ... all type names
)

CycleFrequency = Literal["weekly", "biweekly"]
CycleStatus = Literal["pending", "active", "finalizing", "completed"]


class PlacementXpTier(Struct):
    """Single placement-based XP reward tier.

    Attributes:
        place: Placement position (1st, 2nd, etc.).
        xp: XP amount awarded for this placement.
    """

    place: int
    xp: int


class TournamentCategoryResponse(Struct):
    """Full tournament category with XP configuration.

    Attributes:
        id: Category identifier.
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        cycle_frequency: How often cycles rotate.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
        is_active: Whether the category is currently active.
        created_at: When the category was created.
        updated_at: When the category was last updated.
    """

    id: int
    name: str
    difficulties: list[DifficultyTop]
    cycle_frequency: CycleFrequency
    participation_xp: int
    placement_xp: list[PlacementXpTier]
    streak_xp: list[StreakXpTier]
    champion_role_id: int | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime
```

### Complete Exception Module Template
```python
# Source: Pattern from completions.py, store.py, maps.py exceptions (verified codebase)
"""Tournaments domain exceptions.

These exceptions represent business rule violations in the tournaments domain.
They are raised by TournamentsService and caught by controllers.
"""

from utilities.errors import DomainError


class TournamentsError(DomainError):
    """Base for tournaments domain errors."""


class CategoryNotFoundError(TournamentsError):
    """Tournament category does not exist."""

    def __init__(self, category_id: int) -> None:
        super().__init__("Tournament category not found.", category_id=category_id)


class CycleNotActiveError(TournamentsError):
    """Submission attempted on a non-active cycle."""

    def __init__(self, cycle_id: int, status: str) -> None:
        super().__init__(
            f"Cycle is not active (current status: {status}).",
            cycle_id=cycle_id,
            status=status,
        )
```

### Barrel __init__.py Update Pattern
```python
# Source: apps/api/services/exceptions/__init__.py (verified codebase pattern)
# Shows the aliasing pattern for name collisions
from .tournaments import (
    CategoryLockedError,
    CycleAlreadyActiveError,
    CycleNotActiveError,
    CycleNotFoundError,
    DuplicateTournamentCompletionError,
    MapNotEligibleError,
    NoCycleActiveError,
    TournamentsError,
)
from .tournaments import (
    CategoryNotFoundError as TournamentsCategoryNotFoundError,
)
```

## Schema-to-Type Mapping Reference

This table maps every database column from the Phase 1 migration to its corresponding SDK type, ensuring no mismatches.

### tournaments.config -> TournamentConfigResponse
| DB Column | DB Type | SDK Field | SDK Type |
|-----------|---------|-----------|----------|
| id | int (always 1) | -- | (omitted, singleton) |
| blacklist_weeks | int | blacklist_weeks | int |
| created_at | timestamptz | created_at | dt.datetime |
| updated_at | timestamptz | updated_at | dt.datetime |

### tournaments.categories -> TournamentCategoryResponse
| DB Column | DB Type | SDK Field | SDK Type |
|-----------|---------|-----------|----------|
| id | int | id | int |
| name | text | name | str |
| difficulties | text[] | difficulties | list[DifficultyTop] |
| cycle_frequency | text (check) | cycle_frequency | CycleFrequency (Literal) |
| participation_xp | int | participation_xp | int |
| placement_xp | jsonb | placement_xp | list[PlacementXpTier] |
| streak_xp | jsonb | streak_xp | list[StreakXpTier] |
| champion_role_id | bigint | champion_role_id | int \| None |
| is_active | boolean | is_active | bool |
| created_at | timestamptz | created_at | dt.datetime |
| updated_at | timestamptz | updated_at | dt.datetime |

### tournaments.cycles -> TournamentCycleResponse
| DB Column | DB Type | SDK Field | SDK Type |
|-----------|---------|-----------|----------|
| id | int | id | int |
| category_id | int (FK) | category_id | int |
| map_id | int (FK) | map_id | int |
| status | text (check) | status | CycleStatus (Literal) |
| started_at | timestamptz | started_at | dt.datetime \| None |
| ended_at | timestamptz | ended_at | dt.datetime \| None |
| created_at | timestamptz | created_at | dt.datetime |

### tournaments.completions -> TournamentCompletionResponse
| DB Column | DB Type | SDK Field | SDK Type |
|-----------|---------|-----------|----------|
| id | int | id | int |
| cycle_id | int (FK) | cycle_id | int |
| user_id | bigint (FK) | user_id | int |
| map_id | int (FK) | map_id | int |
| time | numeric(10,2) | time | float |
| screenshot | text | screenshot | str |
| video | text | video | str \| None |
| verified | boolean | verified | bool |
| completion | boolean | completion | bool |
| inserted_at | timestamptz | inserted_at | dt.datetime |

### tournaments.streaks -> TournamentStreakResponse
| DB Column | DB Type | SDK Field | SDK Type |
|-----------|---------|-----------|----------|
| id | int | -- | (omitted, internal) |
| user_id | bigint (FK) | user_id | int |
| current_streak | int | current_streak | int |
| max_streak | int | max_streak | int |
| last_cycle_id | int (FK) | last_cycle_id | int \| None |
| updated_at | timestamptz | updated_at | dt.datetime |

## Complete Type Inventory

Based on D-03 and D-04, the full list of types to define:

### Sub-Structs (JSONB helpers)
1. `PlacementXpTier` -- `{place: int, xp: int}`
2. `StreakXpTier` -- `{threshold: int, xp: int}`

### Type Aliases (Literal types)
3. `CycleFrequency` = `Literal["weekly", "biweekly"]`
4. `CycleStatus` = `Literal["pending", "active", "finalizing", "completed"]`

### Config Types
5. `TournamentConfigResponse` -- singleton config read
6. `TournamentConfigPatchRequest` -- singleton config update (UNSET pattern)

### Category Types
7. `TournamentCategoryResponse` -- full category with XP config
8. `TournamentCategoryCreateRequest` -- category creation
9. `TournamentCategoryPatchRequest` -- category partial update (UNSET pattern)

### Cycle Types
10. `TournamentCycleResponse` -- cycle with status, map info, timestamps
11. `TournamentCycleResultsResponse` -- cycle results with standings (for archive/history)

### Leaderboard Types
12. `TournamentLeaderboardEntryResponse` -- ranked entry (user, time, rank, verified)

### Completion Types
13. `TournamentCompletionCreateRequest` -- submission payload
14. `TournamentCompletionResponse` -- full submission record

### Streak Types
15. `TournamentStreakResponse` -- user streak data

### Event Types (RabbitMQ)
16. `TournamentCycleStartedEvent` -- new cycle activated
17. `TournamentCycleCompletedEvent` -- cycle finalized with results
18. `TournamentCompletionCreatedEvent` -- new tournament submission
19. `TournamentXpGrantEvent` -- XP rewards to distribute

### Domain Exceptions
20. `TournamentsError(DomainError)` -- base
21. `CategoryNotFoundError(TournamentsError)` -- category ID does not exist
22. `CycleNotFoundError(TournamentsError)` -- cycle ID does not exist
23. `CycleNotActiveError(TournamentsError)` -- submission on non-active cycle
24. `DuplicateTournamentCompletionError(TournamentsError)` -- user already submitted for cycle
25. `CategoryLockedError(TournamentsError)` -- category modification during active cycle
26. `MapNotEligibleError(TournamentsError)` -- map on cooldown or wrong difficulty
27. `NoCycleActiveError(TournamentsError)` -- operation requires active cycle
28. `CycleAlreadyActiveError(TournamentsError)` -- starting cycle when one already active

**Total: 19 SDK types + 9 exception classes = 28 definitions**

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Optional[X]` type hints | `X \| None` union syntax | Python 3.10+ | Project already uses new syntax exclusively |
| `handle_db_exceptions` decorator | Three-tier exception hierarchy (repo -> service -> controller) | Per CLAUDE.md anti-patterns section | New tournament code must use the three-tier pattern, NOT the legacy decorator |
| `dict` for JSONB columns | Typed `Struct` sub-types | Established in store.py `QuestRequirements` | Tournament JSONB columns (`placement_xp`, `streak_xp`) use sub-structs |
| msgspec 0.19.x | msgspec 0.20.0 | Installed in project | No breaking changes; UNSET/UnsetType stable since 0.18 |

**Deprecated/outdated:**
- `handle_db_exceptions` decorator: Per CLAUDE.md, this is being superseded by the three-tier hierarchy. Do NOT use it for tournament code.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `TournamentCycleResultsResponse` should embed a `list[TournamentLeaderboardEntryResponse]` for standings | Complete Type Inventory | Low -- fields can be adjusted in later phases |
| A2 | `TournamentXpGrantEvent` should carry `user_id`, `amount`, and `xp_type` fields (mirroring existing `XpGrantEvent`) | Complete Type Inventory | Low -- event fields are refined when the rewards engine (Phase 8) is planned |
| A3 | The `TournamentLeaderboardEntryResponse` should include `rank`, `user_id`, `name`, `time`, `verified`, `completion` | Complete Type Inventory | Low -- leaderboard field set refined during Phase 6 planning |
| A4 | The `TournamentCompletionCreateRequest` needs `code` (OverwatchCode), `user_id`, `time`, `screenshot`, and optionally `video` -- mirroring `CompletionCreateRequest` | Schema-to-Type Mapping | Low -- completion submission pattern is well-established |

## Open Questions

1. **Exact fields for TournamentCycleResultsResponse**
   - What we know: It needs cycle metadata plus standings for archive/history display
   - What's unclear: Whether it should embed the full list of leaderboard entries or just summary stats (top 3, participant count)
   - Recommendation: Include `standings: list[TournamentLeaderboardEntryResponse]` -- downstream phases can trim if needed. Response type granularity can be adjusted when Phase 6 implements the actual endpoint.

2. **TournamentXpGrantEvent vs reusing existing XpGrantEvent**
   - What we know: D-03 lists `TournamentXpGrantEvent` as a distinct type. The existing `XpGrantEvent` in `xp.py` has `user_id`, `amount`, `type`, `previous_amount`, `new_amount`.
   - What's unclear: Whether tournament XP should flow through the existing `api.xp.grant` queue (reusing `XpGrantEvent`) or a new tournament-specific queue (requiring `TournamentXpGrantEvent`).
   - Recommendation: Define `TournamentXpGrantEvent` as specified in D-03. It will carry tournament-specific context (cycle_id, category_id, grant_reason) that the generic `XpGrantEvent` lacks. The Phase 8 planner will decide the queue routing.

## Project Constraints (from CLAUDE.md)

Directives that affect this phase:

- **Linting:** Ruff rules E, F, W, A, PL, I, SIM, RUF, ASYNC, C4, INP, ERA, SLF, PIE, PYI, ANN, N, D enabled. D100, D101, D104, D107 ignored. Google docstring convention.
- **Type hints:** All function parameters and return types must have annotations (ANN rules). Use `str | None` not `Optional[str]`.
- **Line length:** 120 characters.
- **SDK module pattern:** Modules use `__all__` tuples for explicit public API.
- **Struct field ordering:** Required fields first, optional/defaulted fields last (msgspec convention).
- **Exception pattern:** Three-tier hierarchy (repo exceptions -> domain exceptions -> HTTP exceptions). Do NOT use `handle_db_exceptions` decorator for new code.
- **Import style:** Use `from utilities.errors import DomainError` (absolute within app package).
- **DB type mappings:** `numeric` -> float, `jsonb` -> msgspec Struct, `timestamptz` -> `dt.datetime`.
- **Naming conventions:** `PascalCase` for classes, `snake_case` for fields. SDK structs use `{Domain}{Action}{Suffix}` naming. Domain exceptions use `{Description}Error`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Ruff + BasedPyright (lint/type-check only -- no runtime tests for this phase) |
| Config file | Root `pyproject.toml` for Ruff and BasedPyright configuration |
| Quick run command | `just lint-sdk` |
| Full suite command | `just lint-sdk` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC-1 | tournaments.py module exists with msgspec Structs | lint | `just lint-sdk` | Wave 0 (new file) |
| SC-2 | Domain exception classes in services/exceptions/tournaments.py | lint | `uv run ruff check apps/api/services/exceptions/tournaments.py && uv run basedpyright apps/api/services/exceptions/tournaments.py` | Wave 0 (new file) |
| SC-3 | Repository exception mappings cover tournament constraints | manual-only | Visual inspection -- D-07 says no new types needed | N/A |
| SC-4 | SDK types pass lint and type-check | lint | `just lint-sdk` | Covered by SC-1 |

### Sampling Rate
- **Per task commit:** `just lint-sdk` + `uv run ruff check apps/api/services/exceptions/tournaments.py`
- **Per wave merge:** `just lint-all`
- **Phase gate:** `just lint-all` green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `libs/sdk/src/genjishimada_sdk/tournaments.py` -- new module (covers SC-1, SC-4)
- [ ] `apps/api/services/exceptions/tournaments.py` -- new exception module (covers SC-2)
- [ ] `apps/api/services/exceptions/__init__.py` -- update barrel exports

*(No test framework gaps -- this phase is validated purely by linting and type-checking, which is already fully configured.)*

## Security Domain

This phase creates pure type definitions (data classes and exception classes) with no runtime behavior, no network access, no database queries, and no user input handling. Security considerations are minimal.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- no auth logic in type definitions |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | Yes (indirectly) | msgspec `Meta(...)` validators on struct fields; `Literal[...]` for constrained values |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for Type Definitions

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Overly permissive input types | Tampering | Use `Literal[...]` for constrained string values (cycle_frequency, status); use `Annotated[int, Meta(ge=0)]` for numeric bounds |
| Unvalidated string fields | Tampering | Reuse existing validated types (`OverwatchCode`, `GuideURL`) where applicable |

## Sources

### Primary (HIGH confidence)
- `libs/sdk/src/genjishimada_sdk/completions.py` -- Struct naming patterns, Event types, UNSET pattern, __all__ exports
- `libs/sdk/src/genjishimada_sdk/maps.py` -- Literal types, Annotated validators, OverwatchCode/GuideURL types
- `libs/sdk/src/genjishimada_sdk/store.py` -- Config response pattern, JSONB sub-struct pattern (QuestRequirements)
- `libs/sdk/src/genjishimada_sdk/xp.py` -- XpGrantEvent pattern for tournament events
- `libs/sdk/src/genjishimada_sdk/difficulties.py` -- DifficultyTop/DifficultyAll types
- `libs/sdk/src/genjishimada_sdk/__init__.py` -- Module registration pattern
- `apps/api/services/exceptions/completions.py` -- Exception hierarchy template
- `apps/api/services/exceptions/maps.py` -- Exception density and naming conventions
- `apps/api/services/exceptions/store.py` -- Exception with context kwargs
- `apps/api/services/exceptions/content.py` -- Existing `CategoryNotFoundError` (collision source)
- `apps/api/services/exceptions/__init__.py` -- Import aliasing for name collisions
- `apps/api/repository/exceptions.py` -- Repository exception base classes
- `apps/api/utilities/errors.py` -- DomainError base class
- `apps/api/migrations/0020_tournaments.sql` -- Database schema (Phase 1 output)
- `pyproject.toml` -- Ruff and BasedPyright configuration
- `libs/sdk/pyproject.toml` -- SDK dependencies (msgspec >=0.19.0)

### Secondary (MEDIUM confidence)
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` -- Phase 1 decisions constraining type shapes
- `.planning/phases/02-sdk-types-domain-exceptions/02-CONTEXT.md` -- Phase 2 locked decisions

### Tertiary (LOW confidence)
None -- all findings verified against codebase sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new packages; msgspec 0.20.0 verified installed
- Architecture: HIGH -- patterns directly extracted from 5+ existing SDK modules and exception files
- Pitfalls: HIGH -- naming collision verified by reading actual `__init__.py` exports; type mappings verified against migration SQL

**Research date:** 2026-05-29
**Valid until:** 2026-06-29 (stable patterns, no external dependencies)
