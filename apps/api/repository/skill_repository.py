"""Repository for skill-score domain database operations.

The only place raw SQL for skill lives: the ported spike 4-CTE input query
(``best -> field -> video_ranked -> fully``), the lean-snapshot read/bulk-upsert,
and the single-row weight config read/write.
"""

from __future__ import annotations

from datetime import datetime

from asyncpg import Connection, Pool
from asyncpg.pool import PoolConnectionProxy
from litestar.datastructures import State

from repository.base import BaseRepository
from services.exceptions.skill import SkillConfigNotSeededError

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

# Population floor (PYO-TIER-06): below this many `skill_score > 0` players the sample is
# too small to mint meaningful percentile boundaries, so tiering is skipped (boundaries are
# persisted empty -> reads treat everyone as Unranked / tier 0).
_TIER_POPULATION_FLOOR = 20


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

    async def fetch_all_snapshots(self, *, conn: Connection | None = None) -> dict[int, dict]:
        """Read every player's prev snapshot score + breakdown in ONE query (D-05).

        Must be callable BEFORE ``replace_snapshot`` TRUNCATEs so the capture wiring
        (Wave 3) has each user's ``previous_score`` and per-map ``contribution`` from the
        OLD snapshot in hand to build the ``score_history`` + ``score_change`` rows (Pitfall 1).
        Single round-trip over ``skill.snapshot`` — never a per-user loop (Pitfall 3). The
        ``breakdown`` jsonb decodes to a Python list automatically via the jsonb<->msgspec
        codec (D-06).

        Args:
            conn: Optional connection for transaction support.

        Returns:
            A dict keyed by ``user_id`` -> ``{"skill_score": float, "breakdown": list}``.
        """
        _conn = self._get_connection(conn)
        rows = await _conn.fetch("SELECT user_id, skill_score, breakdown FROM skill.snapshot")
        return {row["user_id"]: {"skill_score": row["skill_score"], "breakdown": row["breakdown"]} for row in rows}

    async def bulk_insert_history(self, rows: list[dict], *, conn: Connection | None = None) -> None:
        """Append-only bulk insert into ``skill.score_history`` (D-02; NO TRUNCATE).

        Mirrors ``replace_snapshot``'s ``executemany`` + Pool-vs-Connection fork but the
        history table is forward-only — it is NEVER truncated. An empty ``rows`` list is a
        no-op (returns early, same as ``replace_snapshot``). Each dict supplies
        ``user_id, captured_at, skill_score``.

        Args:
            rows: One dict per user-with-data for this recompute.
            conn: Optional connection for transaction support.
        """
        if not rows:
            return

        async def _do_insert(c: Connection | PoolConnectionProxy) -> None:
            # ON CONFLICT DO NOTHING (IN-02): score_history's PK is (user_id, captured_at). Two
            # recomputes that mint the same sub-microsecond captured_at for the same user would
            # otherwise raise a unique violation and abort the whole capture transaction. Dropping
            # the colliding point (rather than failing the rebuild) preserves the forward-only
            # history and keeps the recompute resilient under burst triggers.
            await c.executemany(
                """
                INSERT INTO skill.score_history (user_id, captured_at, skill_score)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, captured_at) DO NOTHING
                """,
                [(r["user_id"], r["captured_at"], r["skill_score"]) for r in rows],
            )

        _conn = self._get_connection(conn)
        if isinstance(_conn, Pool):
            async with _conn.acquire() as acquired:
                await _do_insert(acquired)
        else:
            await _do_insert(_conn)

    async def bulk_insert_changes(self, rows: list[dict], *, conn: Connection | None = None) -> None:
        """Append-only bulk insert into ``skill.score_change`` (D-02; NO TRUNCATE).

        Same forward-only pattern as ``bulk_insert_history``. ``r["diff"]`` is a Python dict
        — the jsonb<->msgspec codec serializes it (same as ``breakdown`` in
        ``replace_snapshot``); do NOT ``json.dumps`` it. Empty ``rows`` is a no-op. Each dict
        supplies ``user_id, captured_at, previous_score, new_score, delta, cause_category,
        reason, diff``.

        Args:
            rows: One dict per user-with-data for this recompute.
            conn: Optional connection for transaction support.
        """
        if not rows:
            return

        async def _do_insert(c: Connection | PoolConnectionProxy) -> None:
            await c.executemany(
                """
                INSERT INTO skill.score_change
                    (user_id, captured_at, previous_score, new_score, delta, cause_category, reason, diff)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                [
                    (
                        r["user_id"],
                        r["captured_at"],
                        r["previous_score"],
                        r["new_score"],
                        r["delta"],
                        r["cause_category"],
                        r["reason"],
                        r["diff"],
                    )
                    for r in rows
                ],
            )

        _conn = self._get_connection(conn)
        if isinstance(_conn, Pool):
            async with _conn.acquire() as acquired:
                await _do_insert(acquired)
        else:
            await _do_insert(_conn)

    async def fetch_weights(self, *, conn: Connection | None = None) -> dict:
        """Read the single weight-config row (SPEC req 5: the only source of weights).

        Args:
            conn: Optional connection for transaction support.

        Returns:
            A dict of exactly the nine weight columns.

        Raises:
            SkillConfigNotSeededError: If the single ``skill.weight_config`` row is missing —
                fails loudly here rather than letting ``msgspec.convert({}, Weights)`` raise an
                opaque ValidationError 500 downstream (WR-03).
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
        if row is None:
            raise SkillConfigNotSeededError("weight_config")
        return dict(row)

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

    async def update_percentiles(self, percentiles: list[float], *, conn: Connection | None = None) -> dict:
        """Replace the single tier-config row's ``percentiles`` array and return the row (U82-TIER-PATCH-01).

        Binds the ``float8[]`` array positionally as ``$1`` — asyncpg encodes a Python
        ``list[float]`` natively, so there is NO string interpolation or array-literal
        building (T-u82-02). Validation (count/range/monotonicity) is the service's job and
        happens before this write; this method only persists. ``boundaries`` is NOT touched
        here — the caller re-derives it via ``compute_tier_boundaries`` on the same connection.

        Args:
            percentiles: The full replacement percentile array.
            conn: Optional connection for transaction support.

        Returns:
            The updated tier-config row as a dict (``boundaries``, ``percentiles``, ``computed_at``).
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            UPDATE skill.tier_config
            SET percentiles = $1
            RETURNING boundaries, percentiles, computed_at
            """,
            percentiles,
        )
        return dict(row) if row else {}

    async def compute_tier_boundaries(self, *, conn: Connection | None = None) -> None:
        """Recompute and persist the percentile tier boundaries from the live snapshot (PYO-TIER-02).

        Reads the configured ``percentiles`` from the single ``skill.tier_config`` row and,
        when at least ``_TIER_POPULATION_FLOOR`` players have ``skill_score > 0``, sets
        ``boundaries`` to the array of ``percentile_cont(p) WITHIN GROUP (ORDER BY skill_score)``
        over those non-zero rows (one cut-point per configured percentile, ascending). Below
        the floor the boundaries are persisted EMPTY (``'{}'``) so ``width_bucket`` is never
        called on a degenerate sample. ``computed_at`` is always refreshed. There are NO
        hardcoded score cutoffs — the seeded percentile array is the only tunable.

        Args:
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        await _conn.execute(
            """
            WITH cfg AS (SELECT percentiles FROM skill.tier_config LIMIT 1),
                 pop AS (SELECT count(*) AS n FROM skill.snapshot WHERE skill_score > 0),
                 b AS (
                     SELECT array(
                         SELECT percentile_cont(u.p) WITHIN GROUP (ORDER BY ss.skill_score)
                         FROM unnest((SELECT percentiles FROM cfg)) WITH ORDINALITY AS u(p, ord)
                         CROSS JOIN skill.snapshot ss
                         WHERE ss.skill_score > 0
                         GROUP BY u.p, u.ord
                         ORDER BY u.ord
                     ) AS boundaries
                 )
            UPDATE skill.tier_config SET
                boundaries = CASE WHEN (SELECT n FROM pop) >= $1
                                  THEN (SELECT boundaries FROM b)
                                  ELSE '{}'::float8[] END,
                computed_at = now()
            """,
            _TIER_POPULATION_FLOOR,
        )

    async def fetch_tier_config(self, *, conn: Connection | None = None) -> dict:
        """Read the single tier-config row for the tier legend (PYO-TIER-05).

        The ``float8[]`` arrays decode to Python ``list[float]`` natively (no codec needed).

        Args:
            conn: Optional connection for transaction support.

        Returns:
            A dict with ``boundaries``, ``percentiles``, and ``computed_at``.

        Raises:
            SkillConfigNotSeededError: If the single ``skill.tier_config`` row is missing —
                fails loudly rather than letting ``msgspec.convert({}, SkillTiersResponse)`` raise
                an opaque ValidationError 500 downstream (WR-03).
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow("SELECT boundaries, percentiles, computed_at FROM skill.tier_config LIMIT 1")
        if row is None:
            raise SkillConfigNotSeededError("tier_config")
        return dict(row)

    async def fetch_snapshot_with_tier(self, user_id: int, *, conn: Connection | None = None) -> dict | None:
        """Fetch a player's snapshot row plus its tier and population percentile (PYO-TIER-03).

        The tier is ``width_bucket(skill_score, boundaries) + 1`` (1..7) against the cached
        boundaries, or 0 (Unranked) when the player has no positive score or the boundaries
        are empty (population floor not met). The percentile is the share of non-zero players
        with a score at or below this player's score.

        Args:
            user_id: Discord user ID to fetch the snapshot for.
            conn: Optional connection for transaction support.

        Returns:
            The snapshot row (with ``tier`` and ``percentile``) as a dict, or None when the
            player has no eligible runs (D-07).
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT ss.*,
                CASE WHEN ss.skill_score <= 0 OR cardinality(tc.boundaries) = 0 THEN 0
                     ELSE width_bucket(ss.skill_score, tc.boundaries) + 1 END AS tier,
                coalesce(
                    (SELECT count(*) FROM skill.snapshot s2
                       WHERE s2.skill_score > 0 AND s2.skill_score <= ss.skill_score)::float8
                    / NULLIF((SELECT count(*) FROM skill.snapshot s3 WHERE s3.skill_score > 0), 0),
                    0.0) AS percentile
            FROM skill.snapshot ss
            CROSS JOIN skill.tier_config tc
            WHERE ss.user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def fetch_history(self, user_id: int, since: datetime, *, conn: Connection | None = None) -> list[dict]:
        """Read a player's windowed score history, oldest-first (SPEC req 3).

        Filters on ``captured_at >= since`` (a timezone-aware datetime the service computes
        from the window; for ``all`` the service passes a far-past sentinel) and orders
        ascending so the line graph plots chronologically. The composite PK
        ``(user_id, captured_at)`` covers this read with no extra index. ``since`` is bound
        positionally (``$2``) — never string-interpolated (T-14-07).

        Args:
            user_id: Discord user ID whose history to read.
            since: Timezone-aware lower bound for ``captured_at`` (inclusive).
            conn: Optional connection for transaction support.

        Returns:
            A list of ``{user_id, captured_at, skill_score}`` dicts, oldest-first.
        """
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT user_id, captured_at, skill_score
            FROM skill.score_history
            WHERE user_id = $1 AND captured_at >= $2
            ORDER BY captured_at ASC
            """,
            user_id,
            since,
        )
        return [dict(r) for r in rows]

    async def fetch_changes(
        self,
        user_id: int,
        since: datetime,
        limit: int,
        offset: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Read a player's newest-first paginated change feed (SPEC req 4).

        Selects ONLY the columns ``SkillChangeFeedItem`` needs — deliberately OMITTING the
        heavy ``diff`` jsonb (Warning 4): the feed never renders the per-map impact array, so
        selecting ``diff`` would force a per-row jsonb deserialization on every paginated page
        for data the feed never uses. The feed's ``description`` is derived in the service from
        ``cause_category``/``reason``. Orders ``captured_at DESC`` (uses the
        ``(user_id, captured_at DESC)`` feed index) and bounds with ``LIMIT``/``OFFSET`` —
        all positional params (T-14-07/T-14-08; the route caps ``limit``). The drill-down
        ``fetch_change`` is the only method that SELECTs ``diff``.

        Args:
            user_id: Discord user ID whose feed to read.
            since: Timezone-aware lower bound for ``captured_at`` (inclusive).
            limit: Max rows to return (route-validated bound).
            offset: Rows to skip for pagination.
            conn: Optional connection for transaction support.

        Returns:
            A list of feed-item dicts (no ``diff``), newest-first.
        """
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT change_id, captured_at, previous_score, new_score, delta, cause_category, reason
            FROM skill.score_change
            WHERE user_id = $1 AND captured_at >= $2
            ORDER BY captured_at DESC
            LIMIT $3 OFFSET $4
            """,
            user_id,
            since,
            limit,
            offset,
        )
        return [dict(r) for r in rows]

    async def fetch_change(self, user_id: int, change_id: int, *, conn: Connection | None = None) -> dict | None:
        """Read a single change with the ownership predicate baked in (SPEC req 5, T-14-06).

        This is the ONLY method that SELECTs ``diff`` (the all-maps impact array, decoded to a
        Python dict via the jsonb<->msgspec codec). The ``WHERE change_id = $1 AND user_id = $2``
        ownership predicate is the IDOR mitigation: a ``change_id`` belonging to another user
        yields no row -> ``None`` -> the route raises 404 (NOT 403 — does not confirm the id's
        existence to a non-owner).

        Args:
            user_id: Discord user ID that must own the change.
            change_id: The change to read.
            conn: Optional connection for transaction support.

        Returns:
            The full change row (including ``diff``) as a dict, or None if no owned row matches.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT change_id, user_id, captured_at, previous_score, new_score, delta,
                   cause_category, reason, diff
            FROM skill.score_change
            WHERE change_id = $1 AND user_id = $2
            """,
            change_id,
            user_id,
        )
        return dict(row) if row else None


async def provide_skill_repository(state: State) -> SkillRepository:
    """Litestar DI provider for SkillRepository."""
    return SkillRepository(state.db_pool)
