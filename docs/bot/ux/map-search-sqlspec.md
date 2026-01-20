# Map Search SQL Builder (SQLSpec)

This guide documents the SQLSpec-based map search query builder used by the API
map search flow. It is designed to be readable, stable, and easy to extend.

## Location

- Builder: `apps/api/utilities/map_search.py`

## How the query is built

The builder composes a single SELECT statement that can include:

1. Filter-driven CTEs
2. An `intersection_map_ids` CTE (AND semantics across CTE filters)
3. A main SELECT with core map fields and computed columns
4. A `LEFT JOIN LATERAL` to the latest incomplete playtest meta row
5. WHERE filters, ordered for stability
6. ORDER BY and pagination

## CTE model

CTEs are built in a fixed order to keep the SQL predictable and ensure filter
interactions are consistent:

1. mechanics
2. restrictions
3. creator_ids
4. creator_names (one CTE per name, then intersected)
5. minimum_quality
6. medals
7. completions

If any CTEs are active, they are intersected via:

```
intersection_map_ids AS (
    SELECT map_id FROM cte_1
    INTERSECT
    SELECT map_id FROM cte_2
    ...
)
```

When `filters.code` is set and `filters.force_filters` is `False`, CTEs are
skipped. This allows fast, direct lookups by map code.

## WHERE clause ordering

The WHERE clause is appended in a consistent order. Add new conditions at the
end unless the new filter must appear earlier to preserve parameter ordering or
execution characteristics.

Current order:

1. code
2. playtesting
3. playtest_filter (thread_id NULL / NOT NULL)
4. difficulty range
5. difficulty exact
6. archived
7. hidden
8. official
9. map_name
10. category
11. playtest_thread_id
12. finalized_playtests

## SELECT columns

The SELECT list is intentionally stable. Do not reorder columns unless you have
an API-level reason to do so. It includes:

- Core map fields (`m.*` subset)
- `pm.thread_id` from the lateral join
- `time` subquery for user completion time
- Ratings, playtest JSON, creators JSON, guides array, medals JSON
- Mechanics and restrictions arrays (COALESCE with empty arrays)
- `COUNT(*) OVER() AS total_results`

Most computed columns are raw SQL fragments to keep the output stable and avoid
sqlglot rewriting.

## Pagination

Pagination uses SQLSpec's `paginate()` helper on the compiled SQL statement.

- When `filters.return_all` is `True`, pagination is skipped.

## Parameter ordering

Parameters are registered as the query is assembled. If you introduce new
parameters, add them at a point in the build process that keeps the order
stable and predictable.

## Adding a new filter

1. Add a field to `MapSearchFilters`.
2. Decide whether it belongs in:
   - a CTE (set-based filtering), or
   - the WHERE clause (direct filtering).
3. Implement the CTE in `_build_ctes()` or add the WHERE condition in
   `_apply_where_clauses()`.

Use a CTE if the filter should participate in the intersection behavior with
other set-based filters.

## Adding a new column

1. Add a helper method that returns a SQL fragment or expression.
2. Add it to `_build_select_columns()` in the correct position.
3. If the column needs parameters, register them on the query with
   `query.add_parameter()` and use placeholders in the fragment.

## Adding a new intersection source

If a new filter should participate in the `intersection_map_ids` CTE:

1. Add the CTE builder method.
2. Register it in `_build_ctes()` in the correct order.
3. Ensure its output is `SELECT map_id ...` so the intersection works without
   additional transformations.
