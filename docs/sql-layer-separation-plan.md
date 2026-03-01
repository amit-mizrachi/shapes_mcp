# SQL Layer Separation: Query Building vs Database Execution

## Problem

`SqliteDataStore` (331 lines) fuses two distinct responsibilities into one class:

- **SQL query construction** (lines 113-291): Pure, synchronous methods that take domain objects (`FilterCondition`, `TransformExpression`) and produce SQL strings with parameter lists. Zero I/O, no `async`, no dependency on `aiosqlite`.
- **SQLite execution** (lines 293-331): Async methods that depend on `aiosqlite`, use `PRAGMA query_only = ON`, and manage connections.

Adding a second SQL backend (PostgreSQL, DuckDB) would require duplicating the entire 331-line class and changing ~20 lines — 94% code duplication.

## Solution: Three-Way Split

The separation is **three layers**, not two. A pure two-way split would still leave dialect-specific bits (placeholder style, identifier quoting) scattered through the query builder.

```
                    +-------------------+
                    |   SqlDialect      |  (Strategy)
                    |  - placeholder()  |
                    |  - quote_id()     |
                    |  - type_map()     |
                    +-------------------+
                          ^
                          | uses
                          |
+------------------+    +-------------------+    +--------------------+
|  DataStore       |--->| SqlQueryBuilder   |--->| DatabaseExecutor   |
|  (interface)     |    | (generic SQL)     |    | (per-database)     |
+------------------+    +-------------------+    +--------------------+
                              |                        ^
                              | produces               | implements
                              v                        |
                        +-------------------+    +--------------------+
                        | CompiledQuery     |    | SqliteDataStore    |
                        | (sql + params)    |    | PostgresDataStore  |
                        +-------------------+    +--------------------+
```

### Layer 1: SqlDialect (Strategy)

Handles the 3-4 points where SQL databases actually differ:

| Concern | SQLite | PostgreSQL | MySQL |
|---------|--------|-----------|-------|
| Placeholder | `?` | `$1, $2` or `%s` | `%s` |
| Identifier quoting | `"col"` | `"col"` | `` `col` `` |
| Type names | `REAL`, `TEXT` | `DOUBLE PRECISION`, `VARCHAR` | `DOUBLE`, `VARCHAR(255)` |
| Read-only mode | `PRAGMA query_only = ON` | `SET default_transaction_read_only = on` | `SET SESSION TRANSACTION READ ONLY` |

Each dialect implementation is ~15 lines.

### Layer 2: SqlQueryBuilder (Generic SQL)

Everything currently in `sqlite_data_store.py` lines 113-291 moves here, replacing hardcoded `?` with `self._dialect.placeholder()`:

- `_build_select_columns`, `_build_where_clause`, `_build_order_clause`
- `_filter_to_sql_expression`, `_collect_filter_params`
- `_build_case_expression`, `_build_aggregation_expression`
- `_build_having_clause`, `_build_aggregated_sql_query`
- All validation methods
- The `select_rows`/`aggregate` orchestration logic

Produces a `CompiledQuery(sql, params, count_sql, count_params)` frozen dataclass.

### Layer 3: SqliteDataStore (Executor)

Drops from 331 lines to ~60 lines. Only does:

- `aiosqlite.connect()` + `PRAGMA`
- `execute(sql, params)` + `fetchall()`
- Returns `QueryResult`

## File Structure

```
data_store/
    __init__.py
    csv_parser.py                          # unchanged
    interfaces/
        __init__.py
        data_store.py                      # DataStore ABC (unchanged)
        data_ingestor.py                   # DataIngestor ABC (unchanged)
    sql/
        __init__.py
        dialect.py                         # SqlDialect ABC
        query.py                           # CompiledQuery dataclass
        query_builder.py                   # SqlQueryBuilder (~200 lines, pure logic)
        validation.py                      # Pure validation functions (extracted)
        dialects/
            __init__.py
            sqlite_dialect.py              # SqliteDialect (~15 lines)
            # postgresql_dialect.py        # future
    sqlite/
        __init__.py
        sqlite_data_store.py              # ~60 lines: compose builder + execute
        sqlite_ingester.py                # unchanged (or uses dialect for type mapping)
    # postgresql/                          # future — just executor + ingester
```

11 files (up from 7). Each file has one clear job.

## Data Flow

```
tool_handlers.py
    |  calls DataStore.select_rows(filters, fields, ...)
    v
SqliteDataStore
    |  delegates to SqlQueryBuilder.build_select(...)
    v
SqlQueryBuilder  (uses SqliteDialect for ?, quoting)
    |  returns CompiledQuery(sql="SELECT ...", params=[...])
    v
SqliteDataStore
    |  executes via aiosqlite
    v
QueryResult(columns=[...], rows=[...], count=N)
```

## Key Abstractions

### CompiledQuery

The boundary object between builder and executor.

```python
@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    params: list
    count_sql: str | None = None
    count_params: list | None = None
```

### SqlDialect ABC

```python
class SqlDialect(ABC):
    @abstractmethod
    def placeholder(self, position: int = 0) -> str: ...

    @abstractmethod
    def quote_identifier(self, name: str) -> str: ...

    @abstractmethod
    def map_column_type(self, detected_type: str) -> str: ...

    def read_only_preamble(self) -> list[str]:
        return []
```

### SqliteDialect

```python
class SqliteDialect(SqlDialect):
    _TYPE_MAP = {"numeric": "REAL", "text": "TEXT"}

    def placeholder(self, position: int = 0) -> str:
        return "?"

    def quote_identifier(self, name: str) -> str:
        return f'"{name}"'

    def map_column_type(self, detected_type: str) -> str:
        return self._TYPE_MAP.get(detected_type, "TEXT")

    def read_only_preamble(self) -> list[str]:
        return ["PRAGMA query_only = ON"]
```

