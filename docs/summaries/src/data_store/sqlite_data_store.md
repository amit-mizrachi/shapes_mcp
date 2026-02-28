# `sqlite_data_store.py` -- SQLite data store implementation

## Overview

`SqliteDataStore` is a concrete, async implementation of the abstract `DataStore` interface. It provides read-only access to a SQLite database through two primary query patterns: **row selection** and **aggregation**. Every query is built via a companion `SqliteQueryBuilder`, executed over an `aiosqlite` connection, and returned as a `QueryResult`.

The class is designed for a read-only analytics context -- connections are opened with `PRAGMA query_only = ON`, and there are no insert, update, or delete operations.

**Source:** `mcp-server/src/data_store/sqlite_data_store.py`

### Key dependencies

| Dependency | Purpose |
|---|---|
| `aiosqlite` | Async SQLite driver |
| `DataStore` (ABC) | Abstract interface this class implements |
| `SqliteQueryBuilder` | Builds parameterized SQL from structured inputs |
| `Config` | Provides default values for database path and query limits |
| `FilterCondition` | Pydantic model representing a WHERE clause condition |
| `QueryResult` | Pydantic model wrapping query output (columns, rows, count, total_count) |
| `TableSchema` | Pydantic model describing the table's name and columns |
| `TransformExpression` | Pydantic model for CASE WHEN derived-column logic |

---

## Classes

### `SqliteDataStore(DataStore)`

A read-only, async SQLite data store bound to a single table schema. Inherits from the abstract `DataStore` base class and implements all three of its abstract methods: `get_schema`, `select_rows`, and `aggregate`.

---

#### Methods

##### `__init__(database_path: str | None = None, table_schema: TableSchema = None) -> None`

Initialize the data store with a database path and table schema.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `database_path` | `str \| None` | `None` | Absolute path to the SQLite database file. Falls back to `Config.get("mcp_server.db_path")` (default: `/app/db/shapes.db`) when `None`. |
| `table_schema` | `TableSchema` | `None` | Schema describing the target table's name and columns. Passed through to the internal `SqliteQueryBuilder`. |

**Internal state created:**

- `self._db_uri` -- resolved database file path.
- `self._table_schema` -- the table schema used for validation and query building.
- `self._query_builder` -- a `SqliteQueryBuilder` instance bound to the schema.

**Example:**

```python
from shared.modules.data.table_schema import TableSchema
from shared.modules.data.column_info import ColumnInfo

schema = TableSchema(
    table_name="people",
    columns=[
        ColumnInfo(name="id", dtype="INTEGER"),
        ColumnInfo(name="name", dtype="TEXT"),
        ColumnInfo(name="age", dtype="INTEGER"),
    ],
)

store = SqliteDataStore(database_path="/tmp/my_data.db", table_schema=schema)
```

---

##### `async get_schema() -> Optional[TableSchema]`

Return the table schema, or `None` if the schema has no columns.

**Parameters:** None.

**Returns:** `TableSchema | None` -- the schema object when columns exist, otherwise `None`.

**Example:**

```python
schema = await store.get_schema()
if schema:
    print(schema.table_name)
    for col in schema.columns:
        print(f"  {col.name} ({col.dtype})")
```

---

##### `async select_rows(filters, fields, limit, order_by, order, distinct, transform, filter_logic) -> QueryResult`

Query rows from the table with optional filtering, field selection, ordering, deduplication, computed columns, and filter logic.

Internally delegates SQL construction to `SqliteQueryBuilder.build_select()` and then runs the query via `_run_query_with_total`, which also executes a `COUNT(*)` query to populate `total_count` on the result.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `filters` | `list[FilterCondition] \| None` | `None` | WHERE clause conditions. Supports operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`. |
| `fields` | `list[str] \| None` | `None` | Column names to include in the SELECT. `None` selects all columns (`*`). |
| `limit` | `int` | `20` (from config) | Maximum number of rows to return. Configurable default via `mcp_server.default_query_limit`. |
| `order_by` | `str \| None` | `None` | Column name to sort by. Can also be a transform alias when a `transform` is provided. |
| `order` | `str` | `"asc"` | Sort direction. Must be `"asc"` or `"desc"`. |
| `distinct` | `bool` | `False` | When `True`, applies `SELECT DISTINCT`. |
| `transform` | `TransformExpression \| None` | `None` | An optional CASE WHEN expression that creates a computed column (e.g., for unit normalization). |
| `filter_logic` | `str` | `"AND"` | How multiple filters are combined: `"AND"` or `"OR"`. |

**Returns:** `QueryResult` -- contains `columns` (list of column names), `rows` (list of dicts), `count` (number of returned rows), and `total_count` (total matching rows before LIMIT).

**Example:**

```python
from shared.modules.data.filter_condition import FilterCondition

