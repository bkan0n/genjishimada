"""Repository for skill-score domain database operations.

The only place raw SQL for skill lives: the ported spike 4-CTE input query
(``best -> field -> video_ranked -> fully``), the lean-snapshot read/bulk-upsert,
and the single-row weight config read/write.
"""

from __future__ import annotations

from asyncpg import Connection, Pool
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


async def provide_skill_repository(state: State) -> SkillRepository:
    """Litestar DI provider for SkillRepository."""
    return SkillRepository(state.db_pool)
