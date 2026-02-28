# `tool_handlers.py` -- MCP tool handler functions

## Overview

`tool_handlers.py` defines the MCP (Model Context Protocol) server's tool functions that are
exposed to LLM clients. It provides three public tool functions -- `get_schema`, `select_rows`,
and `aggregate` -- which allow an LLM to discover the database schema and query the loaded
dataset. The file also contains private helper functions for input validation, response
formatting, date context generation, and query execution with error handling.

All tool functions are async and operate against a `DataStore` instance stored in the MCP
server's lifespan context. They return JSON-serialized strings suitable for consumption by an
LLM.

**Source:** `mcp-server/src/tool_handlers.py`

## Imports and module-level constants

| Import | Purpose |
|--------|---------|
| `json` | Serialize tool responses to JSON strings |
| `logging` | Structured logging via the module-level `logger` |
| `datetime.date` | Compute nominal-day offsets for date context |
| `mcp.server.fastmcp.Context` | MCP request context carrying lifespan state |
| `shared.config.Config` | Centralized configuration store |
| `shared.modules.data.filter_condition.FilterCondition` | Pydantic model for row filter conditions |
| `shared.modules.data.transform_expression.TransformExpression` | Pydantic model for CASE WHEN transform expressions |
| `shared.modules.data.query_result.QueryResult` | Pydantic model wrapping query result rows |
| `data_store.data_store.DataStore` | Abstract base class for the data persistence layer |

### Module-level logger

```python
logger = logging.getLogger(__name__)
```

Standard Python logger scoped to the module name (`tool_handlers`).

---

## Private helper functions

### `_validate_order(order) -> str`

Validates and normalizes a sort-order string.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `order` | `str` | Sort direction. Must be `"asc"` or `"desc"` (case-insensitive). |

**Returns:** `str` -- The lowercased order string (`"asc"` or `"desc"`).

**Raises:** `ValueError` if `order` is not `"asc"` or `"desc"`.

**Example:**

```python
_validate_order("ASC")   # returns "asc"
_validate_order("desc")  # returns "desc"
_validate_order("up")    # raises ValueError: order must be 'asc' or 'desc'
```

---

### `_clamp_limit(limit) -> int`

Clamps a user-supplied limit to the configured bounds `[1, max_query_limit]`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `limit` | `int` | The requested row/group limit. |

**Returns:** `int` -- The clamped limit, guaranteed to be between `1` and `Config.get("mcp_server.max_query_limit")` (default: `100`).

**Example:**

```python
_clamp_limit(50)   # returns 50 (within bounds)
_clamp_limit(0)    # returns 1  (below minimum)
_clamp_limit(500)  # returns 100 (above maximum, clamped to max_query_limit)
```

---

### `_format_query_response(query_result) -> str`

Formats a `QueryResult` into a JSON string for the LLM.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `query_result` | `QueryResult` | The result object from the data store, containing `rows`, `count`, and optionally `total_count`. |

**Returns:** `str` -- A JSON string with the following structure:

```json
{
  "data": [ ... ],
  "count": 5,
  "total_count": 42
}
```

The `total_count` key is only included when `query_result.total_count` is not `None` (i.e., when results were truncated by the limit).

**Example:**

```python
result = QueryResult(columns=["name"], rows=[{"name": "Alice"}], count=1, total_count=10)
_format_query_response(result)
# '{"data": [{"name": "Alice"}], "count": 1, "total_count": 10}'
```

---

### `_build_date_context() -> dict`

Builds a dictionary of date-context metadata used in schema responses. This context tells the
LLM how nominal date columns work, so it can compute ages, durations, and relative date
comparisons.

**Parameters:** None.

**Returns:** `dict` with two keys:

| Key | Type | Description |
|-----|------|-------------|
| `nominal_date_epoch` | `str` | The ISO-format epoch date string (default `"1970-01-01"`) from config. |
| `today_as_nominal_days` | `int` | The number of days between the epoch and today's date. |

**Example:**

```python
# If today is 2026-02-28 and epoch is 1970-01-01:
_build_date_context()
# {
#     "nominal_date_epoch": "1970-01-01",
#     "today_as_nominal_days": 20512
# }
```

