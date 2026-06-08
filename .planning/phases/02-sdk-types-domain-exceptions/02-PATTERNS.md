# Phase 2: SDK Types & Domain Exceptions - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 3 new/modified files
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | model | transform | `libs/sdk/src/genjishimada_sdk/completions.py` | exact |
| `apps/api/services/exceptions/tournaments.py` | model | N/A | `apps/api/services/exceptions/completions.py` | exact |
| `apps/api/services/exceptions/__init__.py` | config | N/A | `apps/api/services/exceptions/__init__.py` (self) | exact |

## Pattern Assignments

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (model, transform)

**Primary Analog:** `libs/sdk/src/genjishimada_sdk/completions.py`
**Secondary Analog:** `libs/sdk/src/genjishimada_sdk/store.py` (for config response and JSONB sub-struct patterns)
**Tertiary Analog:** `libs/sdk/src/genjishimada_sdk/xp.py` (for Event struct and Literal type alias patterns)

**Imports pattern** (completions.py lines 1-8):
```python
import datetime as dt
from typing import Annotated, Literal

from msgspec import UNSET, Meta, Struct, UnsetType

from .difficulties import DifficultyAll, DifficultyTop
from .internal import JobStatusResponse
from .maps import GuideURL, MedalType, OverwatchCode, OverwatchMap
```

Notes for tournaments.py:
- Import `dt`, `Literal` from typing (no `Annotated` or `Meta` unless field validation is added)
- Import `UNSET`, `Struct`, `UnsetType` from msgspec (no `Meta` unless using `Annotated[int, Meta(ge=...)]`)
- Import `DifficultyTop` from `.difficulties` (categories reference difficulty groupings)
- Do NOT import `from __future__ import annotations` -- completions.py does not use it; keep consistent

**`__all__` exports pattern** (completions.py lines 10-36):
```python
__all__ = (
    "CompletionCreateRequest",
    "CompletionCreatedEvent",
    "CompletionModerateRequest",
    "CompletionPatchRequest",
    "CompletionResponse",
    "CompletionSubmissionJobResponse",
    "CompletionSubmissionResponse",
    "CompletionVerificationUpdateRequest",
    "DashboardCompletionResponse",
    # ... all public names in alphabetical order
)
```

Notes for tournaments.py:
- Tuple (not list), alphabetically sorted
- Include sub-structs (`PlacementXpTier`, `StreakXpTier`) and type aliases (`CycleFrequency`, `CycleStatus`)
- Every public class and type alias must appear here

**Literal type alias pattern** (xp.py line 17, difficulties.py lines 20-27):
```python
# xp.py line 17
XP_TYPES = Literal["Map Submission", "Playtest", "Guide", "Completion", "Record", "World Record", "Quest", "Other"]

# difficulties.py lines 20-27
DifficultyTop = Literal[
    "Easy",
    "Medium",
    "Hard",
    "Very Hard",
    "Extreme",
    "Hell",
]
```

Notes for tournaments.py:
- Define `CycleFrequency = Literal["weekly", "biweekly"]` and `CycleStatus = Literal["pending", "active", "finalizing", "completed"]`
- Place after `__all__` and before class definitions

**JSONB sub-struct pattern** (store.py lines 505-519 -- QuestRequirements):
```python
class QuestRequirements(Struct):
    """Quest requirement specification."""

    type: str
    count: int | None = None
    difficulty: str | None = None
    category: str | None = None
    medal_type: str | None = None
    map_id: int | None = None
    target_time: float | None = None
    target_type: str | None = None
    rival_user_id: int | None = None
    rival_time: float | None = None
    target: str | None = None
    min_count: int | None = None
```

Notes for tournaments.py:
- `PlacementXpTier` and `StreakXpTier` are simpler (all required fields, no defaults)
- Define BEFORE any struct that references them (e.g., `TournamentCategoryResponse`)

**Config response pattern** (store.py lines 53-67 -- StoreConfigResponse):
```python
class StoreConfigResponse(Struct):
    """Store configuration response.

    Attributes:
        rotation_period_days: How often the store rotates.
        active_key_type: Current active key type.
        last_rotation_at: When the last rotation occurred.
        next_rotation_at: When the next rotation will occur.
    """

    rotation_period_days: int
    active_key_type: str
    last_rotation_at: dt.datetime
    next_rotation_at: dt.datetime
```

