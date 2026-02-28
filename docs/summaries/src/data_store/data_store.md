# `data_store.py` -- Abstract data store interface

## Overview

`data_store.py` defines `DataStore`, an abstract base class (ABC) that establishes the contract for all data access operations in the MCP server. Any storage backend (SQLite, PostgreSQL, etc.) must implement this interface to be usable by the system.

The module lives at `mcp-server/src/data_store/data_store.py` and depends on four shared data models:

| Type | Module | Purpose |
|------|--------|---------|
| `FilterCondition` | `shared.modules.data.filter_condition` | Describes a single column filter (column, operator, value) |
| `TableSchema` | `shared.modules.data.table_schema` | Holds table name and a list of `ColumnInfo` objects |
| `QueryResult` | `shared.modules.data.query_result` | Wraps query output: column names, row dicts, counts |
| `TransformExpression` | `shared.modules.data.transform_expression` | Conditional CASE WHEN logic for derived/computed columns |

The only concrete implementation shipped today is `SqliteDataStore` in `data_store/sqlite_data_store.py`.

---

## Classes

### `DataStore`

```python
class DataStore(ABC)
```

Abstract base class that every data store backend must subclass. It declares three abstract async methods: `get_schema`, `select_rows`, and `aggregate`. All methods are async because data access is expected to involve I/O (database connections, network calls, etc.).

Because `DataStore` inherits from `ABC`, Python raises `TypeError` at instantiation time if a subclass does not implement every `@abstractmethod`.

---

#### Methods

##### `get_schema() -> TableSchema | None`

```python
@abstractmethod
async def get_schema(self) -> TableSchema | None
```

Retrieve the schema of the underlying data source.

**Parameters:** None.

**Returns:**
- `TableSchema` -- An immutable Pydantic model containing:
  - `table_name: str` -- Name of the table.
  - `columns: list[ColumnInfo]` -- List of column descriptors, each with `name`, `detected_type`, and optional `samples`.
- `None` -- When no schema is available (e.g., the table has no columns or the source has not been initialized).

**Example:**

```python
class SqliteDataStore(DataStore):
    async def get_schema(self) -> TableSchema | None:
        if not self._table_schema.columns:
            return None
        return self._table_schema

# Usage
store: DataStore = SqliteDataStore(database_path="data.db", table_schema=schema)
schema = await store.get_schema()

if schema:
    for col in schema.columns:
        print(f"{col.name} ({col.detected_type})")
```

---

##### `select_rows(filters, fields, limit, order_by, order, distinct, transform, filter_logic) -> QueryResult`

```python
@abstractmethod
async def select_rows(
    self,
    filters: list[FilterCondition] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
    order_by: str | None = None,
    order: str = "asc",
    distinct: bool = False,
    transform: TransformExpression | None = None,
    filter_logic: str = "AND",
) -> QueryResult
```

Retrieve rows from the data source with optional filtering, projection, ordering, deduplication, and column transformation.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `filters` | `list[FilterCondition] \| None` | `None` | List of filter conditions to apply. Each condition specifies a `column`, an `operator` (one of `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`), and a `value`. |
| `fields` | `list[str] \| None` | `None` | Column names to include in the result. `None` means all columns. |
| `limit` | `int` | `20` | Maximum number of rows to return. |
| `order_by` | `str \| None` | `None` | Column name to sort results by. |
| `order` | `str` | `"asc"` | Sort direction: `"asc"` or `"desc"`. |
| `distinct` | `bool` | `False` | When `True`, return only unique rows. |
| `transform` | `TransformExpression \| None` | `None` | A computed column expression using CASE WHEN logic. Useful for normalizing units, currencies, or categories before selecting. |
| `filter_logic` | `str` | `"AND"` | How to combine multiple filters: `"AND"` (all must match) or `"OR"` (any must match). |

**Returns:**
- `QueryResult` -- An immutable Pydantic model containing:
  - `columns: list[str]` -- Column names in the result set.
  - `rows: list[dict]` -- Each row as a dictionary mapping column names to values.
  - `count: int` -- Number of rows returned.
  - `total_count: int | None` -- Total matching rows before the limit was applied (when supported by the implementation).

