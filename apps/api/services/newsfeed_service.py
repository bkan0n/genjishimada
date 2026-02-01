"""Service layer for newsfeed domain business logic."""

from __future__ import annotations

import datetime as dt
import inspect
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

import msgspec
from asyncpg import Pool
from genjishimada_sdk.maps import MapPatchRequest, MapResponse
from genjishimada_sdk.newsfeed import (
    NewsfeedDispatchEvent,
    NewsfeedEvent,
    NewsfeedFieldChange,
    NewsfeedMapEdit,
    PublishNewsfeedJobResponse,
)
from litestar.datastructures import Headers, State

from services.base import BaseService

if TYPE_CHECKING:
    from repository.newsfeed_repository import NewsfeedRepository

log = logging.getLogger(__name__)

# Type alias for readability
Friendly = str

# Fields to skip entirely in the newsfeed
_EXCLUDED_FIELDS = {"hidden", "official", "archived", "playtesting"}

# Fields that are list-like and should be normalized/sorted for comparison
_LIST_FIELDS = {"creators", "mechanics", "restrictions", "tags"}


def _labelize(field: str) -> str:
    """Convert a snake_case field name into a human-friendly label.

    Transforms e.g. ``"map_name"`` into ``"Map Name"``.

    Args:
        field: The snake_case field name.

    Returns:
        A title-cased string suitable for display.
    """
    return field.replace("_", " ").title()


def _friendly_none(v: Any) -> Friendly:  # noqa: ANN401
    """Render a placeholder for ``None``-like values.

    Args:
        v: The value to render (ignored; only used for signature symmetry).

    Returns:
        A user-friendly placeholder string.
    """
    return "Empty"


def _to_builtin(v: Any) -> Any:  # noqa: ANN401
    """Convert values to JSON-serializable Python builtins.

    This uses ``msgspec.to_builtins`` to normalize enums, msgspec structs,
    dataclasses, and other supported types into standard Python types.

    Args:
        v: The value to convert.

    Returns:
        A JSON-serializable representation of ``v``.
    """
    return msgspec.to_builtins(v)


def _list_norm(items: Iterable[Any]) -> list:
    """Normalize an iterable of values for stable comparison and display.

    Converts items to builtins, sorts them with a string key for determinism,
    and returns a list. ``None`` is treated as an empty iterable.

    Args:
        items: The values to normalize (may be ``None``).

    Returns:
        A stably sorted list of normalized values.
    """
    lst = list(items or [])
    try:
        return sorted((_to_builtin(x) for x in lst), key=lambda x: (str(x)))
    except Exception:
        # Ultra-conservative fallback if items are not directly comparable
        return sorted([str(_to_builtin(x)) for x in lst])


async def _resolve_creator_name(
    resolver: Callable[[int], str | Awaitable[str]] | None,
    creator_id: int,
) -> str | None:
    """Resolve a creator's display name from an ID using a sync or async resolver.

    If ``resolver`` is async, this function awaits it; if sync, it calls directly.

    Args:
        resolver: Callable that returns a name (sync) or an awaitable name (async).
        creator_id: The numeric creator ID to resolve.

    Returns:
        The resolved display name, or ``None`` if unavailable.
    """
    if resolver is None:
        return None
    try:
        result = resolver(creator_id)
        if inspect.isawaitable(result):
            return await result  # type: ignore[func-returns-value]
        return result  # type: ignore[return-value]
    except Exception:
        return None


async def _friendly_value(
    field: str,
    value: Any,  # noqa: ANN401
    *,
    get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
) -> Friendly:
    """Render a field value into a user-friendly string (async for optional lookup).

    Special-cases certain fields:
      * ``creators``: Shows creator names only; if names are missing on the
        new patch value, resolves via ``get_creator_name(id)`` (sync or async).
      * list fields (``mechanics``, ``restrictions``): Order-insensitive,
        comma-separated output.
      * ``None``: Rendered as a placeholder (e.g. ``"—"``).

    For all other fields, values are converted to builtins and stringified.

    Args:
        field: The map field name being rendered.
        value: The field value to render.
        get_creator_name: Optional resolver (sync or async) for creator names
            by ID when the patch omits names.

    Returns:
        A user-friendly string representation of ``value``.
    """
    if value is None:
        return _friendly_none(value)

    if field == "creators":
        names: list[str] = []
        for x in value or []:
            xb = _to_builtin(x)
            name = None
            if isinstance(xb, dict):
                name = xb.get("name")
                if not name and get_creator_name and "id" in xb:
                    resolved = await _resolve_creator_name(get_creator_name, int(xb["id"]))
                    name = resolved or None
            if not name:
                name = str(xb.get("name") or xb.get("id") or xb)
            names.append(name)
        names = sorted(set(names), key=str.casefold)
        return ", ".join(names) if names else _friendly_none(None)

    if field in _LIST_FIELDS:
        vals = _list_norm(value)
        return ", ".join(map(str, vals)) if vals else _friendly_none(None)

    if field == "medals":
        return (
            f"\n<a:_:1406302950443192320>: {value.gold}\n"
            f"<a:_:1406302952263782466>: {value.silver}\n"
            f"<a:_:1406300035624341604>: {value.bronze}\n"
        )

    b = _to_builtin(value)
    if b is None:
        return _friendly_none(None)

    return str(b)


def _values_equal(field: str, old: Any, new: Any) -> bool:  # noqa: ANN401
    """Check semantic equality of two values for a given field.

    For list fields (``creators``, ``mechanics``, ``restrictions``), compares
    order-insensitively after normalization. For all others, compares values
    after converting to builtins.

    Args:
        field: The field name being compared.
        old: The original value.
        new: The new/patch value.

    Returns:
        ``True`` if the values are semantically equal; otherwise ``False``.
    """
    if field in _LIST_FIELDS:
        return _list_norm(old) == _list_norm(new)
    return _to_builtin(old) == _to_builtin(new)