---

### `_execute_query(tool_name, coro) -> str`

Awaits a query coroutine and handles errors uniformly for all tool functions.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `tool_name` | `str` | The name of the calling tool, used in log messages (e.g., `"select_rows"`). |
| `coro` | coroutine | An awaitable that resolves to a `QueryResult`. |

**Returns:** `str` -- One of two JSON structures:

On success (delegates to `_format_query_response`):
```json
{"data": [...], "count": 5}
```

On `ValueError` (validation error, logged at WARNING):
```json
{"error": "order must be 'asc' or 'desc'"}
```

On unexpected exception (logged at ERROR with traceback):
```json
{"error": "Internal error: <exception message>"}
```

**Example:**

```python
# Typical usage inside a tool function:
return await _execute_query("select_rows", _query())
```

---

### `_get_data_store(context) -> DataStore`

Extracts the `DataStore` instance from the MCP lifespan context.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `context` | `Context` | The MCP request context object, expected to carry a `"data_store"` key in its `lifespan_context`. |

**Returns:** `DataStore` -- The active data store instance.

**Raises:** `RuntimeError` if the `"data_store"` key is missing or `None` in the lifespan context.

**Example:**

```python
data_store = _get_data_store(context)
schema = await data_store.get_schema()
```

---

## Public tool functions

These async functions are registered as MCP tools and are callable by an LLM client.

### `get_schema(context) -> str`

Returns the database schema including table name, column names, detected types, sample values,
and date context. This is the discovery tool that should be called first before any queries.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `context` | `Context` | Yes | MCP request context (injected by the framework). |

**Returns:** `str` -- A JSON string with one of these shapes:

On success:
```json
{
  "table": "people",
  "date_context": {
    "nominal_date_epoch": "1970-01-01",
    "today_as_nominal_days": 20512
  },
  "columns": [
    {
      "name": "age",
      "detected_type": "numeric",
      "samples": [25, 30, 42]
    },
    {
      "name": "city",
      "detected_type": "text",
      "samples": ["London", "Paris", "Tokyo"]
    }
  ]
}
```

On error (no data loaded):
```json
{"error": "No data loaded"}
```

On unexpected error:
```json
{"error": "Internal error: <message>"}
```

**Behavior:**
1. Retrieves the `DataStore` from the context via `_get_data_store`.
2. Calls `data_store.get_schema()`.
3. If the schema is `None`, returns an error indicating no data is loaded.
4. Otherwise, serializes the table name, date context (from `_build_date_context`), and column
   metadata into a formatted JSON string (indented with 2 spaces).

**Example:**

```python
# Called by the MCP framework when the LLM invokes the get_schema tool:
result = await get_schema(context)
schema = json.loads(result)
print(schema["table"])       # "people"
print(schema["columns"][0])  # {"name": "age", "detected_type": "numeric", "samples": [25, 30, 42]}
```

---

### `select_rows(...) -> str`

Retrieves rows from the data table with optional filtering, sorting, field selection,
deduplication, and conditional transforms.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `filters` | `list[FilterCondition] \| None` | `None` | List of filter conditions. Each has `column`, `operator` (default `"="`), and `value`. |
| `fields` | `list[str] \| None` | `None` | Column names to include in results. `None` returns all columns. |
| `limit` | `int` | `20` | Maximum rows to return. Clamped to `[1, 100]`. |
| `order_by` | `str \| None` | `None` | Column name (or transform alias) to sort by. |
| `order` | `str` | `"asc"` | Sort direction: `"asc"` or `"desc"`. |
| `distinct` | `bool` | `False` | If `True`, return only unique combinations of the selected fields. |
| `transform` | `TransformExpression \| None` | `None` | Conditional math expression (CASE WHEN logic) to compute a derived column. |
| `filter_logic` | `str` | `"AND"` | How multiple filters combine: `"AND"` (all must match) or `"OR"` (any must match). |
| `context` | `Context` | `None` | MCP request context (injected by the framework). |

**Returns:** `str` -- JSON string from `_format_query_response` on success, or a JSON error
object on failure.