**Example:**

```python
from shared.modules.data.filter_condition import FilterCondition

# Select specific fields with a filter
result = await store.select_rows(
    filters=[
        FilterCondition(column="status", operator="=", value="active"),
        FilterCondition(column="price", operator=">", value=100),
    ],
    fields=["name", "price", "status"],
    limit=10,
    order_by="price",
    order="desc",
)

print(f"Showing {result.count} of {result.total_count} total matches")
for row in result.rows:
    print(row["name"], row["price"])
```

**Example with transform:**

```python
from shared.modules.data.transform_expression import TransformExpression, TransformCase

# Normalize prices from mixed currencies to USD
result = await store.select_rows(
    transform=TransformExpression(
        source_column="price",
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
        alias="price_usd",
    ),
    fields=["name", "price_usd"],
    order_by="price_usd",
    order="desc",
)
```

**Example with OR filter logic:**

```python
# Find rows where status is "active" OR category is "premium"
result = await store.select_rows(
    filters=[
        FilterCondition(column="status", operator="=", value="active"),
        FilterCondition(column="category", operator="=", value="premium"),
    ],
    filter_logic="OR",
)
```

---

##### `aggregate(operation, field, group_by, filters, limit, order_by, order, having_operator, having_value, transform, filter_logic) -> QueryResult`

```python
@abstractmethod
async def aggregate(
    self,
    operation: str,
    field: str | None = None,
    group_by: str | list[str] | None = None,
    filters: list[FilterCondition] | None = None,
    limit: int = 20,
    order_by: str | None = None,
    order: str = "desc",
    having_operator: str | None = None,
    having_value: float | None = None,
    transform: TransformExpression | None = None,
    filter_logic: str = "AND",
) -> QueryResult
```

Perform an aggregation operation (SUM, AVG, COUNT, MIN, MAX, etc.) on the data source, optionally grouped, filtered, and post-filtered with a HAVING clause.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `operation` | `str` | *(required)* | The aggregation function to apply (e.g., `"SUM"`, `"AVG"`, `"COUNT"`, `"MIN"`, `"MAX"`). |
| `field` | `str \| None` | `None` | The column to aggregate. Can be `None` for operations like `COUNT(*)`. |
| `group_by` | `str \| list[str] \| None` | `None` | Column(s) to group by. Accepts a single column name or a list. |
| `filters` | `list[FilterCondition] \| None` | `None` | Pre-aggregation filters (WHERE clause). |
| `limit` | `int` | `20` | Maximum number of grouped results to return. |
| `order_by` | `str \| None` | `None` | Column or aggregate expression to sort by. |
| `order` | `str` | `"desc"` | Sort direction: `"asc"` or `"desc"`. Note: default is `"desc"` (unlike `select_rows` which defaults to `"asc"`). |
| `having_operator` | `str \| None` | `None` | Comparison operator for the HAVING clause (e.g., `">"`, `">="`). |
| `having_value` | `float \| None` | `None` | Threshold value for the HAVING clause. |
| `transform` | `TransformExpression \| None` | `None` | A computed column expression applied before aggregation. |
| `filter_logic` | `str` | `"AND"` | How to combine multiple filters: `"AND"` or `"OR"`. |

**Returns:**
- `QueryResult` -- Column names, row dicts, and row count. The `total_count` field may be `None` depending on the implementation.

**Example -- simple count:**

```python
# Count all rows
result = await store.aggregate(operation="COUNT")
print(result.rows)  # [{"COUNT(*)": 1523}]
```

**Example -- grouped aggregation:**

```python
# Average price per category
result = await store.aggregate(
    operation="AVG",
    field="price",
    group_by="category",
    order_by="AVG(price)",
    order="desc",
    limit=5,
)

for row in result.rows:
    print(f"{row['category']}: ${row['AVG(price)']:.2f}")
```

**Example -- with HAVING clause:**

