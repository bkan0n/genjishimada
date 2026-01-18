from __future__ import annotations

import datetime as dt
import inspect
from logging import getLogger
from typing import TYPE_CHECKING, Any, Awaitable, Callable

import msgspec
from asyncpg import Connection, Record
from genjishimada_sdk.maps import (
    MapEditFieldChange,
    MapEditResponse,
    MapEditSubmissionResponse,
    MapPatchRequest,
    MedalsResponse,
    PendingMapEditResponse,
)
from genjishimada_sdk.users import Creator
from litestar.datastructures import State
from litestar.status_codes import HTTP_409_CONFLICT

from di.base import BaseService
from utilities.errors import CustomHTTPException

if TYPE_CHECKING:
    pass

log = getLogger(__name__)

# Preview length for field values
_PREVIEW_MAX_LENGTH = 50


class MapEditService(BaseService):
    """Service for managing map edit requests."""

    async def create_edit_request(
        self,
        code: str,
        proposed_changes: dict[str, Any],
        reason: str,
        created_by: int,
    ) -> MapEditResponse:
        """Create a new map edit request.

        Args:
            code: The map code to edit.
            proposed_changes: Dict of field -> new_value.
            reason: Reason for the edit request.
            created_by: User ID of the submitter.

        Returns:
            The created edit request.

        Raises:
            ValueError: If the map code doesn't exist.
        """
        # Get map_id from code
        map_row = await self._conn.fetchrow(
            "SELECT id FROM core.maps WHERE code = $1",
            code,
        )
        if not map_row:
            raise ValueError(f"Map with code {code} not found")

        map_id = map_row["id"]

        pending_row = await self._conn.fetchrow(
            """
            SELECT id
            FROM maps.edit_requests
            WHERE map_id = $1 AND accepted IS NULL
            """,
            map_id,
        )
        if pending_row:
            raise CustomHTTPException(
                detail="There is already a pending edit request for this map.",
                status_code=HTTP_409_CONFLICT,
                extra={"edit_request_id": pending_row["id"]},
            )

        row = await self._conn.fetchrow(
            """
            INSERT INTO maps.edit_requests (
                map_id, code, proposed_changes, reason, created_by
            )
            VALUES ($1, $2, $3::jsonb, $4, $5)
            RETURNING
                id, map_id, code, proposed_changes, reason, created_by,
                created_at, message_id, resolved_at, accepted,
                resolved_by, rejection_reason
            """,
            map_id,
            code,
            msgspec.json.encode(proposed_changes).decode(),
            reason,
            created_by,
        )

        if row is None:
            raise ValueError(f"Failed to create edit request for {code}")

        return self._row_to_response(row)

    async def get_edit_request(self, edit_id: int) -> MapEditResponse:
        """Get a specific edit request by ID.

        Args:
            edit_id: The edit request ID.

        Returns:
            The edit request.

        Raises:
            ValueError: If not found.
        """
        row = await self._conn.fetchrow(
            """
            SELECT
                id, map_id, code, proposed_changes, reason, created_by,
                created_at, message_id, resolved_at, accepted,
                resolved_by, rejection_reason
            FROM maps.edit_requests
            WHERE id = $1
            """,
            edit_id,
        )
        if row is None:
            raise ValueError(f"Edit request {edit_id} not found")

        return self._row_to_response(row)

    async def get_pending_requests(self) -> list[PendingMapEditResponse]:
        """Get all pending (unresolved) edit requests.

        Returns:
            List of pending edit requests.
        """
        rows = await self._conn.fetch(
            """
            SELECT id, code, message_id
            FROM maps.edit_requests
            WHERE accepted IS NULL
            ORDER BY created_at
            """
        )
        return [
            PendingMapEditResponse(
                id=row["id"],
                code=row["code"],
                message_id=row["message_id"],
            )
            for row in rows
        ]

    async def get_edit_submission(
        self,
        edit_id: int,
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> MapEditSubmissionResponse:
        """Get enriched edit request data for verification queue display.

        Fetches the edit request, current map data, and submitter info,
        then computes human-readable field changes.

        Args:
            edit_id: The edit request ID.
            get_creator_name: Function to get creator names.

        Returns:
            Enriched submission data with readable changes.
        """
        # Get the edit request with map info
        edit_row = await self._conn.fetchrow(
            """
            SELECT
                e.id, e.code, e.proposed_changes, e.reason,
                e.created_by, e.created_at, e.message_id,
                m.id AS map_id, m.map_name, m.difficulty
            FROM maps.edit_requests e
            JOIN core.maps m ON m.id = e.map_id
            WHERE e.id = $1
            """,
            edit_id,
        )
        if edit_row is None:
            raise ValueError(f"Edit request {edit_id} not found")

        # Get submitter name
        user_row = await self._conn.fetchrow(
            """
            SELECT COALESCE(nickname, global_name, 'Unknown User') as name
            FROM core.users
            WHERE id = $1
            """,
            edit_row["created_by"],
        )
        submitter_name = user_row["name"] if user_row else "Unknown User"

        # Get current map data for comparison
        map_row = await self._conn.fetchrow(
            """
              WITH target_map AS (
                SELECT
                  id,
                  code,
                  map_name,
                  category,
                  checkpoints,
                  difficulty,
                  description,
                  title,
                  custom_banner,
                  hidden,
                  archived,
                  official
                FROM core.maps
                WHERE code = $1
              ),
              mechanics AS (
                SELECT
                  ml.map_id,
                  array_agg(mech.name ORDER BY mech.position) AS mechanics
                FROM maps.mechanic_links ml
                JOIN maps.mechanics mech ON mech.id = ml.mechanic_id
                WHERE ml.map_id = (SELECT id FROM target_map)
                GROUP BY ml.map_id
              ),
              restrictions AS (
                SELECT
                  rl.map_id,
                  array_agg(res.name ORDER BY res.name) AS restrictions
                FROM maps.restriction_links rl
                JOIN maps.restrictions res ON res.id = rl.restriction_id
                WHERE rl.map_id = (SELECT id FROM target_map)
                GROUP BY rl.map_id
              )
              SELECT
                tm.code,
                tm.map_name,
                tm.category,
                tm.checkpoints,
                tm.difficulty,
                tm.description,
                tm.title,
                tm.custom_banner,
                tm.hidden,
                tm.archived,
                tm.official,
                mech.mechanics,
                res.restrictions
              FROM target_map tm
              LEFT JOIN mechanics mech ON mech.map_id = tm.id
              LEFT JOIN restrictions res ON res.map_id = tm.id;
            """,
            edit_row["code"],
        )
        if map_row is None:
            raise ValueError(f"Map {edit_row['code']} not found")

        creator_rows = await self._conn.fetch(
            """
            SELECT user_id, is_primary
            FROM maps.creators
            WHERE map_id = $1
            ORDER BY is_primary DESC, user_id
            """,
            edit_row["map_id"],
        )

        # Get medals separately (different table structure based on your schema)
        medals_row = await self._conn.fetchrow(
            """
            SELECT gold, silver, bronze
            FROM maps.medals md
            JOIN core.maps m ON m.id = md.map_id
            WHERE m.code = $1
            """,
            edit_row["code"],
        )

        # Parse proposed changes
        proposed_changes = edit_row["proposed_changes"]
        if isinstance(proposed_changes, str):
            proposed_changes = msgspec.json.decode(proposed_changes)

        # Build human-readable changes
        map_data = dict(map_row)
        map_data["creators"] = [{"id": row["user_id"], "is_primary": row["is_primary"]} for row in creator_rows]
        medals_data = dict(medals_row) if medals_row else None
        changes = await self._build_field_changes(
            map_data,
            medals_data,
            proposed_changes,
            get_creator_name=get_creator_name,
        )

        return MapEditSubmissionResponse(
            id=edit_row["id"],
            code=edit_row["code"],
            map_name=edit_row["map_name"],
            difficulty=edit_row["difficulty"],
            changes=changes,
            reason=edit_row["reason"],
            submitter_name=submitter_name,
            submitter_id=edit_row["created_by"],
            created_at=edit_row["created_at"],
            message_id=edit_row["message_id"],
        )

    async def _build_field_changes(
        self,
        current_map: dict[str, Any],
        current_medals: dict[str, Any] | None,
        proposed: dict[str, Any],
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> list[MapEditFieldChange]:
        """Build a human-readable field change list.

        Args:
            current_map: Current map data from a database.
            current_medals: Current medal data (might be None).
            proposed: Proposed changes dict.
            get_creator_name: Function to get creator names.

        Returns:
            List of field changes with old/new values formatted.
        """
        changes = []

        for field_name, new_value in proposed.items():
            if field_name == "medals":
                old_value = (
                    {
                        "gold": current_medals["gold"],
                        "silver": current_medals["silver"],
                        "bronze": current_medals["bronze"],
                    }
                    if current_medals
                    else None
                )
            else:
                old_value = current_map.get(field_name)

            # Format values for display
            if field_name == "creators":
                old_display = await self._format_creators_for_display(old_value, get_creator_name)
                new_display = await self._format_creators_for_display(new_value, get_creator_name)
            else:
                old_display = self._format_value_for_display(field_name, old_value)
                new_display = self._format_value_for_display(field_name, new_value)

            # Convert field name to display name
            display_name = field_name.replace("_", " ").title()

            changes.append(
                MapEditFieldChange(
                    field=display_name,
                    old_value=old_display,
                    new_value=new_display,
                )
            )

        return changes

    @staticmethod
    async def _format_creators_for_display(
        value: Any,  # noqa: ANN401
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> str:
        """Format creator values for human-readable display."""
        if value is None:
            return "Not set"

        if not value:
            return "None"

        if isinstance(value, dict):
            value = [value]

        if not isinstance(value, list):
            return str(value)

        rendered = []
        for creator in value:
            if isinstance(creator, dict):
                creator_id = creator.get("id")
                is_primary = creator.get("is_primary")
                name = creator.get("name")
            else:
                creator_id = getattr(creator, "id", None)
                is_primary = getattr(creator, "is_primary", None)
                name = getattr(creator, "name", None)

            if not name and creator_id and get_creator_name:
                resolved = get_creator_name(int(creator_id))
                name = await resolved if inspect.isawaitable(resolved) else resolved
            if not name:
                name = "Unknown User"

            primary_suffix = "primary, " if is_primary else ""
            if creator_id:
                rendered.append(f"{name} ({primary_suffix}{creator_id})")
            else:
                rendered.append(name)

        return ", ".join(rendered)

    @staticmethod
    def _format_value_for_display(field: str, value: str | float | bool | list | dict | None) -> str:
        """Format a field value for a human-readable display.

        Args:
            field: Field name.
            value: Field value.

        Returns:
            Formatted string.
        """
        if value is None:
            return "Not set"

        # Boolean fields
        if field in ("hidden", "archived", "official"):
            return "Yes" if value else "No"

        # Medal fields
        if field == "medals" and isinstance(value, dict):
            return f"🥇 {value.get('gold')} | 🥈 {value.get('silver')} | 🥉 {value.get('bronze')}"

        # List fields (mechanics, restrictions, etc.)
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "None"

        return str(value)

    async def set_message_id(self, edit_id: int, message_id: int) -> None:
        """Associate a Discord message ID with an edit request.

        Args:
            edit_id: The edit request ID.
            message_id: The Discord message ID.
        """
        await self._conn.execute(
            """
            UPDATE maps.edit_requests
            SET message_id = $2
            WHERE id = $1
            """,
            edit_id,
            message_id,
        )

    async def resolve_request(
        self,
        edit_id: int,
        accepted: bool,
        resolved_by: int,
        rejection_reason: str | None = None,
    ) -> None:
        """Mark an edit request as resolved.

        Args:
            edit_id: The edit request ID.
            accepted: Whether the request was accepted.
            resolved_by: User ID of the resolver.
            rejection_reason: Reason for rejection (if rejected).
        """
        await self._conn.execute(
            """
            UPDATE maps.edit_requests
            SET
                resolved_at = $2,
                accepted = $3,
                resolved_by = $4,
                rejection_reason = $5
            WHERE id = $1
            """,
            edit_id,
            dt.datetime.now(dt.timezone.utc),
            accepted,
            resolved_by,
            rejection_reason,
        )

    @staticmethod
    def convert_changes_to_patch(proposed_changes: dict[str, Any]) -> MapPatchRequest:
        """Convert a proposed_changes dict to a MapPatchRequest.

        Args:
            proposed_changes: Dict of field -> new_value.

        Returns:
            MapPatchRequest with the changes applied.
        """
        kwargs: dict[str, Any] = {}

        for field, field_value in proposed_changes.items():
            # Handle special conversions
            if field == "medals" and field_value is not None:
                kwargs[field] = MedalsResponse(**field_value)
            elif field == "creators" and field_value is not None:
                creators = [creator if isinstance(creator, Creator) else Creator(**creator) for creator in field_value]
                kwargs[field] = creators
            else:
                kwargs[field] = field_value

        return MapPatchRequest(**kwargs)

    async def get_user_requests(
        self,
        user_id: int,
        include_resolved: bool = False,
    ) -> list[MapEditResponse]:
        """Get all edit requests submitted by a user.

        Args:
            user_id: The user's ID.
            include_resolved: Whether to include resolved requests.

        Returns:
            List of edit requests.
        """
        query = """
            SELECT
                id, map_id, code, proposed_changes, reason, created_by,
                created_at, message_id, resolved_at, accepted,
                resolved_by, rejection_reason
            FROM maps.edit_requests
            WHERE created_by = $1
        """
        if not include_resolved:
            query += " AND accepted IS NULL"

        query += " ORDER BY created_at DESC"

        rows = await self._conn.fetch(query, user_id)
        return [self._row_to_response(row) for row in rows]

    @staticmethod
    def _row_to_response(row: Record) -> MapEditResponse:
        """Convert a database row to MapEditResponse.

        Args:
            row: Database row dict.

        Returns:
            MapEditResponse instance.
        """
        proposed_changes = row["proposed_changes"]
        if isinstance(proposed_changes, str):
            proposed_changes = msgspec.json.decode(proposed_changes)

        return MapEditResponse(
            id=row["id"],
            map_id=row["map_id"],
            code=row["code"],
            proposed_changes=proposed_changes,
            reason=row["reason"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            message_id=row["message_id"],
            resolved_at=row["resolved_at"],
            accepted=row["accepted"],
            resolved_by=row["resolved_by"],
            rejection_reason=row["rejection_reason"],
        )


async def provide_map_edit_service(conn: Connection, state: State) -> MapEditService:
    """Litestar DI provider for MapEditService.

    Args:
        conn: Active asyncpg connection.
        state: App state.

    Returns:
        MapEditService instance.
    """
    return MapEditService(conn=conn, state=state)