Success response:
```json
{
  "data": [
    {"name": "Alice", "age": 30, "city": "London"},
    {"name": "Bob", "age": 25, "city": "Paris"}
  ],
  "count": 2,
  "total_count": 150
}
```

**Behavior:**
1. Extracts the `DataStore` from context.
2. Validates the `order` parameter and clamps the `limit`.
3. Delegates to `data_store.select_rows(...)`.
4. Wraps execution in `_execute_query` for uniform error handling.

**Examples:**

Basic row retrieval:
```python
result = await select_rows(limit=5, context=ctx)
# Returns up to 5 rows with all columns
```

Filtering with multiple conditions (AND logic):
```python
result = await select_rows(
    filters=[
        FilterCondition(column="age", operator=">", value=30),
        FilterCondition(column="city", value="London"),
    ],
    fields=["name", "age", "city"],
    limit=10,
    context=ctx,
)
# Returns people older than 30 who live in London
```

Using OR logic:
```python
result = await select_rows(
    filters=[
        FilterCondition(column="city", value="London"),
        FilterCondition(column="city", value="Paris"),
    ],
    filter_logic="OR",
    context=ctx,
)
# Returns people from London OR Paris
```

LIKE operator for partial matching:
```python
result = await select_rows(
    filters=[
        FilterCondition(column="name", operator="LIKE", value="%son%"),
    ],
    context=ctx,
)
# Returns rows where name contains "son"
```

IN operator:
```python
result = await select_rows(
    filters=[
        FilterCondition(column="city", operator="IN", value=["London", "Paris", "Tokyo"]),
    ],
    context=ctx,
)
# Returns rows where city is one of the listed values
```

Distinct values:
```python
result = await select_rows(
    fields=["city"],
    distinct=True,
    context=ctx,
)
# Returns unique city values
```

Conditional transform (normalizing mixed units):
```python
result = await select_rows(
    transform=TransformExpression(
        source_column="usage_amount",
        cases=[
            TransformCase(
                when=[FilterCondition(column="unit", value="gallons")],
                then_multiply=3.785,
            ),
        ],
        else_multiply=1,
        alias="usage_liters",
    ),
    order_by="usage_liters",
    order="desc",
    context=ctx,
)
# Returns rows with a computed "usage_liters" column, sorted descending
```

---

### `aggregate(...) -> str`

Runs an aggregation operation on the data table with optional grouping, filtering, HAVING
clauses, and conditional transforms.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `operation` | `str` | (required) | Aggregation function: `"count"`, `"sum"`, `"avg"`, `"min"`, or `"max"`. |
| `field` | `str \| None` | `None` | Column to aggregate. Not required for `"count"` or when using `transform`. |
| `group_by` | `str \| list[str] \| None` | `None` | Column(s) to group by. Single string or list for multi-column grouping. |
| `filters` | `list[FilterCondition] \| None` | `None` | Pre-aggregation row filters, same format as `select_rows`. |
| `limit` | `int` | `20` | Maximum groups to return. Clamped to `[1, 100]`. |
| `order_by` | `str \| None` | `None` | Column name or `"@result"` (the aggregated value) to sort by. |
| `order` | `str` | `"desc"` | Sort direction: `"asc"` or `"desc"`. |
| `having_operator` | `str \| None` | `None` | Comparison operator for HAVING filter: `"="`, `"!="`, `">"`, `">="`, `"<"`, `"<="`. |
| `having_value` | `float \| None` | `None` | Threshold for the HAVING filter. |
| `transform` | `TransformExpression \| None` | `None` | Conditional math expression applied before aggregation. |
| `filter_logic` | `str` | `"AND"` | How multiple filters combine: `"AND"` or `"OR"`. |
| `context` | `Context` | `None` | MCP request context (injected by the framework). |

**Returns:** `str` -- JSON string from `_format_query_response` on success, or a JSON error
object on failure.

Success response:
```json
{
  "data": [
    {"city": "London", "result": 42},
    {"city": "Paris", "result": 35}
  ],
  "count": 2
}
```