Notes for tournaments.py:
- `TournamentConfigResponse` follows this exact shape (singleton config with timestamps)

**Response struct pattern** (completions.py lines 100-145 -- CompletionResponse):
```python
class CompletionResponse(Struct):
    """Represents a completion entry with verification metadata.

    Attributes:
        code: Workshop code for the map.
        user_id: Identifier for the completing user.
        name: Display name of the runner.
        # ... all fields documented
    """

    code: OverwatchCode
    user_id: int
    name: str
    also_known_as: str | None
    time: float
    screenshot: str
    video: GuideURL | None
    completion: bool
    verified: bool
    rank: int | None
    medal: MedalType | None
    # ... required fields first, defaulted fields last
    total_results: int | None = None
    upvotes: int = 0
    id: int | None = None
```

Notes for tournaments.py:
- Required fields first, optional/defaulted fields last
- Google-style docstring with `Attributes:` section
- Each attribute gets `name: Description.` (period at end)

**Create request pattern** (completions.py lines 63-78 -- CompletionCreateRequest):
```python
class CompletionCreateRequest(Struct):
    """Request payload for submitting a completion.

    Attributes:
        code: Workshop code for the map.
        user_id: Identifier for the submitting user.
        time: Completion time in seconds.
        screenshot: Proof screenshot URL.
        video: Optional video proof URL.
    """

    code: OverwatchCode
    user_id: int
    time: float
    screenshot: GuideURL
    video: GuideURL | None
```

Notes for tournaments.py:
- `TournamentCompletionCreateRequest` follows same shape (simple required fields, optional at end)

**PATCH request with UNSET pattern** (completions.py lines 238-255 -- CompletionPatchRequest):
```python
class CompletionPatchRequest(Struct):
    """Partial update payload for completion records.

    Attributes:
        message_id: Discord message identifier for the submission.
        completion: Flag indicating completion status.
        verification_id: Identifier linking to verification metadata.
        legacy: Whether the record predates current validation rules.
        legacy_medal: Medal tier used for legacy records.
        wr_xp_check: Whether to perform world-record XP validation.
    """

    message_id: int | UnsetType = UNSET
    completion: bool | UnsetType = UNSET
    verification_id: int | UnsetType = UNSET
    legacy: bool | UnsetType = UNSET
    legacy_medal: str | None | UnsetType = UNSET
    wr_xp_check: bool | UnsetType = UNSET
```

Notes for tournaments.py:
- `TournamentConfigPatchRequest` and `TournamentCategoryPatchRequest` follow this pattern
- Use `kw_only=True` when ALL fields have UNSET defaults (see CompletionModerateRequest at line 287 for precedent: `class CompletionModerateRequest(Struct, kw_only=True):`)

**Event struct pattern** (completions.py lines 325-332 -- CompletionCreatedEvent, xp.py lines 143-160 -- XpGrantEvent):
```python
# completions.py lines 325-332
class CompletionCreatedEvent(Struct):
    """Event emitted when a completion is created.

    Attributes:
        completion_id: Identifier of the new completion.
    """

    completion_id: int


# xp.py lines 143-160
class XpGrantEvent(Struct):
    """Event emitted when XP is granted to a user.

    Attributes:
        user_id: Identifier of the user receiving XP.
        amount: Amount of XP granted.
        type: Category describing why XP is granted.
        previous_amount: XP total before the grant.
        new_amount: XP total after the grant.
        reason: Optional free-text reason for the grant.
    """

    user_id: int
    amount: int
    type: XP_TYPES
    previous_amount: int
    new_amount: int
    reason: str | None = None
```

Notes for tournaments.py:
- Events carry only IDs/data the consumer needs -- minimal structs
- `TournamentCycleStartedEvent`, `TournamentCycleCompletedEvent`, `TournamentCompletionCreatedEvent`, `TournamentXpGrantEvent`
- Optional fields use defaults at end (e.g., `reason: str | None = None`)

---

