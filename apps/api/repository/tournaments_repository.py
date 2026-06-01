"""Repository for tournaments domain database operations."""

from __future__ import annotations

from logging import getLogger

from asyncpg import Connection, Pool
from asyncpg.exceptions import CheckViolationError, ForeignKeyViolationError, UniqueViolationError
from litestar.datastructures import State

from repository.base import BaseRepository
from repository.exceptions import (
    CheckConstraintViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)
from repository.exceptions import (
    ForeignKeyViolationError as RepoFKError,
)

log = getLogger(__name__)


class TournamentRepository(BaseRepository):
    """Repository for tournaments domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    # =========================================================================
    # Config
    # =========================================================================

    async def fetch_config(
        self,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Fetch tournament configuration.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            Config dict or empty dict if not found.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM tournaments.config WHERE id = 1"
        row = await _conn.fetchrow(query)
        return dict(row) if row else {}

    async def update_config(
        self,
        updates: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update tournament configuration fields.

        Args:
            updates: Dict of field names to new values.
            conn: Optional connection for transaction support.
        """
        if not updates:
            return
        _conn = self._get_connection(conn)
        set_clauses = []
        values: list[object] = []
        for idx, (field, value) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{field} = ${idx}")
            values.append(value)
        set_clauses.append("updated_at = now()")
        query = f"UPDATE tournaments.config SET {', '.join(set_clauses)} WHERE id = 1"
        await _conn.execute(query, *values)

    # =========================================================================
    # Categories
    # =========================================================================

    async def create_category(  # noqa: PLR0913
        self,
        name: str,
        difficulties: list[str],
        cycle_frequency: str,
        participation_xp: int,
        placement_xp: object,
        streak_xp: object,
        champion_role_id: int | None,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Create a tournament category.

        Args:
            name: Category display name.
            difficulties: Array of DifficultyTop values.
            cycle_frequency: Rotation frequency (weekly or biweekly).
            participation_xp: Flat XP bonus for first submission per cycle.
            placement_xp: JSON array of placement XP tiers.
            streak_xp: JSON array of streak XP thresholds.
            champion_role_id: Discord role ID for category champion.
            conn: Optional connection for transaction support.

        Returns:
            Created category as dict.

        Raises:
            UniqueConstraintViolationError: If category name already exists.
            RepoFKError: If a foreign key reference is invalid.
            CheckConstraintViolationError: If cycle_frequency value is invalid.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.categories (
                name, difficulties, cycle_frequency, participation_xp,
                placement_xp, streak_xp, champion_role_id
            )
            VALUES ($1, $2::text[], $3, $4, $5::jsonb, $6::jsonb, $7)
            RETURNING *
        """
        try:
            row = await _conn.fetchrow(
                query,
                name,
                difficulties,
                cycle_frequency,
                participation_xp,
                placement_xp,
                streak_xp,
                champion_role_id,
            )
            return dict(row) if row else {}
        except UniqueViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise UniqueConstraintViolationError(constraint_name, "tournaments.categories", str(e)) from e
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.categories", str(e)) from e
        except CheckViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise CheckConstraintViolationError(constraint_name, "tournaments.categories", str(e)) from e

    async def fetch_category(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single tournament category by ID.

        Args:
            category_id: Category ID.
            conn: Optional connection for transaction support.

        Returns:
            Category dict or None if not found.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM tournaments.categories WHERE id = $1"
        row = await _conn.fetchrow(query, category_id)
        return dict(row) if row else None

    async def fetch_categories(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all tournament categories.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of category dicts ordered by name.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM tournaments.categories ORDER BY name"
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def update_category(
        self,
        category_id: int,
        updates: dict,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Update a tournament category's fields.

        Args:
            category_id: Category ID to update.
            updates: Dict of field names to new values.
            conn: Optional connection for transaction support.

        Returns:
            Updated category dict, or None if not found.

        Raises:
            UniqueConstraintViolationError: If updated name already exists.
            CheckConstraintViolationError: If cycle_frequency value is invalid.
        """
        if not updates:
            return await self.fetch_category(category_id, conn=conn)
        _conn = self._get_connection(conn)
        jsonb_fields = {"placement_xp", "streak_xp"}
        array_fields = {"difficulties"}
        set_clauses: list[str] = []
        values: list[object] = []
        idx = 1
        for field, value in updates.items():
            if field in jsonb_fields:
                set_clauses.append(f"{field} = ${idx}::jsonb")
            elif field in array_fields:
                set_clauses.append(f"{field} = ${idx}::text[]")
            else:
                set_clauses.append(f"{field} = ${idx}")
            values.append(value)
            idx += 1
        set_clauses.append("updated_at = now()")
        query = f"UPDATE tournaments.categories SET {', '.join(set_clauses)} WHERE id = ${idx} RETURNING *"
        values.append(category_id)
        try:
            row = await _conn.fetchrow(query, *values)
            return dict(row) if row else None
        except UniqueViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise UniqueConstraintViolationError(constraint_name, "tournaments.categories", str(e)) from e
        except CheckViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise CheckConstraintViolationError(constraint_name, "tournaments.categories", str(e)) from e

    async def delete_category(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a tournament category.

        Args:
            category_id: Category ID to delete.
            conn: Optional connection for transaction support.

        Returns:
            True if a category was deleted, False if not found.
        """
        _conn = self._get_connection(conn)
        query = "DELETE FROM tournaments.categories WHERE id = $1 RETURNING id"
        result = await _conn.fetchval(query, category_id)
        return result is not None

    async def check_active_cycle_for_category(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Check if a category has an active or finalizing cycle.

        Args:
            category_id: Category ID to check.
            conn: Optional connection for transaction support.

        Returns:
            Cycle ID if an active or finalizing cycle exists, None otherwise.
        """
        _conn = self._get_connection(conn)
        return await _conn.fetchval(
            """
            SELECT id
            FROM tournaments.cycles
            WHERE category_id = $1 AND status IN ('active', 'finalizing')
            LIMIT 1
            """,
            category_id,
        )

    async def get_active_cycle_by_map_id(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Look up the active tournament cycle for a given map.

        Keyed on ``map_id`` so a normal completion's map can be matched to a
        running tournament cycle without a separate submit step (D-01/D-02).
        Backed by ``idx_cycles_map_id`` (migration 0020).

        Args:
            map_id: Map ID to match against active cycles.
            conn: Optional connection for transaction support.

        Returns:
            Cycle dict (id, category_id, map_id, status) if an active cycle
            exists for this map, None otherwise.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT id, category_id, map_id, status
            FROM tournaments.cycles
            WHERE map_id = $1 AND status = 'active'
            LIMIT 1
            """,
            map_id,
        )
        return dict(row) if row else None

    # =========================================================================
    # Cycles
    # =========================================================================

    async def create_cycle(
        self,
        category_id: int,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Create a new tournament cycle.

        Args:
            category_id: Category this cycle belongs to.
            map_id: Map selected for this cycle.
            conn: Optional connection for transaction support.

        Returns:
            Created cycle as dict.

        Raises:
            RepoFKError: If category_id or map_id doesn't exist.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.cycles (category_id, map_id)
            VALUES ($1, $2)
            RETURNING *
        """
        try:
            row = await _conn.fetchrow(query, category_id, map_id)
            return dict(row) if row else {}
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.cycles", str(e)) from e

    async def fetch_cycle(
        self,
        cycle_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single tournament cycle by ID.

        Args:
            cycle_id: Cycle ID.
            conn: Optional connection for transaction support.

        Returns:
            Cycle dict or None if not found.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM tournaments.cycles WHERE id = $1"
        row = await _conn.fetchrow(query, cycle_id)
        return dict(row) if row else None

    async def fetch_active_cycle(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch the active cycle for a category.

        Args:
            category_id: Category ID.
            conn: Optional connection for transaction support.

        Returns:
            Active cycle dict or None if no active cycle.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT * FROM tournaments.cycles
            WHERE category_id = $1 AND status = 'active'
            LIMIT 1
        """
        row = await _conn.fetchrow(query, category_id)
        return dict(row) if row else None

    async def update_cycle_status(
        self,
        cycle_id: int,
        status: str,
        started_at: object = None,
        ended_at: object = None,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Update a cycle's status and optional timestamps.

        Args:
            cycle_id: Cycle ID to update.
            status: New lifecycle status.
            started_at: Optional started_at timestamp (uses COALESCE to preserve existing).
            ended_at: Optional ended_at timestamp (uses COALESCE to preserve existing).
            conn: Optional connection for transaction support.

        Returns:
            Updated cycle dict, or None if not found.

        Raises:
            CheckConstraintViolationError: If status value is invalid.
        """
        _conn = self._get_connection(conn)
        query = """
            UPDATE tournaments.cycles
            SET status = $2,
                started_at = COALESCE($3, started_at),
                ended_at = COALESCE($4, ended_at)
            WHERE id = $1
            RETURNING *
        """
        try:
            row = await _conn.fetchrow(query, cycle_id, status, started_at, ended_at)
            return dict(row) if row else None
        except CheckViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise CheckConstraintViolationError(constraint_name, "tournaments.cycles", str(e)) from e

    async def fetch_cycle_history(
        self,
        category_id: int,
        limit: int = 20,
        offset: int = 0,
        *,
        conn: Connection | None = None,
    ) -> tuple[int, list[dict]]:
        """Fetch paginated cycle history for a category.

        Args:
            category_id: Category ID.
            limit: Maximum number of results.
            offset: Result offset for pagination.
            conn: Optional connection for transaction support.

        Returns:
            Tuple of (total_count, list of cycle dicts).
        """
        _conn = self._get_connection(conn)
        total = await _conn.fetchval(
            "SELECT COUNT(*) FROM tournaments.cycles WHERE category_id = $1",
            category_id,
        )
        rows = await _conn.fetch(
            """
            SELECT *
            FROM tournaments.cycles
            WHERE category_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            category_id,
            limit,
            offset,
        )
        return total or 0, [dict(row) for row in rows]

    async def fetch_cycles(
        self,
        *,
        status: str | None = None,
        category_id: int | None = None,
        limit: int = 20,
        offset: int = 0,
        conn: Connection | None = None,
    ) -> tuple[int, list[dict]]:
        """Fetch paginated cycles with optional filters and winner info.

        Joins core.maps for map details and uses a LEFT JOIN LATERAL
        subquery to find the rank-1 winner per cycle.

        Args:
            status: Optional cycle status filter.
            category_id: Optional category ID filter.
            limit: Maximum number of results.
            offset: Result offset for pagination.
            conn: Optional connection for transaction support.

        Returns:
            Tuple of (total_count, list of cycle dicts with map and winner info).
        """
        _conn = self._get_connection(conn)

        conditions: list[str] = []
        args: list[object] = []
        idx = 1

        if status is not None:
            conditions.append(f"cy.status = ${idx}")
            args.append(status)
            idx += 1

        if category_id is not None:
            conditions.append(f"cy.category_id = ${idx}")
            args.append(category_id)
            idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        count_query = f"SELECT COUNT(*) FROM tournaments.cycles cy {where_clause}"
        total = await _conn.fetchval(count_query, *args)

        data_query = f"""
            SELECT
                cy.id, cy.category_id, cy.map_id,
                m.code AS map_code, m.map_name, m.difficulty AS map_difficulty,
                cy.status, cy.started_at, cy.ended_at, cy.created_at,
                w.name AS winner_name, w.user_id AS winner_user_id
            FROM tournaments.cycles cy
            JOIN core.maps m ON m.id = cy.map_id
            LEFT JOIN LATERAL (
                SELECT
                    COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
                    bpu.user_id
                FROM (
                    SELECT DISTINCT ON (tc2.user_id)
                        tc2.user_id, tc2.verified, tc2.time
                    FROM tournaments.completions tc2
                    WHERE tc2.cycle_id = cy.id
                    ORDER BY tc2.user_id, tc2.verified DESC, tc2.time ASC
                ) bpu
                JOIN core.users u ON u.id = bpu.user_id
                ORDER BY bpu.verified DESC, bpu.time ASC
                LIMIT 1
            ) w ON TRUE
            {where_clause}
            ORDER BY cy.created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
        """
        args.append(limit)
        args.append(offset)

        rows = await _conn.fetch(data_query, *args)
        return total or 0, [dict(row) for row in rows]

    # =========================================================================
    # Map Selection
    # =========================================================================

    async def fetch_eligible_maps(
        self,
        difficulties: list[str],
        blacklist_weeks: int,
        *,
        exclude_map_ids: list[int] | None = None,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch maps eligible for tournament selection.

        Filters to official, non-archived maps matching the category's
        difficulties, excluding maps used in any tournament cycle within
        the blacklist window and maps in pending cycles.

        Args:
            difficulties: List of DifficultyTop values to match.
            blacklist_weeks: Number of weeks for map cooldown.
            exclude_map_ids: Optional list of map IDs to exclude (for reroll).
            conn: Optional connection for transaction support.

        Returns:
            List of eligible map dicts in random order.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT m.id, m.code, m.map_name, m.difficulty
            FROM core.maps m
            WHERE m.official = TRUE
              AND m.archived = FALSE
              AND m.code IS NOT NULL
              AND regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') = ANY($1)
              AND m.id NOT IN (
                  SELECT cy.map_id
                  FROM tournaments.cycles cy
                  WHERE cy.started_at > now() - make_interval(weeks => $2)
              )
              AND m.id NOT IN (
                  SELECT cy.map_id
                  FROM tournaments.cycles cy
                  WHERE cy.status = 'pending'
              )
        """
        args: list[object] = [difficulties, blacklist_weeks]
        if exclude_map_ids:
            query += "              AND m.id != ALL($3::int[])\n"
            args.append(exclude_map_ids)
        query += "            ORDER BY random()\n"
        rows = await _conn.fetch(query, *args)
        return [dict(row) for row in rows]

    async def fetch_least_recently_used_map(
        self,
        difficulties: list[str],
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch the least recently used eligible map.

        Fallback when the eligible pool is exhausted. Finds the map with
        the oldest (or NULL) started_at in tournament cycles.

        Args:
            difficulties: List of DifficultyTop values to match.
            conn: Optional connection for transaction support.

        Returns:
            Map dict or None if no eligible maps exist.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT m.id, m.code, m.map_name, m.difficulty
            FROM core.maps m
            LEFT JOIN tournaments.cycles cy ON cy.map_id = m.id
            WHERE m.official = TRUE
              AND m.archived = FALSE
              AND m.code IS NOT NULL
              AND regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') = ANY($1)
            ORDER BY cy.started_at ASC NULLS FIRST
            LIMIT 1
        """
        row = await _conn.fetchrow(query, difficulties)
        return dict(row) if row else None

    async def fetch_pending_cycle(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch the pending cycle for a category with joined map details.

        Args:
            category_id: Category ID to look up.
            conn: Optional connection for transaction support.

        Returns:
            Pending cycle dict with map details, or None if no pending cycle.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT cy.id, cy.category_id, cy.map_id, cy.status,
                   cy.started_at, cy.ended_at, cy.created_at,
                   m.code AS map_code, m.map_name, m.difficulty AS map_difficulty
            FROM tournaments.cycles cy
            JOIN core.maps m ON m.id = cy.map_id
            WHERE cy.category_id = $1 AND cy.status = 'pending'
            LIMIT 1
        """
        row = await _conn.fetchrow(query, category_id)
        return dict(row) if row else None

    async def delete_cycle(
        self,
        cycle_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a tournament cycle by ID.

        Args:
            cycle_id: Cycle ID to delete.
            conn: Optional connection for transaction support.

        Returns:
            True if a cycle was deleted, False if not found.
        """
        _conn = self._get_connection(conn)
        query = "DELETE FROM tournaments.cycles WHERE id = $1 RETURNING id"
        result = await _conn.fetchval(query, cycle_id)
        return result is not None

    async def fetch_map_by_code(
        self,
        map_code: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a map from core.maps by its workshop code.

        Args:
            map_code: Workshop code of the map.
            conn: Optional connection for transaction support.

        Returns:
            Map dict with id, code, map_name, difficulty, or None if not found.
        """
        _conn = self._get_connection(conn)
        query = "SELECT id, code, map_name, difficulty FROM core.maps WHERE code = $1"
        row = await _conn.fetchrow(query, map_code)
        return dict(row) if row else None

    # =========================================================================
    # Streaks
    # =========================================================================

    async def fetch_streak(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a user's participation streak.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction support.

        Returns:
            Streak dict or None if no streak record exists.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM tournaments.streaks WHERE user_id = $1"
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def upsert_streak(
        self,
        user_id: int,
        cycle_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Upsert user participation streak.

        Increments current_streak and updates max_streak if exceeded.
        Creates the streak row if it doesn't exist.

        Args:
            user_id: User ID.
            cycle_id: Current cycle ID.
            conn: Optional connection for transaction support.

        Returns:
            Updated streak dict.

        Raises:
            RepoFKError: If user_id or cycle_id doesn't exist.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
            VALUES ($1, 1, 1, $2, now())
            ON CONFLICT (user_id) DO UPDATE SET
                current_streak = tournaments.streaks.current_streak + 1,
                max_streak = GREATEST(tournaments.streaks.max_streak, tournaments.streaks.current_streak + 1),
                last_cycle_id = $2,
                updated_at = now()
            RETURNING user_id, current_streak, max_streak, last_cycle_id, updated_at
        """
        try:
            row = await _conn.fetchrow(query, user_id, cycle_id)
            return dict(row) if row else {}
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.streaks", str(e)) from e

    async def advance_streak(
        self,
        user_id: int,
        cycle_id: int,
        participated: bool,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Advance a user's participation streak for a cycle (reset-capable).

        Unlike upsert_streak (increment-only), this method handles both the
        participant and non-participant paths the 08-03 reset sweep needs:

        - Participant (participated=True): increments current_streak by 1 and
          bumps max_streak via GREATEST, but ONLY when last_cycle_id IS DISTINCT
          FROM the given cycle. This dedupe guard (Pitfall 1) prevents a user who
          played two simultaneous categories from incrementing twice per window.
          last_cycle_id is set to cycle_id either way.
        - Non-participant (participated=False): resets current_streak to 0 and
          sets last_cycle_id to cycle_id.

        Args:
            user_id: User ID.
            cycle_id: Current cycle ID.
            participated: Whether the user submitted in this cycle.
            conn: Optional connection for transaction support.

        Returns:
            Updated streak dict (user_id, current_streak, max_streak,
            last_cycle_id, updated_at).

        Raises:
            RepoFKError: If user_id or cycle_id doesn't exist.
        """
        _conn = self._get_connection(conn)
        if participated:
            query = """
                INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
                VALUES ($1, 1, 1, $2, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    current_streak = CASE
                        WHEN tournaments.streaks.last_cycle_id IS DISTINCT FROM $2
                        THEN tournaments.streaks.current_streak + 1
                        ELSE tournaments.streaks.current_streak
                    END,
                    max_streak = CASE
                        WHEN tournaments.streaks.last_cycle_id IS DISTINCT FROM $2
                        THEN GREATEST(tournaments.streaks.max_streak, tournaments.streaks.current_streak + 1)
                        ELSE tournaments.streaks.max_streak
                    END,
                    last_cycle_id = $2,
                    updated_at = now()
                RETURNING user_id, current_streak, max_streak, last_cycle_id, updated_at
            """
        else:
            query = """
                INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
                VALUES ($1, 0, 0, $2, now())
                ON CONFLICT (user_id) DO UPDATE SET
                    current_streak = 0,
                    last_cycle_id = $2,
                    updated_at = now()
                RETURNING user_id, current_streak, max_streak, last_cycle_id, updated_at
            """
        try:
            row = await _conn.fetchrow(query, user_id, cycle_id)
            return dict(row) if row else {}
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.streaks", str(e)) from e

    async def fetch_all_streak_user_ids(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[int]:
        """Fetch every user_id tracked in tournaments.streaks.

        The 08-03 outbox reset sweep iterates this full tracked-user set and
        subtracts the cycle's participants (in Python) to find non-participants
        whose streaks must reset to 0. No WHERE clause by design.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of user_ids (empty when no streaks exist).
        """
        _conn = self._get_connection(conn)
        query = "SELECT user_id FROM tournaments.streaks"
        rows = await _conn.fetch(query)
        return [r["user_id"] for r in rows]

    # =========================================================================
    # XP Grants (idempotency ledger)
    # =========================================================================

    async def claim_xp_grant(  # noqa: PLR0913
        self,
        cycle_id: int,
        user_id: int,
        reason: str,
        amount: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Idempotently claim an XP-grant ledger row.

        Inserts into tournaments.xp_grants with ON CONFLICT DO NOTHING. The first
        call for a (cycle_id, user_id, reason) wins the claim and returns True; a
        replayed finalization or outbox re-delivery returns False, so the caller
        skips the grant. This is the only real double-grant guard because
        api.xp.grant is in IGNORE_IDEMPOTENCY.

        Args:
            cycle_id: Cycle the grant belongs to.
            user_id: User receiving the grant.
            reason: Grant category (participation, placement, streak).
            amount: XP amount for this claim.
            conn: Optional connection for transaction support.

        Returns:
            True if this call won the claim (first time), False if already claimed.

        Raises:
            RepoFKError: If cycle_id or user_id doesn't exist.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.xp_grants (cycle_id, user_id, reason, amount)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (cycle_id, user_id, reason) DO NOTHING
            RETURNING id
        """
        try:
            row = await _conn.fetchval(query, cycle_id, user_id, reason, amount)
            return row is not None
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.xp_grants", str(e)) from e

    # =========================================================================
    # Completions
    # =========================================================================

    async def create_tournament_completion(  # noqa: PLR0913
        self,
        cycle_id: int,
        user_id: int,
        map_id: int,
        time: float,
        screenshot: str,
        video: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Create a tournament completion record.

        Args:
            cycle_id: Cycle the completion belongs to.
            user_id: User submitting the completion.
            map_id: Map that was completed.
            time: Completion time in seconds.
            screenshot: Screenshot proof URL.
            video: Optional video proof URL.
            conn: Optional connection for transaction support.

        Returns:
            Created tournament completion as dict.

        Raises:
            UniqueConstraintViolationError: If duplicate submission for cycle/user/timestamp.
            RepoFKError: If cycle_id, user_id, or map_id doesn't exist.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.completions (cycle_id, user_id, map_id, time, screenshot, video)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """
        try:
            row = await _conn.fetchrow(query, cycle_id, user_id, map_id, time, screenshot, video)
            return dict(row) if row else {}
        except UniqueViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise UniqueConstraintViolationError(constraint_name, "tournaments.completions", str(e)) from e
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.completions", str(e)) from e

    async def cross_write_to_core(  # noqa: PLR0913
        self,
        tournament_completion_id: int,
        user_id: int,
        map_id: int,
        time: float,
        screenshot: str,
        video: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Conditionally write tournament completion to core.completions.

        Only inserts when tournament time is strictly faster than the user's
        current best non-legacy time for this map. The CTE pre-checks to
        avoid triggering enforce_speed_rules_nonlegacy_only() errors.

        Args:
            tournament_completion_id: ID of the tournament completion record.
            user_id: User ID.
            map_id: Map ID.
            time: Completion time in seconds.
            screenshot: Screenshot proof URL.
            video: Optional video proof URL.
            conn: Optional connection for transaction support.

        Returns:
            The new core.completions ID if inserted, None if skipped (time not faster).
        """
        _conn = self._get_connection(conn)
        query = """
            WITH current_best AS (
                SELECT MIN(c.time) AS best_time
                FROM core.completions c
                WHERE c.user_id = $2
                  AND c.map_id = $3
                  AND c.legacy = FALSE
            ),
            should_insert AS (
                SELECT
                    CASE
                        WHEN cb.best_time IS NULL THEN TRUE
                        WHEN $4 < cb.best_time THEN TRUE
                        ELSE FALSE
                    END AS do_insert
                FROM current_best cb
            ),
            map_flags AS (
                SELECT
                    m.official,
                    (m.playtesting = 'In Progress') AS in_playtest
                FROM core.maps m
                WHERE m.id = $3
            ),
            computed AS (
                SELECT
                    (mf.in_playtest
                     OR $6::text IS NULL OR $6::text = ''
                     OR NOT mf.official) AS completion_flag
                FROM map_flags mf
            )
            INSERT INTO core.completions (
                map_id, user_id, time, screenshot, video,
                completion, tournament_completion_id
            )
            SELECT $3, $2, $4, $5, $6, co.completion_flag, $1
            FROM should_insert si
            CROSS JOIN computed co
            WHERE si.do_insert = TRUE
            RETURNING id
        """
        return await _conn.fetchval(
            query,
            tournament_completion_id,  # $1
            user_id,  # $2
            map_id,  # $3
            time,  # $4
            screenshot,  # $5
            video,  # $6
        )

    async def set_tournament_verified(
        self,
        tournament_completion_id: int,
        verified: bool = True,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Flip a single tournament completion's verified flag (only on a real change).

        Used by BOTH the PB side-effect (inside the completion verify path)
        and the non-PB verify endpoint (D-04a/D-06). The UPDATE is guarded by
        ``verified IS DISTINCT FROM $2`` so a no-op transition (the row is
        already in the target state) matches no row and returns ``None``,
        letting callers distinguish "real transition" from "no change" and
        avoid re-granting XP or re-publishing on redelivery (CR-01/WR-06).

        Args:
            tournament_completion_id: ID of the tournament completion row.
            verified: Target verified value (defaults to True).
            conn: Optional connection for transaction support.

        Returns:
            Dict with id, cycle_id, user_id, time of the updated row when the
            value actually changed, or None when no row matched (row missing OR
            already in the target state). Callers re-fetch to disambiguate.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            UPDATE tournaments.completions
            SET verified = $2
            WHERE id = $1 AND verified IS DISTINCT FROM $2
            RETURNING id, cycle_id, user_id, time
            """,
            tournament_completion_id,
            verified,
        )
        return dict(row) if row else None

    async def fetch_tournament_completion(
        self,
        tournament_completion_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single tournament completion row by ID.

        Used by the non-PB verify/reject endpoints (11-03) to resolve the cycle
        and user before flipping the verified flag and awarding participation XP.

        Args:
            tournament_completion_id: ID of the tournament completion row.
            conn: Optional connection for transaction support.

        Returns:
            Dict with id, cycle_id, user_id, time, verified, or None if no row matched.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT id, cycle_id, user_id, time, verified
            FROM tournaments.completions
            WHERE id = $1
            """,
            tournament_completion_id,
        )
        return dict(row) if row else None

    async def fetch_leaderboard(
        self,
        cycle_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch ranked leaderboard for a tournament cycle.

        Returns best-per-user submissions ranked by tier-then-time:
        verified completions outrank unverified, fastest time wins within tier.

        Args:
            cycle_id: Cycle to fetch leaderboard for.
            conn: Optional connection for transaction support.

        Returns:
            List of ranked leaderboard entry dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            WITH best_per_user AS (
                SELECT DISTINCT ON (tc.user_id)
                    tc.user_id,
                    tc.time,
                    tc.verified,
                    tc.completion
                FROM tournaments.completions tc
                WHERE tc.cycle_id = $1
                ORDER BY tc.user_id, tc.verified DESC, tc.time ASC
            )
            SELECT
                RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)::int AS rank,
                bpu.user_id,
                COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
                bpu.time::float AS time,
                bpu.verified,
                bpu.completion
            FROM best_per_user bpu
            JOIN core.users u ON u.id = bpu.user_id
            ORDER BY bpu.verified DESC, bpu.time ASC
        """
        rows = await _conn.fetch(query, cycle_id)
        return [dict(row) for row in rows]

    async def fetch_user_completion(
        self,
        cycle_id: int,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a user's best tournament completion for a cycle.

        Returns the best submission ranked by verified status then time.

        Args:
            cycle_id: Cycle to look up.
            user_id: User to look up.
            conn: Optional connection for transaction support.

        Returns:
            Best completion dict or None if user hasn't submitted.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT * FROM tournaments.completions
            WHERE cycle_id = $1 AND user_id = $2
            ORDER BY verified DESC, time ASC
            LIMIT 1
        """
        row = await _conn.fetchrow(query, cycle_id, user_id)
        return dict(row) if row else None

    async def fetch_cycle_participants(
        self,
        cycle_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[int]:
        """Fetch the distinct user_ids who submitted in a cycle.

        Drives streak recomputation: participants get their streaks advanced and
        the complement (tracked users not in this set) gets reset to 0 by the
        08-03 sweep.

        Args:
            cycle_id: Cycle to look up.
            conn: Optional connection for transaction support.

        Returns:
            Distinct list of participant user_ids (empty for a zero-participant cycle).
        """
        _conn = self._get_connection(conn)
        query = "SELECT DISTINCT user_id FROM tournaments.completions WHERE cycle_id = $1"
        rows = await _conn.fetch(query, cycle_id)
        return [r["user_id"] for r in rows]

    # =========================================================================
    # Pending Transitions
    # =========================================================================

    async def create_pending_transition(
        self,
        cycle_id: int,
        event_type: str,
        payload: str,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Create a pending transition event for outbox publishing.

        Args:
            cycle_id: Cycle that triggered the transition.
            event_type: Event type (cycle_started or cycle_completed).
            payload: JSON payload for the event.
            conn: Optional connection for transaction support.

        Returns:
            Created transition dict.

        Raises:
            RepoFKError: If cycle_id doesn't exist.
            CheckConstraintViolationError: If event_type value is invalid.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
            VALUES ($1, $2, $3::jsonb)
            RETURNING *
        """
        try:
            row = await _conn.fetchrow(query, cycle_id, event_type, payload)
            return dict(row) if row else {}
        except ForeignKeyViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise RepoFKError(constraint_name, "tournaments.pending_transitions", str(e)) from e
        except CheckViolationError as e:
            constraint_name = extract_constraint_name(e) or "unknown"
            raise CheckConstraintViolationError(constraint_name, "tournaments.pending_transitions", str(e)) from e

    async def fetch_unpublished_transitions(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all unpublished pending transitions, locking the selected rows.

        The query appends ``FOR UPDATE SKIP LOCKED`` so concurrent pollers (e.g.
        multiple API instances) never select the same outbox row. Callers MUST
        invoke this within an open ``conn.transaction()`` for the row lock to be
        meaningful: the lock is held only for the duration of that transaction,
        and the matching ``mark_transition_published`` UPDATE must run in the
        same transaction so the lock survives until the row is marked published.

        Args:
            conn: Optional connection for transaction support. Should be a
                connection inside an open transaction so the row lock holds.

        Returns:
            List of unpublished transition dicts ordered by creation time.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT * FROM tournaments.pending_transitions
            WHERE published = FALSE
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def mark_transition_published(
        self,
        transition_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Mark a pending transition as published.

        Args:
            transition_id: Transition ID to mark.
            conn: Optional connection for transaction support.

        Returns:
            True if a transition was updated, False if not found or already published.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            """
            UPDATE tournaments.pending_transitions
            SET published = TRUE
            WHERE id = $1 AND published = FALSE
            """,
            transition_id,
        )
        return result == "UPDATE 1"


async def provide_tournament_repository(state: State) -> TournamentRepository:
    """Provide TournamentRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        TournamentRepository instance.
    """
    return TournamentRepository(state.db_pool)
