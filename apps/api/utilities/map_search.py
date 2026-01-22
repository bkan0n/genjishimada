from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from textwrap import dedent
from typing import Literal, TypeAlias, cast

import msgspec
from genjishimada_sdk.difficulties import DIFFICULTY_RANGES_ALL, DIFFICULTY_RANGES_TOP, DifficultyTop
from genjishimada_sdk.maps import (
    MapCategory,
    Mechanics,
    OverwatchCode,
    OverwatchMap,
    PlaytestStatus,
    Restrictions,
    SortKey,
    Tags,
)
from sqlspec import SQL, Select, sql
from sqlspec.adapters.asyncpg import default_statement_config

_TriFilter = Literal["All", "With", "Without"]
CompletionFilter = _TriFilter
MedalFilter = _TriFilter
PlaytestFilter = Literal["All", "Only", "None"]
ColumnExpr: TypeAlias = str | SQL
StatementParams: TypeAlias = Mapping[str, object] | Sequence[object] | object | None


class QueryWithArgs(msgspec.Struct):
    """Container for a SQL query string and its bound parameters."""

    query: str
    args: list[object]

    def __iter__(self) -> Iterator[object]:
        """Yield the query string and args for tuple unpacking.

        Yields:
            object: The SQL query string.
            object: The positional argument list for the query.
        """
        yield self.query
        yield self.args


class MapSearchFilters(msgspec.Struct):
    """Filter set for building map search queries."""

    playtesting: PlaytestStatus | None = None
    archived: bool | None = None
    hidden: bool | None = None
    official: bool | None = None
    playtest_thread_id: int | None = None
    code: OverwatchCode | None = None
    category: list[MapCategory] | None = None
    map_name: list[OverwatchMap] | None = None
    sort: list[SortKey] | None = None
    creator_ids: list[int] | None = None
    creator_names: list[str] | None = None
    mechanics: list[Mechanics] | None = None
    restrictions: list[Restrictions] | None = None
    tags: list[Tags] | None = None
    difficulty_exact: DifficultyTop | None = None
    difficulty_range_min: DifficultyTop | None = None
    difficulty_range_max: DifficultyTop | None = None
    finalized_playtests: bool | None = None
    minimum_quality: int | None = None
    user_id: int | None = None
    medal_filter: MedalFilter = "All"
    completion_filter: CompletionFilter = "All"
    playtest_filter: PlaytestFilter = "All"
    return_all: bool = False
    force_filters: bool = False
    page_size: Literal[10, 20, 25, 50, 12] = 10
    page_number: int = 1


