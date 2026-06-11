"""Spike 001 — canonical skill-input query.

Pulls, for every (user, map) pair, the single best verified non-legacy completion plus every
signal a skill score could use. Excludes legacy, unverified, archived-map, and suspicious-flagged
completions. Emits a JSON dataset (skill_inputs.json) that spikes 002 and 003 consume, so the
expensive DB read happens once.

Run:
    uv run --env-file .env.local --with asyncpg python .planning/spikes/001-skill-input-query/query.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg

# One row per (user, map): the player's fastest verified non-legacy time, joined to difficulty,
# medal thresholds, and the field (everyone else's best time on that map) so we can compute a
# time-percentile. `completion = FALSE` => fully-verified (video); `completion = TRUE` => partial.
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


async def main() -> None:
    conn = await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )
    rows = [dict(r) for r in await conn.fetch(SKILL_INPUT_QUERY)]
    await conn.close()

    # drop suspicious-flagged rows entirely (score 0 / excluded per requirements)
    clean = [r for r in rows if not r["suspicious"]]
    dropped = len(rows) - len(clean)

    out = Path(__file__).parent / "skill_inputs.json"
    out.write_text(json.dumps(clean, indent=0))

    users = {r["user_id"] for r in clean}
    maps = {r["map_id"] for r in clean}
    fully = [r for r in clean if r["fully_verified"]]
    with_pct = [r for r in clean if r["field_size"] >= 3]
    medals = [r for r in clean if r["medal"]]
    wrs = [r for r in clean if r["video_rank"] == 1]

    print(f"rows (best per user/map) ........ {len(clean)}  ({dropped} suspicious dropped)")
    print(f"distinct players ................ {len(users)}")
    print(f"distinct maps ................... {len(maps)}")
    print(f"fully-verified (video) rows ..... {len(fully)}  ({len({r['user_id'] for r in fully})} players)")
    print(f"time-pct computable (field>=3) .. {len(with_pct)}  ({len(with_pct) / len(clean):.1%})")
    print(f"medal-earning rows .............. {len(medals)}")
    print(f"world-record rows (video_rank=1)  {len(wrs)}")
    print(f"\nwrote {out.relative_to(Path.cwd())}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    asyncio.run(main())