### `apps/api/services/exceptions/tournaments.py` (model, N/A)

**Analog:** `apps/api/services/exceptions/completions.py`
**Secondary Analog:** `apps/api/services/exceptions/store.py` (for exceptions with context kwargs and `__init__` docstrings)

**Module docstring pattern** (completions.py lines 1-5):
```python
"""Completions domain exceptions.

These exceptions represent business rule violations in the completions domain.
They are raised by CompletionsService and caught by controllers.
"""
```

Notes for tournaments.py:
- Replace "Completions" with "Tournaments" and "CompletionsService" with "TournamentsService"

**Import pattern** (completions.py line 7):
```python
from utilities.errors import DomainError
```

Notes for tournaments.py:
- Single import, absolute path within the `apps/api` package

**Base domain error pattern** (completions.py lines 10-11):
```python
class CompletionsError(DomainError):
    """Base for completions domain errors."""
```

Notes for tournaments.py:
- `class TournamentsError(DomainError):` with `"""Base for tournaments domain errors."""`

**Specific error with single context param** (completions.py lines 14-18):
```python
class MapNotFoundError(CompletionsError):
    """Map code does not exist or has been archived."""

    def __init__(self, code: str) -> None:
        super().__init__("This map code does not exist or has been archived.", code=code)
```

Notes for tournaments.py:
- `CategoryNotFoundError`, `CycleNotFoundError`, `NoCycleActiveError`, `CycleAlreadyActiveError`, `MapNotEligibleError` follow this pattern (single ID param)

**Specific error with multiple context params** (completions.py lines 21-25):
```python
class DuplicateCompletionError(CompletionsError):
    """User already has a completion for this map."""

    def __init__(self, user_id: int, map_code: str) -> None:
        super().__init__("You already have a completion for this map.", user_id=user_id, map_code=map_code)
```

Notes for tournaments.py:
- `CycleNotActiveError` (cycle_id + status), `DuplicateTournamentCompletionError` (user_id + cycle_id), `CategoryLockedError` (category_id + cycle_id) follow this pattern

**Error with f-string message** (completions.py lines 28-38, store.py lines 26-38):
```python
# completions.py lines 28-38
class SlowerThanPendingError(CompletionsError):
    """New submission is slower than pending verification."""

    def __init__(self, new_time: float, pending_time: float) -> None:
        super().__init__(
            f"You already have a pending verification for this map with time {pending_time}s. "
            f"Your new submission ({new_time}s) must be faster. "
            f"Please wait for verification or submit a faster time.",
            new_time=new_time,
            pending_time=pending_time,
        )


# store.py lines 26-38
class InsufficientCoinsError(StoreError):
    """Raised when user doesn't have enough coins."""

    def __init__(self, user_coins: int, required: int) -> None:
        """Initialize exception.

        Args:
            user_coins: User's current coin balance.
            required: Coins required for purchase.
        """
        super().__init__(
            f"Insufficient coins: have {user_coins}, need {required}", user_coins=user_coins, required=required
        )
```

Notes for tournaments.py:
- `CycleNotActiveError` should include the current status in the message via f-string
- Note: completions.py errors do NOT have `__init__` docstrings. store.py errors DO. Either pattern is accepted. Choose one style and be consistent within the file. Completions pattern (no `__init__` docstring) is cleaner since `D107` is ignored.

**No-arg error pattern** (store.py lines 53-58):
```python
class RotationExpiredError(StoreError):
    """Raised when trying to purchase from expired rotation."""

    def __init__(self) -> None:
        """Initialize exception."""
        super().__init__("Rotation has expired")
```

Notes for tournaments.py:
- `NoCycleActiveError` could be zero-arg if no context needed, or take `category_id` for context

---

### `apps/api/services/exceptions/__init__.py` (config, N/A -- modification)

**Analog:** Self (the file being modified)

**Import block pattern with aliasing** (lines 17-23, 34-36, 88-90):
```python
# Standard import (no collision)
from .change_requests import (
    ChangeRequestAlreadyExistsError,
    ChangeRequestsError,
)

# Aliased import (collision with maps.MapNotFoundError)
from .change_requests import (
    MapNotFoundError as ChangeRequestsMapNotFoundError,
)

# Another aliased import
from .completions import (
    MapNotFoundError as CompletionsMapNotFoundError,
)

# Users domain alias
from .users import (
    UserNotFoundError as UsersUserNotFoundError,
)
```

