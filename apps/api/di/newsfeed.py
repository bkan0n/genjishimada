from __future__ import annotations

import datetime as dt
import inspect
from logging import getLogger
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Iterable

import msgspec
from genjishimada_sdk.maps import MapPatchRequest, MapResponse
from genjishimada_sdk.newsfeed import (
    NewsfeedDispatchEvent,
    NewsfeedEvent,
    NewsfeedFieldChange,
    NewsfeedMapEdit,
    PublishNewsfeedJobResponse,
)
from litestar.datastructures import Headers

from di.base import BaseService

if TYPE_CHECKING:
    from asyncpg import Connection
    from litestar.datastructures import State


log = getLogger(__name__)

# Type alias for readability
Friendly = str

# Fields to skip entirely in the newsfeed
_EXCLUDED_FIELDS = {"hidden", "official", "archived", "playtesting"}

# Fields that are list-like and should be normalized/sorted for comparison
_LIST_FIELDS = {"creators", "mechanics", "restrictions"}


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
    async def create_and_publish(
        self,
        event: NewsfeedEvent,
        *,
        headers: Headers,
        use_pool: bool = False,
    ) -> PublishNewsfeedJobResponse:
        """Insert a newsfeed event and publish its ID to Rabbit.

        Args:
            event (NewsfeedEvent): The event payload to persist.
            headers (Headers): HTTP headers to include in the published message.
            use_pool (bool): Whether or not to use a pool for the connection.

        Returns:
            PublishNewsfeedJobResponse: The job status and newly created newsfeed event ID.
        """
        q = "INSERT INTO newsfeed (timestamp, payload) VALUES ($1, $2::jsonb) RETURNING id;"
        payload_obj = msgspec.to_builtins(event.payload)
        if use_pool:
            async with self._pool.acquire() as conn:
                new_id = await conn.fetchval(q, event.timestamp, payload_obj)
        else:
            new_id = await self._conn.fetchval(q, event.timestamp, payload_obj)
        idempotency_key = f"newsfeed:create:{new_id}"
        job_status = await self.publish_message(
            routing_key="api.newsfeed.create",
            data=NewsfeedDispatchEvent(newsfeed_id=new_id),
            headers=headers,
            idempotency_key=idempotency_key,
            use_pool=use_pool,
        )
        return PublishNewsfeedJobResponse(job_status, new_id)

    async def get_event(self, id_: int) -> NewsfeedEvent | None:
        """Fetch a single newsfeed event by ID.

        Args:
            id_ (int): The newsfeed event ID.

        Returns:
            NewsfeedEvent: The resolved event.
        """
        row = await self._conn.fetchrow(
            "SELECT id, timestamp, payload, event_type FROM newsfeed WHERE id=$1",
            id_,
        )
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
            limit (int): Page size to return (e.g., 10, 20, 25, 50).
            page_number (int): 1-based page number.
            type_ (str | None): Optional event type filter.

        Returns:
            list[NewsfeedEvent]: Events ordered by most recent first (timestamp DESC, id DESC).
        """
        offset = max(page_number - 1, 0) * limit
        q = """
            SELECT id, timestamp, payload, event_type, count(*) OVER () AS total_results
            FROM newsfeed
            WHERE ($1::text IS NULL OR event_type = $1)
            ORDER BY timestamp DESC, id DESC
            LIMIT $2 OFFSET $3
        """
        rows = await self._conn.fetch(q, type_, limit, offset)

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

        await self.create_and_publish(event, headers=headers)


async def provide_newsfeed_service(conn: Connection, state: State) -> NewsfeedService:
    """Litestar DI provider for `NewsfeedService`.

    Args:
        conn (Connection): Active asyncpg connection scoped to the request.
        state (State): Application state instance.

    Returns:
        NewsfeedService: Service instance configured with the given connection and state.
    """
    return NewsfeedService(conn=conn, state=state)