class NewsfeedService(BaseService):
    """Service for newsfeed domain business logic.

    Provides methods for creating, reading, and listing newsfeed events.
    Includes helper for generating map edit newsfeed entries.
    """

    def __init__(self, pool: Pool, state: State, newsfeed_repo: NewsfeedRepository) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            newsfeed_repo: Newsfeed repository instance.
        """
        super().__init__(pool, state)
        self._newsfeed_repo = newsfeed_repo

    async def create_and_publish(
        self,
        *,
        event: NewsfeedEvent,
        headers: Headers,
    ) -> PublishNewsfeedJobResponse:
        """Insert a newsfeed event and publish its ID to RabbitMQ.

        Args:
            event: The event payload to persist.
            headers: HTTP headers to include in the published message.

        Returns:
            PublishNewsfeedJobResponse: The job status and newly created newsfeed event ID.
        """
        # Convert payload to dict for storage
        payload_obj = msgspec.to_builtins(event.payload)

        # Insert event into database
        new_id = await self._newsfeed_repo.insert_event(
            timestamp=event.timestamp,
            payload=payload_obj,
        )

        # Publish to RabbitMQ
        idempotency_key = f"newsfeed:create:{new_id}"
        job_status = await self.publish_message(
            routing_key="api.newsfeed.create",
            data=NewsfeedDispatchEvent(newsfeed_id=new_id),
            headers=headers,
            idempotency_key=idempotency_key,
        )

        return PublishNewsfeedJobResponse(job_status, new_id)

    async def get_event(self, id_: int) -> NewsfeedEvent | None:
        """Fetch a single newsfeed event by ID.

        Args:
            id_: The newsfeed event ID.

        Returns:
            The resolved event or None if not found.
        """
        row = await self._newsfeed_repo.fetch_event_by_id(id_)
        if not row:
            return None
        return msgspec.convert(row, NewsfeedEvent)

    async def list_events(
        self,
        *,
        limit: int,
        page_number: int,
        type_: str | None,
    ) -> list[NewsfeedEvent] | None:
        """List newsfeed events with offset/limit pagination and optional type filter.

        Args:
            limit: Page size to return (e.g., 10, 20, 25, 50).
            page_number: 1-based page number.
            type_: Optional event type filter.

        Returns:
            Events ordered by most recent first (timestamp DESC, id DESC), or None if empty.
        """
        offset = max(page_number - 1, 0) * limit
        rows = await self._newsfeed_repo.fetch_events(
            limit=limit,
            offset=offset,
            event_type=type_,
        )

        if not rows:
            return None

        log.debug(rows)
        return msgspec.convert(rows, list[NewsfeedEvent])

    async def generate_map_edit_newsfeed(
        self,
        old_data: MapResponse,
        patch_data: MapPatchRequest,
        reason: str,
        headers: Headers,
        *,
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> None:
        """Build and publish a user-friendly `NewsfeedMapEdit` from a map PATCH.

        Behavior:
          * Ignores fields set to ``msgspec.UNSET``.
          * Excludes internal/boring fields: ``hidden``, ``official``, ``archived``, ``playtesting``.
          * Emits changes only when values actually differ (order-insensitive for lists).
          * Renders creators by **name** only (resolving IDs via ``get_creator_name`` when needed).
          * Displays ``None`` as a friendly placeholder (e.g. ``"—"``).
          * Produces prettified field labels (e.g. ``"map_name"`` → ``"Map Name"``).

        Side Effects:
          Publishes a `NewsfeedEvent` via `create_and_publish` if at least one
          material change is detected.

        Args:
            old_data: The pre-patch map snapshot (`MapResponse`) for old values.
            patch_data: The incoming partial update (`MapPatchRequest`).
            reason: Human-readable explanation for the change (shown in feed).
            headers: HTTP headers to include when publishing.
            get_creator_name: Optional resolver for creator names by ID when the
                patch omits names.

        Returns:
            None. Publishes an event only if there are material changes; otherwise no-op.
        """
        patch_fields = msgspec.structs.asdict(patch_data)
        changes: list[NewsfeedFieldChange] = []

        for field, new_val in patch_fields.items():
            if new_val is msgspec.UNSET:
                continue
            if field in _EXCLUDED_FIELDS:
                continue

            old_val = getattr(old_data, field, None)

            if _values_equal(field, old_val, new_val):
                continue

            old_f = await _friendly_value(field, old_val, get_creator_name=get_creator_name)
            new_f = await _friendly_value(field, new_val, get_creator_name=get_creator_name)
            label = _labelize(field)

            changes.append(NewsfeedFieldChange(field=label, old=old_f, new=new_f))

        if not changes:
            return

        payload = NewsfeedMapEdit(
            code=old_data.code,
            changes=changes,
            reason=reason,
        )

        event = NewsfeedEvent(
            id=None,
            timestamp=dt.datetime.now(dt.timezone.utc),
            payload=payload,
            event_type="map_edit",
        )

        await self.create_and_publish(event=event, headers=headers)


async def provide_newsfeed_service(state: State) -> NewsfeedService:
    """Provide NewsfeedService DI.

    Args:
        state: Application state.

    Returns:
        NewsfeedService instance.
    """
    from repository.newsfeed_repository import NewsfeedRepository  # noqa: PLC0415

    newsfeed_repo = NewsfeedRepository(state.db_pool)
    return NewsfeedService(state.db_pool, state, newsfeed_repo)