# Select name and age for people older than 30, ordered by age descending
result = await store.select_rows(
    filters=[FilterCondition(column="age", operator=">", value=30)],
    fields=["name", "age"],
    limit=10,
    order_by="age",
    order="desc",
)

print(f"Showing {result.count} of {result.total_count} total matches")
for row in result.rows:
    print(f"  {row['name']}: {row['age']}")
```

**Example with transform:**

```python
from shared.modules.data.transform_expression import TransformExpression, TransformCase
from shared.modules.data.filter_condition import FilterCondition

# Normalize salary to USD using a CASE WHEN expression
transform = TransformExpression(
    source_column="salary",
    cases=[
        TransformCase(
            when=[FilterCondition(column="currency", operator="=", value="EUR")],
            then_multiply=1.08,
        ),
        TransformCase(
            when=[FilterCondition(column="currency", operator="=", value="GBP")],
            then_multiply=1.27,
        ),
    ],
    else_multiply=1.0,
    alias="salary_usd",
)

result = await store.select_rows(
    transform=transform,
    order_by="salary_usd",
    order="desc",
    limit=5,
)
```

**Example with OR filter logic:**

```python
# Find people named "Alice" OR aged 25
result = await store.select_rows(
    filters=[
        FilterCondition(column="name", operator="=", value="Alice"),
        FilterCondition(column="age", operator="=", value=25),
    ],
    filter_logic="OR",
)
```

---

##### `async aggregate(operation, field, group_by, filters, limit, order_by, order, having_operator, having_value, transform, filter_logic) -> QueryResult`

Perform an aggregation query (COUNT, SUM, AVG, MIN, MAX) with optional grouping, filtering, HAVING clause, computed columns, and filter logic.

Internally delegates SQL construction to `SqliteQueryBuilder.build_aggregate()` and then runs the query via `_run_query` (no separate total-count query).

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `operation` | `str` | *(required)* | Aggregation function: `"count"`, `"sum"`, `"avg"`, `"min"`, or `"max"` (case-insensitive). |
| `field` | `str \| None` | `None` | Column to aggregate. Required for all operations except `count`. |
| `group_by` | `str \| list[str] \| None` | `None` | Column(s) to group by. Enables per-group results. |
| `filters` | `list[FilterCondition] \| None` | `None` | WHERE clause conditions applied before aggregation. |
| `limit` | `int` | `20` (from config) | Maximum number of grouped result rows to return. |
| `order_by` | `str \| None` | `None` | Column to sort by. Use the special sentinel `"@result"` to order by the aggregated value itself. |
| `order` | `str` | `"desc"` | Sort direction. Must be `"asc"` or `"desc"`. |
| `having_operator` | `str \| None` | `None` | Comparison operator for the HAVING clause (`=`, `!=`, `>`, `>=`, `<`, `<=`). Defaults to `">="` when `having_value` is set. Requires `group_by`. |
| `having_value` | `float \| None` | `None` | Threshold value for the HAVING clause. |
| `transform` | `TransformExpression \| None` | `None` | An optional CASE WHEN expression. When provided, the aggregation operates on the computed column rather than a raw column. |
| `filter_logic` | `str` | `"AND"` | How multiple filters are combined: `"AND"` or `"OR"`. |

**Returns:** `QueryResult` -- contains `columns`, `rows`, `count`. The `total_count` field is `None` for aggregate queries.

**Example -- simple count:**

```python
result = await store.aggregate(operation="count")
print(f"Total rows: {result.rows[0]['result']}")
```

**Example -- average by group with HAVING:**

```python
# Average age by department, only departments with avg age >= 30
result = await store.aggregate(
    operation="avg",
    field="age",
    group_by="department",
    having_value=30,
    having_operator=">=",
    order_by="@result",
    order="desc",
    limit=10,
)

for row in result.rows:
    print(f"  {row['department']}: avg age = {row['result']:.1f}")