class MapSearchSQLSpecBuilder:
    """Build the map search SQL query using SQLSpec primitives.

    This builder uses SQLSpec for structured query assembly and parameter
    binding while keeping the SQL readable and predictable.
    """

    def __init__(self, filters: MapSearchFilters) -> None:
        """Initialize the builder with the given filters.

        Args:
            filters: Filter set that drives CTE, WHERE, and pagination behavior.
        """
        self._filters = filters
        self.validate()

    def validate(self) -> None:
        """Validate filter combinations that are mutually exclusive.

        Raises:
            ValueError: If exact difficulty is combined with a range, or if
                both creator_ids and creator_names are supplied.
        """
        if self._filters.difficulty_exact and (
            self._filters.difficulty_range_min or self._filters.difficulty_range_max
        ):
            raise ValueError("Cannot use exact difficulty with range-based filtering")

        if self._filters.creator_ids and self._filters.creator_names:
            raise ValueError("Cannot use creator_ids and creator_names simultaneously")

    def build(self) -> QueryWithArgs:
        """Compile the SQLSpec query into SQL text and bound parameters.

        Returns:
            QueryWithArgs: The compiled SQL and its positional parameters.
        """
        query = self._build_query()
        if not self._filters.return_all:
            self._apply_pagination(query)
        statement = query.to_statement(config=default_statement_config)
        compiled_sql, compiled_params = statement.compile()
        params = self._normalize_params(cast(StatementParams, compiled_params))
        return QueryWithArgs(compiled_sql, params)

    def _build_query(self) -> Select:
        """Assemble the full SELECT with CTEs, joins, filters, and pagination.

        Returns:
            Select: The SQLSpec Select builder for the query.
        """
        ctes = self._build_ctes()
        query = sql.select()
        columns = self._build_select_columns(query)
        use_intersection = any(name == "intersection_map_ids" for name, _ in ctes)

        query = query.select(*columns)

        for name, cte_query in ctes:
            query = query.with_(name, cte_query)

        if use_intersection:
            query = query.from_("intersection_map_ids", alias="i").join("core.maps", "m.id = i.map_id", alias="m")
        else:
            query = query.from_("core.maps", alias="m")

        query = query.join(
            self._playtest_meta_subquery(),
            on="pm.map_id = m.id AND pm.rn = 1",
            join_type="LEFT",
            alias="pm",
        )

        self._apply_where_clauses(query)

        self._apply_sorting(query)
        return query

    def _apply_sorting(self, query: Select) -> None:
        """Apply ORDER BY clauses based on requested sort keys.

        Args:
            query: Select builder to update with ordering.
        """
        if not self._filters.sort:
            query.order_by("raw_difficulty")
            return

        sort_map: dict[str, str] = {
            "difficulty": "m.raw_difficulty",
            "checkpoints": "m.checkpoints",
            "ratings": "ratings",
            "map_name": "m.map_name",
            "title": "m.title",
            "code": "m.code",
        }
        order_clauses: list[str] = []
        for item in self._filters.sort:
            field, direction = item.split(":", 1)
            column = sort_map[field]
            order_clauses.append(f"{column} {direction.upper()} NULLS FIRST")

        order_clauses.append("m.id ASC")
        query.order_by(*order_clauses)

    def _build_ctes(self) -> list[tuple[str, Select]]:
        """Build the ordered list of CTEs based on active filters.

        Returns:
            list[tuple[str, Select]]: Ordered CTE name/query pairs.
        """
        if self._filters.code and not self._filters.force_filters:
            return []

        ctes: list[tuple[str, Select]] = []

        mechanics_ctes = self._build_mechanics_ctes()
        ctes.extend(mechanics_ctes)

        restrictions_ctes = self._build_restrictions_ctes()
        ctes.extend(restrictions_ctes)

        tags_ctes = self._build_tags_ctes()
        ctes.extend(tags_ctes)

        creator_ids_cte = self._build_creator_ids_cte()
        if creator_ids_cte:
            ctes.append(creator_ids_cte)

        creator_names_ctes = self._build_creator_names_ctes()
        ctes.extend(creator_names_ctes)

        quality_cte = self._build_minimum_quality_cte()
        if quality_cte:
            ctes.append(quality_cte)

        medals_cte = self._build_medals_cte()
        if medals_cte:
            ctes.append(medals_cte)

        completions_cte = self._build_completions_cte()
        if completions_cte:
            ctes.append(completions_cte)

        if ctes:
            intersection = self._build_intersection_cte([name for name, _ in ctes])
            if intersection:
                ctes.append(intersection)

        return ctes

    def _apply_pagination(self, query: Select) -> None:
        """Apply limit/offset pagination to the query builder.

        Args:
            query: Select builder to update with LIMIT/OFFSET.
        """
        page_number = max(1, self._filters.page_number)
        page_size = self._filters.page_size
        offset_value = (page_number - 1) * page_size
        query.limit(page_size).offset(offset_value)

    def _build_mechanics_ctes(self) -> list[tuple[str, Select]]:
        """Restrict to maps containing the provided mechanics.

        Each mechanic yields its own CTE, and all are intersected for AND
        semantics.

        Returns:
            list[tuple[str, Select]]: CTE name/query pairs for each mechanic.
        """
        if not self._filters.mechanics:
            return []
        ctes: list[tuple[str, Select]] = []
        for idx, mechanic in enumerate(self._filters.mechanics):
            query = (
                sql.select("map_id")
                .from_("maps.mechanic_links", alias="ml")
                .join("maps.mechanics", "ml.mechanic_id = m.id", alias="m")
                .where_eq("m.name", mechanic)
            )
            ctes.append((f"mechanic_match_{idx}", query))
        return ctes

    def _build_restrictions_ctes(self) -> list[tuple[str, Select]]:
        """Restrict to maps containing the provided restrictions.

        Each restriction yields its own CTE, and all are intersected for AND
        semantics.

        Returns:
            list[tuple[str, Select]]: CTE name/query pairs for each restriction.
        """
        if not self._filters.restrictions:
            return []
        ctes: list[tuple[str, Select]] = []
        for idx, restriction in enumerate(self._filters.restrictions):
            query = (
                sql.select("map_id")
                .from_("maps.restriction_links", alias="rl")
                .join("maps.restrictions", "rl.restriction_id = r.id", alias="r")
                .where_eq("r.name", restriction)
            )
            ctes.append((f"restriction_match_{idx}", query))
        return ctes

    def _build_tags_ctes(self) -> list[tuple[str, Select]]:
        """Restrict to maps containing the provided tags.

        Each tag yields its own CTE, and all are intersected for AND
        semantics.

        Returns:
            list[tuple[str, Select]]: CTE name/query pairs for each tag.
        """
        if not self._filters.tags:
            return []
        ctes: list[tuple[str, Select]] = []
        for idx, tag in enumerate(self._filters.tags):
            query = (
                sql.select("map_id")
                .from_("maps.tag_links", alias="tl")
                .join("maps.tags", "tl.tag_id = t.id", alias="t")
                .where_eq("t.name", tag)
            )
            ctes.append((f"tag_match_{idx}", query))
        return ctes

    def _build_creator_ids_cte(self) -> tuple[str, Select] | None:
        """Restrict to maps created by specific user IDs.

        Returns:
            tuple[str, Select] | None: CTE name and query, or None if inactive.
        """
        if not self._filters.creator_ids:
            return None
        query = sql.select("map_id").from_("maps.creators", alias="c").where_in("c.user_id", self._filters.creator_ids)
        return "limited_creator_ids", query

    def _build_creator_names_ctes(self) -> list[tuple[str, Select]]:
        """Restrict to maps by creator names across nickname/global/OW usernames.

        Each creator name yields its own CTE, and all are intersected for AND
        semantics.

        Returns:
            list[tuple[str, Select]]: CTE name/query pairs for each name.
        """
        if not self._filters.creator_names:
            return []
        ctes: list[tuple[str, Select]] = []
        for idx, name in enumerate(self._filters.creator_names):
            pattern = f"%{name}%"
            query = (
                sql.select("c.map_id")
                .from_("maps.creators", alias="c")
                .join("core.users", "c.user_id = u.id", alias="u")
                .left_join("users.overwatch_usernames", "u.id = ow.user_id", alias="ow")
                .where_ilike("u.nickname", pattern)
                .or_where_ilike("u.global_name", pattern)
                .or_where_ilike("ow.username", pattern)
            )
            query = query.distinct()
            ctes.append((f"creator_match_{idx}", query))
        return ctes

    def _build_minimum_quality_cte(self) -> tuple[str, Select] | None:
        """Restrict to maps whose average rating meets a minimum threshold.

        Returns:
            tuple[str, Select] | None: CTE name and query, or None if inactive.
        """
        if self._filters.minimum_quality is None:
            return None
        avg_subquery = (
            sql.select("map_id", sql.avg("quality").as_("avg_quality"))
            .from_("maps.ratings")
            .where_eq("verified", True)
            .group_by("map_id")
        )
        query = (
            sql.select("miaq.map_id")
            .from_(avg_subquery, alias="miaq")
            .where_gte("miaq.avg_quality", self._filters.minimum_quality)
        )
        return "limited_quality", query

    def _build_medals_cte(self) -> tuple[str, Select] | None:
        """Restrict to maps with or without medals based on medal_filter.

        Returns:
            tuple[str, Select] | None: CTE name and query, or None if inactive.
        """
        match self._filters.medal_filter:
            case "With":
                return "limited_medals", sql.select("map_id").from_("maps.medals")
            case "Without":
                query = (
                    sql.select("m.id AS map_id")
                    .from_("core.maps", alias="m")
                    .where("NOT EXISTS (SELECT 1 FROM maps.medals med WHERE med.map_id = m.id)")
                )
                return "limited_medals", query
            case _:
                return None

    def _build_completions_cte(self) -> tuple[str, Select] | None:
        """Restrict to maps based on the user's completion status.

        Returns:
            tuple[str, Select] | None: CTE name and query, or None if inactive.
        """
        if not self._filters.user_id:
            return None
        match self._filters.completion_filter:
            case "With":
                query = (
                    sql.select("map_id")
                    .from_("core.completions")
                    .where_eq("user_id", self._filters.user_id)
                    .where_eq("verified", True)
                    .where_eq("legacy", False)
                    .group_by("map_id")
                )
                return "limited_user_completion", query
            case "Without":
                subquery = (
                    sql.select("c.map_id")
                    .from_("core.completions", alias="c")
                    .where_eq("c.user_id", self._filters.user_id)
                    .where_eq("c.verified", True)
                    .where_eq("c.legacy", False)
                )
                query = sql.select("m.id AS map_id").from_("core.maps", alias="m").where_not_in("m.id", subquery)
                return "limited_user_completion", query
            case _:
                return None

    @staticmethod
    def _build_intersection_cte(cte_names: Iterable[str]) -> tuple[str, Select] | None:
        """Combine CTEs via INTERSECT so all filters must match.

        Args:
            cte_names: Ordered CTE names to intersect.

        Returns:
            tuple[str, Select] | None: Intersection CTE or None when empty.
        """
        names = list(cte_names)
        if not names:
            return None
        intersection = sql.select("map_id").from_(names[0])
        for name in names[1:]:
            intersection = intersection.intersect(sql.select("map_id").from_(name))
        return "intersection_map_ids", intersection

    def _apply_where_clauses(self, query: Select) -> None:  # noqa: PLR0912
        """Append WHERE clauses in a stable, predictable order.

        Args:
            query: Select builder to mutate with WHERE conditions.
        """
        if self._filters.code:
            query.where_eq("m.code", self._filters.code)

        if self._filters.playtesting:
            query.where_eq("m.playtesting", self._filters.playtesting)

        match self._filters.playtest_filter:
            case "None":
                query.where_is_null("pm.thread_id")
            case "Only":
                query.where_is_not_null("pm.thread_id")

        if self._filters.difficulty_range_min or self._filters.difficulty_range_max:
            raw_min, raw_max = self._get_raw_difficulty_bounds(
                self._filters.difficulty_range_min,
                self._filters.difficulty_range_max,
            )
            query.where_between("m.raw_difficulty", raw_min, raw_max)

        if self._filters.difficulty_exact:
            top = self._filters.difficulty_exact
            if top == "Hell":
                query.where("m.difficulty = 'Hell'")
            else:
                lo_key = f"{top} -"
                hi_key = f"{top} +"
                raw_min = DIFFICULTY_RANGES_ALL[lo_key][0]  # pyright: ignore[reportArgumentType]
                raw_max = DIFFICULTY_RANGES_ALL[hi_key][1]  # pyright: ignore[reportArgumentType]
                query.where_gte("m.raw_difficulty", raw_min).where_lt("m.raw_difficulty", raw_max)

        if self._filters.archived is not None:
            query.where_eq("m.archived", self._filters.archived)

        if self._filters.hidden is not None:
            query.where_eq("m.hidden", self._filters.hidden)

        if self._filters.official is not None:
            query.where_eq("m.official", self._filters.official)

        if self._filters.map_name:
            query.where_in("m.map_name", self._filters.map_name)

        if self._filters.category:
            query.where_in("m.category", self._filters.category)

        if self._filters.playtest_thread_id:
            query.where_eq("pm.thread_id", self._filters.playtest_thread_id)

        if self._filters.finalized_playtests:
            query.where("pm.verification_id IS NOT NULL AND m.playtesting = 'In Progress'")

    def _build_select_columns(self, query: Select) -> list[ColumnExpr]:
        """Return the SELECT columns for the map search query.

        Args:
            query: Select builder used to register parameters as needed.

        Returns:
            list[ColumnExpr]: Column expressions for the SELECT list.
        """
        columns: list[ColumnExpr] = [
            "m.id",
            "m.code",
            "m.map_name",
            "m.category",
            "m.checkpoints",
            "m.official",
            "m.playtesting",
            "m.archived",
            "m.hidden",
            "m.created_at",
            "m.updated_at",
            "pm.thread_id",
            self._user_completion_time_column(),
            self._ratings_column(),
            self._playtest_json_column(),
            self._creators_json_column(),
            self._guides_array_column(),
            self._medals_json_column(),
            self._mechanics_array_column(),
            self._restrictions_array_column(),
            self._tags_array_column(),
            "m.description",
            "m.raw_difficulty",
            "m.difficulty",
            "m.title",
            "m.linked_code",
            "m.custom_banner AS map_banner",
            "COUNT(*) OVER() AS total_results",
        ]
        return columns

    def _user_completion_time_column(self) -> ColumnExpr:
        """Return a scalar subquery for the user's latest verified completion time.

        Returns:
            ColumnExpr: Scalar subquery aliased as `time`.
        """
        if self._filters.user_id is None:
            return "NULL AS time"

        return SQL(
            dedent(
                """
                (
                    SELECT c.time
                    FROM core.completions c
                    WHERE c.map_id = m.id
                      AND c.user_id = :completion_user_id
                      AND c.verified
                      AND c.legacy = FALSE
                    ORDER BY c.inserted_at DESC
                    LIMIT 1
                ) AS time
                """
            ).strip(),
            {"completion_user_id": self._filters.user_id},
        )

    @staticmethod
    def _playtest_meta_subquery() -> Select:
        """Return the playtest metadata subquery for the LEFT JOIN.

        Returns:
            Select: Subquery providing the latest in-progress metadata per map.
        """
        return (
            sql.select(
                "map_id",
                "thread_id",
                "initial_difficulty",
                "verification_id",
                "created_at",
                "updated_at",
                "completed",
                "ROW_NUMBER() OVER (PARTITION BY map_id ORDER BY created_at DESC) AS rn",
                dialect="postgres",
            )
            .from_("playtests.meta")
            .where("completed IS FALSE")
        )

    @staticmethod
    def _ratings_column() -> str:
        """Return the ratings subquery column.

        Returns:
            str: SQL fragment for the ratings column.
        """
        return "(SELECT avg(quality)::float FROM maps.ratings r WHERE r.map_id = m.id) AS ratings"

    @staticmethod
    def _guides_array_column() -> str:
        """Return the guides array subquery column.

        Returns:
            str: SQL fragment for the guides array column.
        """
        return "(SELECT array_agg(DISTINCT g.url) FROM maps.guides g WHERE g.map_id = m.id) AS guides"

    @staticmethod
    def _playtest_json_column() -> str:
        """Return the playtest JSON blob column.

        Returns:
            str: SQL fragment for the playtest JSON column.
        """
        return dedent(
            """
            CASE WHEN playtesting::text = 'In Progress' and pm.thread_id IS NOT NULL
            THEN
            jsonb_build_object(
                'thread_id', pm.thread_id,
                'initial_difficulty', pm.initial_difficulty,
                'verification_id', pm.verification_id,
                'completed', pm.completed,
                'vote_average', (
                    SELECT avg(difficulty)::float
                    FROM playtests.votes v
                    WHERE v.map_id = m.id
                ),
                'vote_count', (
                    SELECT count(*)
                    FROM playtests.votes v
                    WHERE v.map_id = m.id
                ),
                'voters', (
                    SELECT array_agg(DISTINCT v.user_id)
                    FROM playtests.votes v
                    WHERE v.map_id = m.id
                )
            ) END AS playtest
            """
        ).strip()

    @staticmethod
    def _creators_json_column() -> str:
        """Return the creators JSON blob column.

        Returns:
            str: SQL fragment for the creators JSON column.
        """
        return dedent(
            """
            COALESCE(
                (
                    SELECT jsonb_agg(
                        DISTINCT jsonb_build_object(
                           'id', c.user_id,
                           'is_primary', c.is_primary,
                           'name', coalesce(ow.username, u.nickname, u.global_name, 'Unknown Username')
                       )
                    )
                    FROM maps.creators c
                    JOIN core.users u ON c.user_id = u.id
                    LEFT JOIN users.overwatch_usernames ow ON c.user_id = ow.user_id AND ow.is_primary
                    WHERE c.map_id = m.id
                ),
                '[]'::jsonb
            ) AS creators
            """
        ).strip()

    @staticmethod
    def _medals_json_column() -> str:
        """Return the medals JSON blob column.

        Returns:
            str: SQL fragment for the medals JSON column.
        """
        return dedent(
            """
            (
               SELECT jsonb_build_object(
                   'gold', med.gold,
                   'silver', med.silver,
                   'bronze', med.bronze
               )
               FROM maps.medals med WHERE med.map_id = m.id
            ) AS medals
            """
        ).strip()

    @staticmethod
    def _mechanics_array_column() -> str:
        """Return the mechanics array column with an empty array fallback.

        Returns:
            str: SQL fragment for the mechanics array column.
        """
        return dedent(
            """
            COALESCE((
                SELECT array_agg(DISTINCT mech.name)
                FROM maps.mechanic_links ml
                JOIN maps.mechanics mech ON mech.id = ml.mechanic_id
                WHERE ml.map_id = m.id
            ), ARRAY[]::text[]) AS mechanics
            """
        ).strip()

    @staticmethod
    def _restrictions_array_column() -> str:
        """Return the restrictions array column with an empty array fallback.

        Returns:
            str: SQL fragment for the restrictions array column.
        """
        return dedent(
            """
            COALESCE((
                SELECT array_agg(DISTINCT res.name)
                FROM maps.restriction_links rl
                JOIN maps.restrictions res ON res.id = rl.restriction_id
                WHERE rl.map_id = m.id
            ), ARRAY[]::text[]) AS restrictions
            """
        ).strip()

    @staticmethod
    def _tags_array_column() -> str:
        """Return the tags array column with an empty array fallback.

        Returns:
            str: SQL fragment for the tags array column.
        """
        return dedent(
            """
            COALESCE((
                SELECT array_agg(DISTINCT tag.name)
                FROM maps.tag_links tl
                JOIN maps.tags tag ON tag.id = tl.tag_id
                WHERE tl.map_id = m.id
            ), ARRAY[]::text[]) AS tags
            """
        ).strip()

    @staticmethod
    def _get_raw_difficulty_bounds(
        min_difficulty: DifficultyTop | None, max_difficulty: DifficultyTop | None
    ) -> tuple[float, float]:
        """Convert difficulty labels to raw numeric bounds.

        Args:
            min_difficulty: Lower difficulty label.
            max_difficulty: Upper difficulty label.

        Returns:
            tuple[float, float]: Raw min/max bounds.
        """
        min_key = min_difficulty or "Easy"
        max_key = max_difficulty or "Hell"
        raw_min = DIFFICULTY_RANGES_TOP.get(min_key, (0.0, 0.0))[0]
        raw_max = DIFFICULTY_RANGES_TOP.get(max_key, (10.0, 10.0))[1]
        return raw_min, raw_max

    @staticmethod
    def _normalize_params(compiled_params: StatementParams) -> list[object]:
        """Normalize SQLSpec compiled params into a positional list.

        Args:
            compiled_params: Parameters produced by SQLSpec compilation.

        Returns:
            list[object]: Positional parameter list.
        """
        if compiled_params is None:
            return []
        if isinstance(compiled_params, Mapping):
            return list(compiled_params.values())
        if isinstance(compiled_params, Sequence) and not isinstance(compiled_params, (str, bytes, bytearray)):
            return list(compiled_params)
        return [compiled_params]


if __name__ == "__main__":
    example_filters = MapSearchFilters(
        category=["Classic"],
        map_name=["Hanamura"],
        creator_names=["MashaFF"],
        mechanics=["Bhop", "Dash"],
        restrictions=["Wall Climb"],
        tags=["Other Heroes"],
        difficulty_range_min="Medium",
        difficulty_range_max="Hard",
        page_size=10,
        page_number=1,
    )
    builder = MapSearchSQLSpecBuilder(example_filters)
    _query, args = builder.build()
    print(_query)
    print(args)
