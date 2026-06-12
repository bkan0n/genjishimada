"""Repository for skill-score domain database operations.

The only place raw SQL for skill lives: the ported spike 4-CTE input query
(``best -> field -> video_ranked -> fully``), the lean-snapshot read/bulk-upsert,
and the single-row weight config read/write.
"""

from __future__ import annotations

from asyncpg import Connection, Pool
from asyncpg.pool import PoolConnectionProxy
from litestar.datastructures import State

from repository.base import BaseRepository

# Verbatim port of the spike input query (sources/001-skill-input-query/query.py:24-92).
# One row per (user, map): the player's fastest verified, non-legacy completion joined to
# difficulty, medal thresholds, and the map's field, carrying every signal the scorer uses.
#
# Load-bearing gotchas preserved exactly from the spike:
#   - `completion = TRUE`  => partially verified (screenshot/playtest, no video).
#     `completion = FALSE` => fully verified (video proof; ranked + medal-eligible).
#   - window-function row-filtering is INVALID in Postgres (it is an aggregate-only
#     clause), so the video set is ranked in its OWN `video_ranked` CTE and LEFT JOINed back.
#   - `raw_difficulty::float8` (0-10 numeric), never the text tier.
#   - `time_pct` (percent_rank, field-relative; 1.0 = fastest) — NEVER compare raw time across maps.
#   - eligibility WHERE (SPEC req 3): verified, non-legacy, non-archived, code present.
SKILL_INPUT_QUERY = """
WITH best AS (
    -- fastest verified, non-legacy completion per (user, map), on non-archived maps
    SELECT DISTINCT ON (c.user_id, c.map_id)
        c.user_id, c.map_id, c.time, c.completion, c.id AS completion_id, c.message_id
    FROM core.completions c
    JOIN core.maps m ON m.id = c.map_id
    WHERE c.verified = TRUE
      AND c.legacy = FALSE
      AND m.archived = FALSE
      AND m.code IS NOT NULL
    ORDER BY c.user_id, c.map_id, c.time ASC
),
field AS (
    -- rank within each map's field by time; percentile of 1.0 == fastest in field
    SELECT b.*,
        count(*)      OVER (PARTITION BY b.map_id)                       AS field_size,
        percent_rank() OVER (PARTITION BY b.map_id ORDER BY b.time DESC) AS time_pct,
        rank()         OVER (PARTITION BY b.map_id ORDER BY b.time ASC)  AS field_rank
    FROM best b
),
-- fully-verified-only ranking: leaderboard rank / WR are meaningful only with video proof.
-- (Window funcs don't take FILTER, so rank the video-only set in its own CTE and join back.)
video_ranked AS (
    SELECT b.user_id, b.map_id,
        rank() OVER (PARTITION BY b.map_id ORDER BY b.time ASC) AS video_rank
    FROM best b
    WHERE b.completion = FALSE
),
fully AS (
    SELECT f.*, vr.video_rank
    FROM field f
    LEFT JOIN video_ranked vr ON vr.user_id = f.user_id AND vr.map_id = f.map_id
)
SELECT
    f.user_id,
    coalesce(nullif(max(owu.username) FILTER (WHERE owu.is_primary), ''),
             nullif(u.nickname, ''), nullif(u.global_name, ''), 'User ' || f.user_id::text) AS name,
    f.map_id,
    m.code,
    m.map_name,
    m.difficulty,
    m.raw_difficulty::float8 AS raw_difficulty,
    f.time::float8           AS time,
    f.completion,
    (f.completion = FALSE)   AS fully_verified,        -- has video proof
    f.field_size,
    f.field_rank,
    f.video_rank,                                       -- leaderboard rank among video runs (NULL if partial)
    round(f.time_pct::numeric, 4)::float8 AS time_pct,  -- 1.0 = fastest in field, 0.0 = slowest
    -- absolute medal thresholds (skill medals): a real skill signal on ANY time, but per the
    -- hybrid model the scorer only *credits* medals on fully-verified runs.
    CASE
        WHEN md.gold   IS NOT NULL AND f.time <= md.gold   THEN 'Gold'
        WHEN md.silver IS NOT NULL AND f.time <= md.silver THEN 'Silver'
        WHEN md.bronze IS NOT NULL AND f.time <= md.bronze THEN 'Bronze'
    END AS medal,
    (md.map_id IS NOT NULL) AS has_medal_thresholds,
    EXISTS (SELECT 1 FROM users.suspicious_flags sf WHERE sf.completion_id = f.completion_id) AS suspicious
FROM fully f
JOIN core.maps m ON m.id = f.map_id
JOIN core.users u ON u.id = f.user_id
LEFT JOIN users.overwatch_usernames owu ON owu.user_id = f.user_id
LEFT JOIN maps.medals md ON md.map_id = f.map_id
GROUP BY f.user_id, f.map_id, m.code, m.map_name, m.difficulty, m.raw_difficulty, f.time,
         f.completion, f.field_size, f.field_rank, f.video_rank, f.time_pct,
         md.gold, md.silver, md.bronze, md.map_id, f.completion_id, u.nickname, u.global_name
ORDER BY f.user_id, m.raw_difficulty DESC
"""

# Allow-list of the nine weight columns (D-09). A partial PATCH (D-10) may only set
# these names — the UPDATE SET clause is built exclusively from this set, never from
# arbitrary caller-supplied keys (T-13-07).
_WEIGHT_COLUMNS = frozenset(
    {
        "diff_base",
        "gamma",
        "time_bonus",
        "shrink_k",
        "wr_bonus",
        "partial_factor",
        "medal_gold",
        "medal_silver",
        "medal_bronze",
    }
)


