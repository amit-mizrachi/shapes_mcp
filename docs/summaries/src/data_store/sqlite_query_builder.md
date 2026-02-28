# `sqlite_query_builder.py` — Parameterized SQLite query construction

## Overview

This module builds parameterized SQLite `SELECT` and aggregate (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`) queries from a validated table schema. It provides SQL-injection-safe query construction by quoting identifiers, validating column names against the schema, and using parameter placeholders (`?`) for all user-supplied values.

The builder also supports computed columns via `CASE WHEN` expressions (called "transforms"), `HAVING` clauses, configurable filter logic (`AND`/`OR`), and multi-column `GROUP BY`.

### Module-level constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `RESULT_ORDER_SENTINEL` | `"@result"` | Pass as `order_by` in `build_aggregate` to order by the aggregation result column instead of a table column. |
| `_AGG_RESULT_ALIAS` | `"result"` | Internal alias applied to every aggregation expression in the generated SQL (e.g. `COUNT(*) AS result`). |

### Dependencies

| Type | Module | Description |
|------|--------|-------------|
| `FilterCondition` | `shared.modules.data.filter_condition` | Pydantic model representing a single filter (`column`, `operator`, `value`). Supported operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`. |
| `TableSchema` | `shared.modules.data.table_schema` | Pydantic model containing `table_name: str` and `columns: list[ColumnInfo]`. |
| `TransformExpression` | `shared.modules.data.transform_expression` | Pydantic model describing a `CASE WHEN` transformation with conditional branches (`TransformCase`) and an optional else clause. |

---

## Classes

### `SelectQuery`

A `NamedTuple` returned by `SqliteQueryBuilder.build_select`. It bundles the main data query and its companion count query together so callers can fetch paginated results and total counts in a single logical operation.

| Field | Type | Description |
|-------|------|-------------|
| `sql` | `str` | The parameterized `SELECT` statement. |
| `params` | `list` | Bind parameters for `sql`. |
| `count_sql` | `str` | A `SELECT COUNT(*)` query with the same filters/distinct settings (no ordering or limit). |
| `count_params` | `list` | Bind parameters for `count_sql`. |

**Example:**

```python
query = builder.build_select(limit=10)
# query.sql        -> 'SELECT * FROM "players" LIMIT ?'
# query.params     -> [10]
# query.count_sql  -> 'SELECT COUNT(*) FROM (SELECT * FROM "players")'
# query.count_params -> []
```

---

### `AggregateQuery`

A `NamedTuple` returned by `SqliteQueryBuilder.build_aggregate`.

| Field | Type | Description |
|-------|------|-------------|
| `sql` | `str` | The parameterized aggregate `SELECT` statement. |
| `params` | `list` | Bind parameters for `sql`. |

**Example:**

```python
query = builder.build_aggregate(operation="sum", field="goals", limit=50)
# query.sql    -> 'SELECT SUM("goals") AS result FROM "players"'
# query.params -> []
```

---

### `SqliteQueryBuilder`

The main class. Constructs parameterized SQL queries validated against a `TableSchema`.

#### Constructor

##### `__init__(self, table_schema: TableSchema) -> None`

Initializes the builder with a table schema. Extracts the set of valid column names for use in all subsequent validation.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `table_schema` | `TableSchema` | Schema describing the target table (name and columns). |

**Example:**

```python
from shared.modules.data.table_schema import TableSchema
from data_store.sqlite_query_builder import SqliteQueryBuilder

schema = TableSchema(
    table_name="players",
    columns=[
        ColumnInfo(name="name", type="TEXT"),
        ColumnInfo(name="goals", type="INTEGER"),
        ColumnInfo(name="team", type="TEXT"),
    ],
)
builder = SqliteQueryBuilder(schema)
```

---

#### Public methods

##### `build_select(*, filters, fields, limit, order_by, order, distinct, transform, filter_logic) -> SelectQuery`

Builds a parameterized `SELECT` query with optional filtering, field selection, ordering, distinct, computed columns, and pagination. Also produces a companion `COUNT(*)` query for total-row counts.

**Parameters (all keyword-only):**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filters` | `Optional[list[FilterCondition]]` | `None` | Row-level filter conditions. |
| `fields` | `Optional[list[str]]` | `None` | Columns to select. `None` selects all (`*`). |
| `limit` | `int` | (required) | Maximum rows to return. |
| `order_by` | `Optional[str]` | `None` | Column (or transform alias) to sort by. |
| `order` | `str` | `"asc"` | Sort direction: `"asc"` or `"desc"`. |
| `distinct` | `bool` | `False` | If `True`, adds `DISTINCT` to the select. |
| `transform` | `Optional[TransformExpression]` | `None` | A `CASE WHEN` expression appended as a computed column. |
| `filter_logic` | `str` | `"AND"` | How to join multiple filters: `"AND"` or `"OR"`. |

**Returns:** `SelectQuery`

**Raises:** `ValueError` if a column name is invalid, order direction is unrecognized, or `filter_logic` is not `AND`/`OR`.

**Example -- basic select:**

```python
query = builder.build_select(limit=20)
# query.sql -> 'SELECT * FROM "players" LIMIT ?'
# query.params -> [20]
```

**Example -- filtered and ordered:**

```python
query = builder.build_select(
    filters=[FilterCondition(column="team", operator="=", value="Arsenal")],
    fields=["name", "goals"],
    order_by="goals",
    order="desc",
    limit=10,
)
# query.sql ->
#   'SELECT "name", "goals" FROM "players" WHERE "team" = ? ORDER BY "goals" DESC LIMIT ?'
# query.params -> ["Arsenal", 10]
```

**Example -- with transform (computed column):**

```python
transform = TransformExpression(
    source_column="goals",
    cases=[
        TransformCase(
            when=[FilterCondition(column="team", operator="=", value="Arsenal")],
            then_multiply=1.5,
        )
    ],
    else_multiply=1.0,
    alias="weighted_goals",
)
query = builder.build_select(
    transform=transform,
    order_by="weighted_goals",
    order="desc",
    limit=5,
)
# The SQL includes:
#   CASE WHEN "team" = ? THEN "goals" * ? ELSE "goals" * ? END AS "weighted_goals"
```

---

##### `build_aggregate(*, operation, field, group_by, filters, limit, order_by, order, having_operator, having_value, transform, filter_logic) -> AggregateQuery`

Builds a parameterized aggregate query. Supports all five standard SQL aggregate functions, optional grouping with `HAVING`, optional transforms, and result-based ordering.

**Parameters (all keyword-only):**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `str` | (required) | One of `"count"`, `"sum"`, `"avg"`, `"min"`, `"max"` (case-insensitive). |
| `field` | `Optional[str]` | `None` | Column to aggregate. Required for all operations except `count`. |
| `group_by` | `Optional[str \| list[str]]` | `None` | Column(s) to group by. |
| `filters` | `Optional[list[FilterCondition]]` | `None` | `WHERE` clause conditions. |
| `limit` | `int` | (required) | Maximum rows (groups) to return. |
| `order_by` | `Optional[str]` | `None` | Column to sort by, or `"@result"` to sort by the aggregation result. |
| `order` | `str` | `"desc"` | Sort direction: `"asc"` or `"desc"`. |
| `having_operator` | `Optional[str]` | `None` | Comparison operator for the `HAVING` clause. One of `=`, `!=`, `>`, `>=`, `<`, `<=`. Defaults to `>=` when `having_value` is set. |
| `having_value` | `Optional[float]` | `None` | Threshold for the `HAVING` clause. Requires `group_by`. |
| `transform` | `Optional[TransformExpression]` | `None` | Apply a `CASE WHEN` expression inside the aggregation function. |
| `filter_logic` | `str` | `"AND"` | How to join multiple filters: `"AND"` or `"OR"`. |

**Returns:** `AggregateQuery`

**Raises:** `ValueError` if the operation is unsupported, `field` is missing for non-count operations, a column name is invalid, or `having` is used without `group_by`.

**Example -- simple count:**

```python
query = builder.build_aggregate(operation="count", limit=1)
# query.sql    -> 'SELECT COUNT(*) AS result FROM "players"'
# query.params -> []
```

**Example -- grouped sum with result ordering:**

```python
query = builder.build_aggregate(
    operation="sum",
    field="goals",
    group_by="team",
    order_by="@result",
    order="desc",
    limit=10,
)
# query.sql ->
#   'SELECT "team", SUM("goals") AS result FROM "players"
#    GROUP BY "team" ORDER BY result DESC LIMIT ?'
# query.params -> [10]
```

**Example -- with HAVING:**

```python
query = builder.build_aggregate(
    operation="avg",
    field="goals",
    group_by="team",
    having_operator=">=",
    having_value=5.0,
    order_by="@result",
    order="desc",
    limit=10,
)
# query.sql ->
#   'SELECT "team", AVG("goals") AS result FROM "players"
#    GROUP BY "team" HAVING result >= ? ORDER BY result DESC LIMIT ?'
# query.params -> [5.0, 10]
```

**Example -- aggregate with transform:**

```python
transform = TransformExpression(
    source_column="goals",
    cases=[
        TransformCase(
            when=[FilterCondition(column="team", operator="=", value="Arsenal")],
            then_multiply=1.5,
        )
    ],
    else_multiply=1.0,
    alias="weighted_goals",
)
query = builder.build_aggregate(
    operation="sum",
    group_by="team",
    transform=transform,
    order_by="@result",
    order="desc",
    limit=10,
)
# The aggregation wraps the CASE expression:
#   SUM(CASE WHEN "team" = ? THEN "goals" * ? ELSE "goals" * ? END) AS result
```

---

#### Private methods

These methods are internal implementation details. They are documented here for completeness.

---

##### `_build_select_columns(self, fields: Optional[list[str]]) -> str`

Returns the column-list portion of a `SELECT` statement. If `fields` is `None` or empty, returns `"*"`. Otherwise, validates each column name against the schema and returns quoted, comma-separated names.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `fields` | `Optional[list[str]]` | Column names to include, or `None` for all. |

**Returns:** `str` -- e.g. `'*'` or `'"name", "goals"'`.

**Raises:** `ValueError` if any field name is not in the schema.

**Example:**

```python
builder._build_select_columns(None)          # -> '*'
builder._build_select_columns(["name"])       # -> '"name"'
builder._build_select_columns(["name", "goals"])  # -> '"name", "goals"'
```

---

##### `_build_where_clause(self, filter_conditions: Optional[list[FilterCondition]], filter_logic: str = "AND") -> tuple[str, list]`

Converts a list of `FilterCondition` objects into a SQL `WHERE` clause string and its associated bind parameters. Individual conditions are joined with the specified logic (`AND` or `OR`).

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filter_conditions` | `Optional[list[FilterCondition]]` | -- | The filters to apply. |
| `filter_logic` | `str` | `"AND"` | Logical joiner: `"AND"` or `"OR"`. |

**Returns:** `tuple[str, list]` -- the clause string (including ` WHERE ` prefix) and the parameter list. Returns `("", [])` when no filters are provided.

**Raises:** `ValueError` if `filter_logic` is not `AND` or `OR`, or if a column is invalid.

**Example:**

```python
clause, params = builder._build_where_clause(
    [
        FilterCondition(column="team", operator="=", value="Arsenal"),
        FilterCondition(column="goals", operator=">", value=5),
    ],
    filter_logic="AND",
)
# clause -> ' WHERE "team" = ? AND "goals" > ?'
# params -> ["Arsenal", 5]
```

---

##### `_validate_transform_columns(self, transform: TransformExpression) -> None`

Validates that the `source_column` and every column referenced inside `transform.cases[*].when[*].column` exists in the schema. Raises `ValueError` on the first invalid column encountered.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `transform` | `TransformExpression` | The transform expression to validate. |

**Returns:** `None`

**Raises:** `ValueError` if any referenced column is not in the schema.

---

##### `_build_case_expression(self, transform: TransformExpression) -> tuple[str, list]`

Generates a SQL `CASE WHEN ... END` expression from a `TransformExpression`. Each `TransformCase` becomes a `WHEN ... THEN ...` branch. The `THEN` clause is either a multiplication (`source_column * ?`) or a constant replacement (`?`), depending on whether `then_multiply` or `then_value` is set.

The `ELSE` clause mirrors this logic using `else_multiply`, `else_value`, or a bare column reference if neither is set.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `transform` | `TransformExpression` | The transform to convert to SQL. |

**Returns:** `tuple[str, list]` -- the `CASE ... END` SQL string (without alias) and the bind parameters.

**Example:**

```python
# Given a transform that doubles Arsenal goals and keeps others unchanged:
case_sql, params = builder._build_case_expression(transform)
# case_sql -> 'CASE WHEN "team" = ? THEN "goals" * ? ELSE "goals" * ? END'
# params   -> ["Arsenal", 2.0, 1.0]
```

---

##### `_validate_order_direction(self, order: str) -> str`

Normalizes and validates a sort direction string.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `order` | `str` | Direction string (case-insensitive). |

**Returns:** `str` -- `"ASC"` or `"DESC"`.

**Raises:** `ValueError` if the input is not `"asc"` or `"desc"` (case-insensitive).

---

##### `_build_order_clause(self, order_by: Optional[str], order: str) -> str`

Builds an ` ORDER BY "column" ASC/DESC` clause. Returns an empty string when `order_by` is `None`.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `order_by` | `Optional[str]` | Column name to order by, or `None`. |
| `order` | `str` | Sort direction. |

**Returns:** `str` -- e.g. `' ORDER BY "goals" DESC'` or `""`.

**Raises:** `ValueError` if the column is not in the schema or the direction is invalid.

---

##### `_normalize_group_by(group_by: Optional[str | list[str]]) -> list[str]` (static)

Normalizes the `group_by` parameter into a consistent `list[str]` form.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `group_by` | `Optional[str \| list[str]]` | A single column name, a list of column names, or `None`. |

**Returns:** `list[str]` -- always a list (empty if input was `None`).

**Example:**

```python
SqliteQueryBuilder._normalize_group_by(None)             # -> []
SqliteQueryBuilder._normalize_group_by("team")           # -> ["team"]
SqliteQueryBuilder._normalize_group_by(["team", "year"]) # -> ["team", "year"]
```

---

##### `_validate_aggregation_op(self, operation: str) -> str`

Validates that `operation` is one of the five supported aggregate functions. Returns the uppercased operation string.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `operation` | `str` | The aggregation function name (case-insensitive). |

**Returns:** `str` -- the uppercased operation, e.g. `"SUM"`.

**Raises:** `ValueError` if the operation is not one of `COUNT`, `SUM`, `AVG`, `MIN`, `MAX`.

---

##### `_validate_aggregation_args(self, operation: str, field: Optional[str], group_by_columns: list[str]) -> str`

Validates the full set of aggregation arguments: the operation name, the field (required for all operations except `COUNT`), and every `group_by` column.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `operation` | `str` | The aggregation function name. |
| `field` | `Optional[str]` | The column to aggregate. |
| `group_by_columns` | `list[str]` | The columns to group by. |

**Returns:** `str` -- the uppercased operation.

**Raises:** `ValueError` if the operation is unsupported, `field` is missing for non-count operations, or any column is invalid.

---

##### `_build_aggregation_expression(self, sql_operation: str, field: Optional[str]) -> str`

Builds the aggregation function call string. `COUNT` always produces `COUNT(*)`. All other operations produce `OPERATION("field")`.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `sql_operation` | `str` | The uppercased operation name. |
| `field` | `Optional[str]` | The column name. |

**Returns:** `str` -- e.g. `'COUNT(*)'` or `'SUM("goals")'`.

---

##### `_build_having_clause(self, having_operator: Optional[str], having_value: Optional[float], group_by_columns: list[str]) -> tuple[str, list]`

Builds a SQL `HAVING` clause for filtering aggregate results.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `having_operator` | `Optional[str]` | Comparison operator. Defaults to `>=` when `having_value` is set. |
| `having_value` | `Optional[float]` | Threshold value. If `None`, no `HAVING` clause is generated. |
| `group_by_columns` | `list[str]` | Required to be non-empty when `having_value` is set. |

**Returns:** `tuple[str, list]` -- e.g. `(' HAVING result >= ?', [5.0])` or `("", [])`.

**Raises:** `ValueError` if `having_value` is set but `group_by_columns` is empty, or if the operator is not in `{=, !=, >, >=, <, <=}`.

**Example:**

```python
clause, params = builder._build_having_clause(">=", 10.0, ["team"])
# clause -> ' HAVING result >= ?'
# params -> [10.0]
```

---

##### `_build_aggregated_sql_query(self, aggregation_expression, where_clause, params, group_by_columns, limit, order_by, order, having_clause, having_params) -> tuple[str, list]`

Assembles the final aggregate SQL string. Behavior differs based on whether `group_by_columns` is empty:

- **Without grouping:** produces a single-row result (no `GROUP BY`, `ORDER BY`, or `LIMIT`).
- **With grouping:** includes `GROUP BY`, optional `HAVING`, `ORDER BY`, and `LIMIT`. When `order_by` equals `RESULT_ORDER_SENTINEL` (`"@result"`), the query orders by the aggregation result alias instead of a table column.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `aggregation_expression` | `str` | The aggregation SQL fragment, e.g. `'SUM("goals")'`. |
| `where_clause` | `str` | The `WHERE` clause string (may be empty). |
| `params` | `list` | Accumulated bind parameters so far. |
| `group_by_columns` | `list[str]` | Columns to group by. |
| `limit` | `int` | Maximum rows to return. |
| `order_by` | `Optional[str]` | Column or `"@result"` sentinel. |
| `order` | `str` | Sort direction. |
| `having_clause` | `str` | The `HAVING` clause string (may be empty). |
| `having_params` | `Optional[list]` | Bind parameters for the `HAVING` clause. |

**Returns:** `tuple[str, list]` -- the complete SQL string and the full parameter list.

---

##### `_validate_column(self, column: str) -> None`

Checks that `column` exists in the schema's column set. This is the single-point-of-truth guard against SQL injection through column names.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `column` | `str` | Column name to validate. |

**Returns:** `None`

**Raises:** `ValueError` with a message listing all valid columns if the name is not found.

**Example:**

```python
builder._validate_column("goals")           # OK, no exception
builder._validate_column("nonexistent")     # raises ValueError
# ValueError: Column 'nonexistent' not found. Valid columns: ['goals', 'name', 'team']
```

---

##### `_filter_to_sql_expression(self, filter_condition: FilterCondition) -> str`

Converts a single `FilterCondition` into a SQL expression fragment (without bind values). Handles six operator categories:

| Operator(s) | SQL output |
|-------------|------------|
| `LIKE`, `NOT LIKE` | `"column" LIKE ?` / `"column" NOT LIKE ?` |
| `IN`, `NOT IN` | `"column" IN (?,?,?)` with the correct number of placeholders |
| `IS NULL` | `"column" IS NULL` (no placeholder) |
| `IS NOT NULL` | `"column" IS NOT NULL` (no placeholder) |
| All others (`=`, `!=`, `>`, `>=`, `<`, `<=`) | `"column" op ?` |

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filter_condition` | `FilterCondition` | The condition to convert. |

**Returns:** `str` -- the SQL fragment.

**Example:**

```python
fc = FilterCondition(column="team", operator="IN", value=["Arsenal", "Chelsea"])
builder._filter_to_sql_expression(fc)
# -> '"team" IN (?,?)'
```

---

##### `_collect_filter_params(filter_condition: FilterCondition, params: list) -> None` (static)

Appends the bind parameters for a single `FilterCondition` to the `params` list. For `IN`/`NOT IN`, it extends the list with every element. For `IS NULL`/`IS NOT NULL`, it appends nothing. For all other operators, it appends the single value.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `filter_condition` | `FilterCondition` | The condition whose value(s) to collect. |
| `params` | `list` | The accumulator list (mutated in place). |

**Returns:** `None`

**Example:**

```python
params = []
fc = FilterCondition(column="team", operator="IN", value=["Arsenal", "Chelsea"])
SqliteQueryBuilder._collect_filter_params(fc, params)
# params -> ["Arsenal", "Chelsea"]

fc2 = FilterCondition(column="goals", operator=">", value=5)
SqliteQueryBuilder._collect_filter_params(fc2, params)
# params -> ["Arsenal", "Chelsea", 5]

fc3 = FilterCondition(column="name", operator="IS NOT NULL")
SqliteQueryBuilder._collect_filter_params(fc3, params)
# params -> ["Arsenal", "Chelsea", 5]  (unchanged)
```