**Behavior:**
1. Extracts the `DataStore` from context.
2. Validates the `order` parameter and clamps the `limit`.
3. Delegates to `data_store.aggregate(...)`.
4. Wraps execution in `_execute_query` for uniform error handling.

**Examples:**

Simple count:
```python
result = await aggregate(operation="count", context=ctx)
# Returns total row count: {"data": [{"result": 500}], "count": 1}
```

Count grouped by a column:
```python
result = await aggregate(
    operation="count",
    group_by="city",
    order_by="@result",
    order="desc",
    limit=5,
    context=ctx,
)
# Returns top 5 cities by number of people
```

Average with filtering:
```python
result = await aggregate(
    operation="avg",
    field="salary",
    filters=[FilterCondition(column="department", value="Engineering")],
    context=ctx,
)
# Returns average salary in the Engineering department
```

Multi-column grouping:
```python
result = await aggregate(
    operation="count",
    group_by=["city", "department"],
    order_by="@result",
    order="desc",
    context=ctx,
)
# Returns count per city+department combination
```

HAVING clause:
```python
result = await aggregate(
    operation="count",
    group_by="job",
    having_operator=">",
    having_value=5,
    context=ctx,
)
# Returns only job titles held by more than 5 people
```

Transform before aggregation (normalizing mixed units):
```python
result = await aggregate(
    operation="avg",
    transform=TransformExpression(
        source_column="usage_amount",
        cases=[
            TransformCase(
                when=[
                    FilterCondition(column="unit", value="gallons"),
                    FilterCondition(column="frequency", value="Daily"),
                ],
                then_multiply=113.55,
            ),
            TransformCase(
                when=[
                    FilterCondition(column="unit", value="gallons"),
                    FilterCondition(column="frequency", value="Monthly"),
                ],
                then_multiply=3.785,
            ),
        ],
        else_multiply=1,
        alias="monthly_liters",
    ),
    group_by="region",
    order_by="@result",
    order="desc",
    context=ctx,
)
# Returns average monthly usage in liters per region, with unit normalization
```

---

## Key data types reference

These Pydantic models are used as parameter types across the tool functions.

### `FilterCondition`

Represents a single row-level filter.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `column` | `str` | (required) | Column name to filter on. |
| `operator` | `str` | `"="` | One of: `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`. |
| `value` | `str \| int \| float \| list` | `""` | Comparison value. Must be a list for `IN`/`NOT IN`, a string for `LIKE`/`NOT LIKE`. |

### `TransformExpression`

Defines a conditional math expression (CASE WHEN) that computes a derived column.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source_column` | `str` | (required) | Numeric column to transform. |
| `cases` | `list[TransformCase]` | (required) | 1-10 conditional branches. |
| `else_multiply` | `float \| None` | `None` | Default multiplier when no case matches. |
| `else_value` | `float \| None` | `None` | Default constant when no case matches. |
| `alias` | `str` | (required) | Name for the computed column (lowercase alphanumeric + underscores). |

### `TransformCase`

A single branch within a `TransformExpression`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `when` | `list[FilterCondition]` | (required) | All conditions must match for this case to apply. |
| `then_multiply` | `float \| None` | `None` | Multiply the source column by this factor. |
| `then_value` | `float \| None` | `None` | Replace the source column with this constant. |

Exactly one of `then_multiply` or `then_value` must be specified.

### `QueryResult`

The data store's return type for all queries.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `columns` | `list[str]` | (required) | Column names in the result set. |
| `rows` | `list[dict]` | (required) | List of row dictionaries. |
| `count` | `int` | (required) | Number of rows returned. |
| `total_count` | `int \| None` | `None` | Total matching rows before limit was applied (present when results are truncated). |

---

## Configuration dependencies

The following configuration keys from `shared.config.Config` are referenced by this module:

| Key | Default value | Used by |
|-----|---------------|---------|
| `mcp_server.default_query_limit` | `20` | Default `limit` parameter for `select_rows` and `aggregate`. |
| `mcp_server.max_query_limit` | `100` | Upper bound enforced by `_clamp_limit`. |
| `mcp_server.enrichment.nominal_date_epoch` | `"1970-01-01"` | Epoch for nominal-day calculations in `_build_date_context`. |