class SkillRepository(BaseRepository):
    """Repository for the skill-score domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def fetch_skill_inputs(self, *, conn: Connection | None = None) -> list[dict]:
        """Fetch one fastest eligible run per (user, map) with every scoring signal.

        Runs the ported spike 4-CTE input query and drops suspicious-flagged rows in
        Python (mirroring the spike harness: suspicious users contribute nothing,
        SPEC req 3). Each remaining row carries ``raw_difficulty``, ``time``,
        ``fully_verified``, ``field_size``, ``field_rank``, ``video_rank``,
        ``time_pct`` (1.0 = fastest), ``medal``, ``has_medal_thresholds``.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of eligible skill-input rows as dicts, suspicious rows excluded.
        """
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(SKILL_INPUT_QUERY)
        return [dict(row) for row in rows if not row["suspicious"]]

    async def snapshot_is_empty(self, *, conn: Connection | None = None) -> bool:
        """Report whether the lean snapshot cache holds zero rows.

        Used by the app-side poller to decide whether to run the one-time initial
        population on startup (cold-start fix): a fresh DB, a post-truncate state, or
        a DB with no eligible players all read as empty. Uses a ``NOT EXISTS`` probe so
        the query short-circuits on the first row instead of counting the whole table.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            True if ``skill.snapshot`` has no rows, otherwise False.
        """
        _conn = self._get_connection(conn)
        return await _conn.fetchval("SELECT NOT EXISTS (SELECT 1 FROM skill.snapshot)")

    async def fetch_snapshot(self, user_id: int, *, conn: Connection | None = None) -> dict | None:
        """Fetch a single player's lean snapshot row.

        The ``breakdown`` jsonb column decodes to a Python list automatically via the
        app's jsonb<->msgspec codec (D-06); no manual JSON handling.

        Args:
            user_id: Discord user ID to fetch the snapshot for.
            conn: Optional connection for transaction support.

        Returns:
            The snapshot row as a dict, or None if the player has no eligible runs (D-07).
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow("SELECT * FROM skill.snapshot WHERE user_id = $1", user_id)
        return dict(row) if row else None

    async def replace_snapshot(self, rows: list[dict], *, conn: Connection | None = None) -> None:
        """Atomically replace the entire lean snapshot with the supplied rows (D-04/D-07).

        Runs inside a single transaction: TRUNCATE then bulk-insert. An empty ``rows``
        list leaves the snapshot empty (truncate only) without error. Each dict supplies
        ``user_id, skill_score, maps_cleared, video_clears, hardest_raw, breakdown,
        computed_at``; the ``breakdown`` value is a Python list serialized by the
        jsonb codec (app.py:132).

        Args:
            rows: The full new snapshot — one dict per player with an eligible run.
            conn: Optional connection for transaction support.
        """

        async def _do_replace(c: Connection | PoolConnectionProxy) -> None:
            async with c.transaction():
                await c.execute("TRUNCATE skill.snapshot")
                if not rows:
                    return
                await c.executemany(
                    """
                    INSERT INTO skill.snapshot
                        (user_id, skill_score, maps_cleared, video_clears, hardest_raw, breakdown, computed_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    [
                        (
                            r["user_id"],
                            r["skill_score"],
                            r["maps_cleared"],
                            r["video_clears"],
                            r["hardest_raw"],
                            r["breakdown"],
                            r["computed_at"],
                        )
                        for r in rows
                    ],
                )

        _conn = self._get_connection(conn)
        if isinstance(_conn, Pool):
            async with _conn.acquire() as acquired:
                await _do_replace(acquired)
        else:
            await _do_replace(_conn)

    async def fetch_weights(self, *, conn: Connection | None = None) -> dict:
        """Read the single weight-config row (SPEC req 5: the only source of weights).

        Args:
            conn: Optional connection for transaction support.

        Returns:
            A dict of exactly the nine weight columns.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT diff_base, gamma, time_bonus, shrink_k, wr_bonus, partial_factor,
                   medal_gold, medal_silver, medal_bronze
            FROM skill.weight_config
            LIMIT 1
            """
        )
        return dict(row) if row else {}

    async def update_weights(self, weights: dict, *, conn: Connection | None = None) -> dict:
        """Partial-update the single weight-config row (D-10) and return the full row.

        The SET clause is built from an allow-list of the nine known weight columns
        (T-13-07: never arbitrary caller-supplied column names); values are bound
        positionally. An empty/all-unknown update returns the current row unchanged.

        Args:
            weights: Mapping of weight column name -> new value (partial PATCH).
            conn: Optional connection for transaction support.

        Returns:
            The full updated weight-config row as a dict.
        """
        _conn = self._get_connection(conn)
        updates = {k: v for k, v in weights.items() if k in _WEIGHT_COLUMNS}
        if not updates:
            return await self.fetch_weights(conn=conn)
        columns = list(updates)
        set_clause = ", ".join(f"{col} = ${i}" for i, col in enumerate(columns, start=1))
        row = await _conn.fetchrow(
            f"""
            UPDATE skill.weight_config
            SET {set_clause}
            RETURNING diff_base, gamma, time_bonus, shrink_k, wr_bonus, partial_factor,
                      medal_gold, medal_silver, medal_bronze
            """,
            *(updates[col] for col in columns),
        )
        return dict(row) if row else {}


async def provide_skill_repository(state: State) -> SkillRepository:
    """Litestar DI provider for SkillRepository."""
    return SkillRepository(state.db_pool)