```python
# Categories with more than 50 products
result = await store.aggregate(
    operation="COUNT",
    field="id",
    group_by="category",
    having_operator=">",
    having_value=50,
)
```

**Example -- multi-column group by with filters:**

```python
# Total sales by region and year, only for completed orders
result = await store.aggregate(
    operation="SUM",
    field="amount",
    group_by=["region", "year"],
    filters=[
        FilterCondition(column="status", operator="=", value="completed"),
    ],
    order_by="SUM(amount)",
    order="desc",
)
```

**Example -- with transform and aggregation:**

```python
# Sum prices normalized to USD, grouped by region
result = await store.aggregate(
    operation="SUM",
    field="price_usd",
    group_by="region",
    transform=TransformExpression(
        source_column="price",
        cases=[
            TransformCase(
                when=[FilterCondition(column="currency", operator="=", value="EUR")],
                then_multiply=1.08,
            ),
        ],
        else_multiply=1.0,
        alias="price_usd",
    ),
)
```

---

## Related types reference

### `FilterCondition`

```python
class FilterCondition(ShapesBaseModel):
    column: str
    operator: str = "="           # One of: =, !=, >, >=, <, <=, LIKE, NOT LIKE, IN, NOT IN, IS NULL, IS NOT NULL
    value: str | int | float | list = ""
```

Immutable (frozen) Pydantic model. Validated on construction: `IN`/`NOT IN` require a non-empty list, `LIKE`/`NOT LIKE` require a string, and the operator must be in the allowed set.

### `TableSchema`

```python
class TableSchema(ShapesBaseModel):
    table_name: str
    columns: list[ColumnInfo]
```

### `ColumnInfo`

```python
class ColumnInfo(ShapesBaseModel):
    name: str
    detected_type: str
    samples: list[str] = []
```

### `QueryResult`

```python
class QueryResult(ShapesBaseModel):
    columns: list[str]
    rows: list[dict]
    count: int
    total_count: int | None = None
```

### `TransformExpression`

```python
class TransformExpression(ShapesBaseModel):
    source_column: str               # Numeric column to transform
    cases: list[TransformCase]       # 1-10 conditional branches
    else_multiply: float | None      # Default multiplier when no case matches
    else_value: float | None         # Default constant when no case matches
    alias: str                       # Name for the computed column (lowercase, alphanumeric, underscores)
```

### `TransformCase`

```python
class TransformCase(ShapesBaseModel):
    when: list[FilterCondition]      # Conditions that must all match
    then_multiply: float | None      # Multiply source column by this factor
    then_value: float | None         # Replace source column with this constant
```

---

## Implementing a new data store

To add a new storage backend, subclass `DataStore` and implement all three abstract methods.

```python
from data_store.interfaces.data_store import DataStore
from shared.modules.data.table_schema import TableSchema
from shared.modules.data.query_result import QueryResult
from shared.modules.data.filter_condition import FilterCondition
from shared.modules.data.transform_expression import TransformExpression


class PostgresDataStore(DataStore):
    async def get_schema(self) -> TableSchema | None:
        # Inspect the database and return the schema
        ...

    async def select_rows(
            self,
            filters: list[FilterCondition] | None = None,
            fields: list[str] | None = None,
            limit: int = 20,
            order_by: str | None = None,
            order: str = "asc",
            distinct: bool = False,
            transform: TransformExpression | None = None,
            filter_logic: str = "AND",
    ) -> QueryResult:
        # Build and execute a SELECT query
        ...

    async def aggregate(
            self,
            operation: str,
            field: str | None = None,
            group_by: str | list[str] | None = None,
            filters: list[FilterCondition] | None = None,
            limit: int = 20,
            order_by: str | None = None,
            order: str = "desc",
            having_operator: str | None = None,
            having_value: float | None = None,
            transform: TransformExpression | None = None,
            filter_logic: str = "AND",
    ) -> QueryResult:
        # Build and execute an aggregate query
        ...
```

Failing to implement any of the three methods results in a `TypeError` when the class is instantiated:

```
TypeError: Can't instantiate abstract class PostgresDataStore with abstract method get_schema
```