Notes for tournaments.py additions:
- Add a standard import block for all non-colliding tournament exceptions
- Add a separate aliased import for `CategoryNotFoundError as TournamentsCategoryNotFoundError` (collision with `content.CategoryNotFoundError` already exported at line 38)
- Add all new names to `__all__` list in alphabetical order
- Import blocks are grouped by domain module, alphabetically ordered among existing blocks

**`__all__` list pattern** (lines 92-157):
```python
__all__ = [
    "AlreadyInPlaytestError",
    "AlreadyOwnedError",
    # ... alphabetically sorted
    "VoteNotFoundError",
]
```

Notes:
- List (not tuple), alphabetically sorted
- Add new tournament exception names in correct alphabetical positions
- Include the aliased name `TournamentsCategoryNotFoundError` (not the original `CategoryNotFoundError`)

---

## Shared Patterns

### Google Docstring Convention
**Source:** All SDK modules and exception files
**Apply to:** `tournaments.py` (SDK), `tournaments.py` (exceptions)

Every public class must have:
1. Summary line (one sentence)
2. Blank line
3. `Attributes:` section with indented `name: Description.` entries (period at end)

Exception classes need only a summary line docstring (no `Attributes:` section). The `__init__` docstring is optional (D107 is ignored in project config).

### Field Ordering Convention
**Source:** All SDK modules (completions.py, store.py, xp.py)
**Apply to:** All structs in `tournaments.py` (SDK)

1. Required fields first (no default value)
2. Optional/nullable fields without defaults next (e.g., `field: str | None`)
3. Fields with explicit defaults last (e.g., `field: int = 0`, `field: str | None = None`)
4. UNSET fields in PATCH structs: all fields have `= UNSET` defaults

### `kw_only=True` for All-Default Structs
**Source:** `libs/sdk/src/genjishimada_sdk/completions.py` line 287
**Apply to:** PATCH request structs where ALL fields have UNSET defaults
```python
class CompletionModerateRequest(Struct, kw_only=True):
```

### SDK `__init__.py` Registration
**Source:** `libs/sdk/src/genjishimada_sdk/__init__.py` lines 5-20
**Apply to:** SDK `__init__.py` (modification)
```python
from . import (
    auth,
    change_requests,
    completions,
    difficulties,
    internal,
    logs,
    lootbox,
    maps,
    newsfeed,
    notifications,
    rank_card,
    store,
    tournaments,  # NEW: add in alphabetical position
    users,
    xp,
)

__all__ = [
    # ... existing entries ...
    "tournaments",  # NEW: add in alphabetical position
    # ...
]
```

### DomainError Base Class
**Source:** `apps/api/utilities/errors.py` lines 150-169
**Apply to:** `apps/api/services/exceptions/tournaments.py`
```python
class DomainError(Exception):
    """Base exception for domain-level business rule violations.

    Attributes:
        message: Human-readable error message.
        context: Additional context about the error.

    """

    def __init__(self, message: str, **context: typing.Any) -> None:  # noqa: ANN401
        super().__init__(message)
        self.message = message
        self.context = context
```

Key details:
- `message` is first positional arg to `super().__init__`
- `**context` passes named kwargs stored as dict on `self.context`
- Subclasses call `super().__init__("message text", key=value, key2=value2)`

## No Analog Found

No files in this phase lack a close analog. All three files have exact matches in the codebase.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | -- | -- | -- |

## Metadata

**Analog search scope:** `libs/sdk/src/genjishimada_sdk/`, `apps/api/services/exceptions/`, `apps/api/utilities/`
**Files scanned:** 8 analog files read (completions.py SDK, store.py SDK, xp.py SDK, difficulties.py SDK, maps.py SDK first 50 lines, __init__.py SDK, completions.py exceptions, store.py exceptions, __init__.py exceptions, errors.py utilities)
**Pattern extraction date:** 2026-05-29
