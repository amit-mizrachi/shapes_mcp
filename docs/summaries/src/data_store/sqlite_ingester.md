# `sqlite_ingester.py` -- SQLite data ingestion from parsed CSV

## Overview

This module provides `SqliteIngester`, a concrete implementation of the `DataIngestor` abstract
base class. It takes a `ParsedCSV` object (table name, column metadata, and row data) and
writes the data into a SQLite database. The ingester handles table creation, type mapping
(numeric columns become `REAL`, everything else becomes `TEXT`), and bulk row insertion. On
success it returns a `TableSchema` describing the table that was created.

**Source:** `mcp-server/src/data_store/sqlite_ingester.py`

**Dependencies:**

| Import | Purpose |
|--------|---------|
| `sqlite3` | Standard-library SQLite driver |
| `shared.config.Config` | Application configuration (provides the default database path) |
| `shared.modules.data.parsed_csv.ParsedCSV` | Immutable model representing parsed CSV data |
| `shared.modules.data.table_schema.TableSchema` | Immutable model representing the schema of an ingested table |
| `data_store.data_ingestor.DataIngestor` | Abstract base class that defines the `ingest` contract |

---

## Classes

### `SqliteIngester(DataIngestor)`

Ingests parsed CSV data into a SQLite database. Implements the `DataIngestor` interface.

Each call to `ingest` opens a new connection, drops any existing table with the same name,
creates a fresh table with the appropriate column types, inserts all rows, and commits the
transaction. The connection is always closed, even if an error occurs.

#### Methods

---

##### `__init__(self, database_path: str | None = None) -> None`

Initialize the ingester with a database file path.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `database_path` | `str \| None` | No | Absolute or relative path to the SQLite database file. When `None`, the path is read from the application config key `mcp_server.db_path`. |

**Attributes set:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `_db_uri` | `str` | Resolved path to the SQLite database file |

**Example:**

```python
# Use the default path from Config
ingester = SqliteIngester()

# Use a custom path
ingester = SqliteIngester(database_path="/tmp/my_data.db")
```

---

##### `ingest(self, parsed_csv: ParsedCSV) -> TableSchema`

Main entry point. Creates a table in the SQLite database and populates it with the data from
`parsed_csv`. If a table with the same name already exists, it is dropped and recreated.

The method opens a connection, delegates to `_create_table` and `_insert_rows`, commits the
transaction, and closes the connection inside a `try/finally` block so the connection is
always released.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `parsed_csv` | `ParsedCSV` | Yes | Parsed CSV data containing the table name, column definitions, and row data |

**Returns:** `TableSchema` -- a frozen Pydantic model with `table_name` and `columns` fields
describing the table that was created.

**Raises:** Any `sqlite3` exception (e.g., `sqlite3.OperationalError`) will propagate after
the connection is closed.

**Example:**

```python
from shared.modules.data.parsed_csv import ParsedCSV
from shared.modules.data.column_info import ColumnInfo

parsed = ParsedCSV(
    table_name="players",
    columns=[
        ColumnInfo(name="name", detected_type="text"),
        ColumnInfo(name="score", detected_type="numeric"),
    ],
    rows=[
        {"name": "Alice", "score": 42},
        {"name": "Bob", "score": 99},
    ],
)

ingester = SqliteIngester(database_path="/tmp/example.db")
schema = ingester.ingest(parsed)

print(schema.table_name)  # "players"
print(len(schema.columns))  # 2
```

---

##### `_create_table(self, connection: sqlite3.Connection, parsed: ParsedCSV) -> None`

Drop (if it exists) and create the SQLite table matching the column definitions in `parsed`.

Column type mapping:
- `detected_type == "numeric"` maps to SQLite `REAL`
- Everything else maps to SQLite `TEXT`

Column and table names are double-quoted to handle names that contain spaces or are reserved
words.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `connection` | `sqlite3.Connection` | Yes | An open SQLite connection |
| `parsed` | `ParsedCSV` | Yes | Parsed CSV data with `table_name` and `columns` |

**Returns:** `None`

**SQL emitted (example):**

For a `ParsedCSV` with `table_name="stats"` and columns `[("goals", "numeric"), ("team", "text")]`:

```sql
DROP TABLE IF EXISTS "stats";
CREATE TABLE "stats" ("goals" REAL, "team" TEXT);
```

---

##### `_insert_rows(self, connection: sqlite3.Connection, parsed_csv: ParsedCSV) -> None`

Bulk-insert all rows from `parsed_csv` into the table using parameterized `INSERT` statements
via `executemany`. Each cell value is converted through `_to_sql_value` before insertion.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `connection` | `sqlite3.Connection` | Yes | An open SQLite connection |
| `parsed_csv` | `ParsedCSV` | Yes | Parsed CSV data with `table_name`, `headers`, and `rows` |

**Returns:** `None`

**SQL emitted (example):**

```sql
INSERT INTO "players" VALUES (?, ?)
-- executed once per row with parameterized values
```

---

##### `_to_sql_value(raw_value, detected_type: str) -> float | None | str` *(static method)*

Convert a single cell value from the parsed CSV into a type suitable for SQLite insertion.

**Conversion rules:**

| Condition | Return value |
|-----------|-------------|
| `raw_value is None` | `None` |
| `detected_type` is not `"numeric"` | `str(raw_value)` |
| `raw_value` is `int` or `float` | `float(raw_value)` |
| `str(raw_value).strip()` is empty | `None` |
| `str(raw_value).strip()` parses as a float | `float(...)` |
| Float parsing raises `ValueError` | `None` |

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `raw_value` | any | Yes | The raw cell value from a CSV row dictionary |
| `detected_type` | `str` | Yes | The column's detected type (e.g., `"numeric"` or `"text"`) |

**Returns:** `float | None | str`

**Examples:**

```python
SqliteIngester._to_sql_value(None, "numeric")       # None
SqliteIngester._to_sql_value(42, "numeric")          # 42.0
SqliteIngester._to_sql_value("3.14", "numeric")      # 3.14
SqliteIngester._to_sql_value("", "numeric")          # None
SqliteIngester._to_sql_value("not_a_number", "numeric")  # None
SqliteIngester._to_sql_value("hello", "text")        # "hello"
SqliteIngester._to_sql_value(123, "text")            # "123"
```

---

## Data flow

```
ParsedCSV
  |
  v
ingest()
  |-- _create_table()   -->  DROP + CREATE TABLE in SQLite
  |-- _insert_rows()    -->  INSERT rows (each cell via _to_sql_value)
  |-- connection.commit()
  |
  v
TableSchema (table_name, columns)
```

## Related types

| Type | Location | Role |
|------|----------|------|
| `DataIngestor` | `data_store/data_ingestor.py` | Abstract base class with the `ingest` contract |
| `ParsedCSV` | `shared/modules/data/parsed_csv.py` | Frozen Pydantic model: `table_name`, `columns`, `rows`, `headers` (property) |
| `TableSchema` | `shared/modules/data/table_schema.py` | Frozen Pydantic model: `table_name`, `columns` |
| `ColumnInfo` | `shared/modules/data/column_info.py` | Frozen Pydantic model: `name`, `detected_type`, `samples` |
| `Config` | `shared/config.py` | Application configuration accessor |