```

**Example -- sum with transform:**

```python
# Sum salaries normalized to USD, grouped by department
result = await store.aggregate(
    operation="sum",
    field="salary_usd",  # not needed when transform is provided
    transform=TransformExpression(
        source_column="salary",
        cases=[
            TransformCase(
                when=[FilterCondition(column="currency", operator="=", value="EUR")],
                then_multiply=1.08,
            ),
        ],
        else_multiply=1.0,
        alias="salary_usd",
    ),
    group_by="department",
    order_by="@result",
    order="desc",
)
```

---

##### `async _run_query_with_total(sql_query: str, params: list, count_sql: str, count_params: list) -> QueryResult`

Execute both a count query and a data query within a single connection, returning a `QueryResult` that includes the `total_count` of matching rows (before LIMIT is applied).

This is used by `select_rows` to provide pagination metadata.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `sql_query` | `str` | The parameterized SELECT statement. |
| `params` | `list` | Bind parameters for the SELECT. |
| `count_sql` | `str` | The parameterized `SELECT COUNT(*)` statement. |
| `count_params` | `list` | Bind parameters for the count query. |

**Returns:** `QueryResult` -- with `total_count` populated from the count query.

**Error handling:** Logs the failed SQL and parameters at `ERROR` level with a full traceback, then re-raises the original exception.

---

##### `async _run_query(sql_query: str, params: list) -> QueryResult`

Execute a single data query within a connection and return the result. Used by `aggregate`, which does not need a separate total-count query.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `sql_query` | `str` | The parameterized SQL statement. |
| `params` | `list` | Bind parameters for the query. |

**Returns:** `QueryResult` -- with `total_count` set to `None`.

**Error handling:** Logs the failed SQL and parameters at `ERROR` level with a full traceback, then re-raises the original exception.

---

##### `async _connection() -> AsyncIterator[aiosqlite.Connection]`

Async context manager that opens a new SQLite connection, configures it for read-only access, sets the row factory to `aiosqlite.Row`, and guarantees the connection is closed on exit.

**Parameters:** None.

**Yields:** `aiosqlite.Connection` -- a configured, read-only connection.

**Key behaviors:**

- Executes `PRAGMA query_only = ON` immediately after opening, ensuring no writes can occur.
- Sets `connection.row_factory = aiosqlite.Row` so fetched rows can be accessed by column name.
- Connection is closed in a `finally` block, ensuring cleanup even on exceptions.

**Example (internal usage):**

```python
async with self._connection() as conn:
    cursor = await conn.execute("SELECT * FROM people LIMIT 5")
    rows = await cursor.fetchall()
```

---

##### `async _execute_query(connection: aiosqlite.Connection, sql_query: str, params: list) -> QueryResult`

Execute a parameterized query on an existing connection and convert the result into a `QueryResult`.

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `connection` | `aiosqlite.Connection` | An open database connection (typically from `_connection()`). |
| `sql_query` | `str` | The parameterized SQL statement. |
| `params` | `list` | Bind parameters for the query. |

**Returns:** `QueryResult` -- with `columns` extracted from `cursor.description`, `rows` as a list of dicts (column-name keys), `count` as the length of the returned rows, and `total_count` set to `None` (caller may override).

**Details:**

1. Executes the query with `connection.execute(sql_query, params)`.
2. Fetches all rows with `cursor.fetchall()`.
3. Extracts column names from `cursor.description`.
4. Converts each row into a `dict` keyed by column name.

---

## Data flow

```
select_rows() / aggregate()
        |
        v
SqliteQueryBuilder.build_select() / build_aggregate()
        |
        v
 _run_query_with_total() / _run_query()
        |
        v
    _connection()          <-- opens read-only aiosqlite connection
        |
        v
    _execute_query()       <-- runs SQL, returns QueryResult
```

## Related types reference

### `QueryResult`

```python
class QueryResult(ShapesBaseModel):
    columns: list[str]       # Column names in result order
    rows: list[dict]         # Each row as {column_name: value}
    count: int               # Number of rows returned
    total_count: int | None  # Total matching rows (before LIMIT); None for aggregates
```

### `FilterCondition`

```python
class FilterCondition(ShapesBaseModel):
    column: str                              # Column name to filter on
    operator: str = "="                      # One of: =, !=, >, >=, <, <=, LIKE, NOT LIKE, IN, NOT IN, IS NULL, IS NOT NULL
    value: str | int | float | list = ""     # Comparison value (list for IN/NOT IN, ignored for IS NULL/IS NOT NULL)
```

### `TableSchema`

```python
class TableSchema(ShapesBaseModel):
    table_name: str              # Name of the database table
    columns: list[ColumnInfo]    # Column definitions
```

### `TransformExpression`

```python
class TransformExpression(ShapesBaseModel):
    source_column: str                   # Numeric column to transform
    cases: list[TransformCase]           # CASE WHEN branches (1-10 allowed)
    else_multiply: float | None = None   # Default multiplier when no case matches
    else_value: float | None = None      # Default constant when no case matches
    alias: str                           # Name for the computed column (lowercase alphanumeric + underscores)
```

### `TransformCase`

```python
class TransformCase(ShapesBaseModel):
    when: list[FilterCondition]          # Conditions that must all match
    then_multiply: float | None = None   # Multiply source column by this factor
    then_value: float | None = None      # Replace source column with this constant
```