### SqlQueryBuilder

```python
class SqlQueryBuilder:
    def __init__(self, dialect: SqlDialect, table_schema: TableSchema) -> None:
        self._dialect = dialect
        self._table_name = table_schema.table_name
        self._valid_columns = {col.name for col in table_schema.columns}

    def build_select(self, filters, fields, limit, order_by, order,
                     distinct, transform, filter_logic) -> CompiledQuery: ...

    def build_aggregate(self, operation, field, group_by, filters, limit,
                        order_by, order, having_operator, having_value,
                        transform, filter_logic) -> CompiledQuery: ...
```

### Refactored SqliteDataStore

```python
class SqliteDataStore(DataStore):
    def __init__(self, database_path=None, table_schema=None):
        self._db_uri = database_path or Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._dialect = SqliteDialect()
        self._builder = SqlQueryBuilder(self._dialect, table_schema)

    async def select_rows(self, **kwargs) -> QueryResult:
        query = self._builder.build_select(**kwargs)
        return await self._execute(query)

    async def aggregate(self, **kwargs) -> QueryResult:
        query = self._builder.build_aggregate(**kwargs)
        return await self._execute(query)

    async def _execute(self, query: CompiledQuery) -> QueryResult:
        # aiosqlite-specific execution, ~30 lines
        ...
```

## PostgreSQL Numbered Placeholder Gotcha

The trickiest dialect difference. SQLite uses `?` (stateless), but `asyncpg` uses `$1, $2, $3` (stateful counter).

Solution — use a `PlaceholderTracker` created fresh per query build:

```python
class PlaceholderTracker:
    def __init__(self, dialect: SqlDialect):
        self._dialect = dialect
        self._index = 0

    def next(self) -> str:
        self._index += 1
        return self._dialect.placeholder(self._index)
```

For SQLite, `placeholder()` ignores the index and returns `?`. For PostgreSQL, it returns `$N`. The builder creates a fresh tracker at the start of each `build_select`/`build_aggregate` call.

## Other Dialect Gotchas

| Concern | SQLite | PostgreSQL | MySQL |
|---------|--------|-----------|-------|
| LIKE case sensitivity | Case-insensitive by default | Case-sensitive (use `ILIKE`) | Depends on collation |
| Boolean type | Stored as text `"true"`/`"false"` | Native `BOOLEAN` | `TINYINT(1)` |
| LIMIT syntax | `LIMIT ?` | `LIMIT $N` | `LIMIT ?` (same) |
| Auto-increment | `INTEGER PRIMARY KEY` | `SERIAL` / `GENERATED ALWAYS` | `AUTO_INCREMENT` |

For this project, `LIKE` case sensitivity is the most likely to matter. Consider adding `dialect.like_operator(case_sensitive: bool)` to handle `LIKE` vs `ILIKE`.

## What Belongs Where

### Generic SQL layer (`sql/`)

All `_build_*` and `_validate_*` methods. These are pure functions that produce SQL strings:

- `_build_select_columns` — `SELECT "col1", "col2"` with identifier quoting
- `_build_where_clause` — `WHERE ... AND/OR ...` universal SQL
- `_build_order_clause` — `ORDER BY "col" ASC/DESC` standard SQL
- `_filter_to_sql_expression` — converts `FilterCondition` to SQL fragments with dialect placeholders
- `_collect_filter_params` — pure data transformation
- `_build_case_expression` — `CASE WHEN ... THEN ... ELSE ... END` is ANSI SQL
- `_build_aggregation_expression` — `COUNT(*)`, `SUM("col")` standard SQL
- `_build_having_clause` — `HAVING result >= ?` standard SQL
- `_build_aggregated_sql_query` — composes standard SQL clauses
- `_validate_column`, `_validate_order_direction`, `_validate_aggregation_op`, `_validate_aggregation_args`, `_validate_transform_columns` — pure validation

### Database-specific layer (`sqlite/`, `postgresql/`)

- Connection management (`aiosqlite.connect` vs `asyncpg.connect`)
- Read-only pragmas
- Query execution and result formatting
- Ingestion (DDL with database-specific types)

## Migration Steps

| Step | What | Files Created | Files Modified | Risk |
|------|------|--------------|----------------|------|
| 1 | Extract validation functions into `sql/validation.py` | `sql/__init__.py`, `sql/validation.py` | `sqlite_data_store.py` (delegates) | None |
| 2 | Create `SqlDialect` ABC + `SqliteDialect` | `sql/dialect.py`, `sql/dialects/__init__.py`, `sql/dialects/sqlite_dialect.py` | None | None |
| 3 | Create `CompiledQuery` + `SqlQueryBuilder` | `sql/query.py`, `sql/query_builder.py` | `sqlite_data_store.py` (major slim-down) | **All existing tests pass unchanged** |
| 4 | Add unit tests for `SqlQueryBuilder` in isolation | `tests/.../test_sql_query_builder.py` | None | Additive only |
| 5 | Clean up remaining dead code | None | `sqlite_data_store.py` | None |

The critical safety property: **the `DataStore` interface never changes**, so `tool_handlers.py`, `server.py` wiring, and all 30+ existing tests remain valid at every step.

## Adding PostgreSQL Later

```python
# server.py — just swap dialect + executor
dialect = PostgresDialect()
builder = SqlQueryBuilder(dialect=dialect, table_schema=schema)  # SAME builder, untouched
data_store = PostgresDataStore(table_schema=schema)              # new executor only
```

`SqlQueryBuilder` stays completely untouched. Only a new dialect (~15 lines) and a new executor (~60 lines) are needed.
