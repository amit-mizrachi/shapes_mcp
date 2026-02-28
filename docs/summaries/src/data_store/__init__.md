# `__init__.py` -- Data Store Package Init

## Overview

The file `mcp-server/src/data_store/__init__.py` is an **empty Python package marker**. It contains no imports, exports, classes, or functions. Its sole purpose is to declare the `data_store` directory as a Python package so that its sibling modules can be imported with dotted paths (e.g., `from data_store.data_store import DataStore`).

## Exports / Imports

**None.** The file is 0 bytes. It does not re-export any symbols from sibling modules.

All consumers import directly from the specific modules within the package rather than from `data_store` itself. For example:

```python
from data_store.interfaces.data_store import DataStore
from data_store.sqlite_data_store import SqliteDataStore
from data_store.interfaces.data_ingestor import DataIngestor
from data_store.sqlite_ingester import SqliteIngester
from data_store.sqlite_query_builder import SqliteQueryBuilder
from data_store.csv_parser import CSVParser
```

## Classes

_No classes are defined in this file._

---

## Package contents

Because the `__init__.py` is empty, the following table summarizes the modules that make up the `data_store` package for navigational context.

| Module | Primary class | Role |
|--------|---------------|------|
| `data_store.py` | `DataStore` (ABC) | Abstract interface for querying stored data (schema, select, aggregate). |
| `data_ingestor.py` | `DataIngestor` (ABC) | Abstract interface for ingesting parsed CSV data into a store. |
| `sqlite_data_store.py` | `SqliteDataStore` | Concrete `DataStore` backed by SQLite via `aiosqlite`. |
| `sqlite_query_builder.py` | `SqliteQueryBuilder` | Builds parameterized SQL SELECT and aggregate queries with filters, ordering, transforms, and HAVING clauses. |
| `sqlite_ingester.py` | `SqliteIngester` | Concrete `DataIngestor` that creates a SQLite table and inserts rows from a `ParsedCSV`. |
| `csv_parser.py` | `CSVParser` | Reads a CSV file, sanitizes column names, detects column types (numeric vs. text), and produces a `ParsedCSV`. |

### Dependency graph

```
CSVParser
    |
    v
SqliteIngester (implements DataIngestor)
    |  produces TableSchema
    v
SqliteDataStore (implements DataStore)
    |  delegates SQL construction to
    v
SqliteQueryBuilder
```

### Quick-start example

```python
from data_store.csv_parser import CSVParser
from data_store.sqlite_ingester import SqliteIngester
from data_store.sqlite_data_store import SqliteDataStore

# 1. Parse a CSV file
parsed_csv = CSVParser.parse("/path/to/sales.csv")

# 2. Ingest into SQLite
ingester = SqliteIngester(database_path="/tmp/shapes.db")
table_schema = ingester.ingest(parsed_csv)

# 3. Query the data
store = SqliteDataStore(database_path="/tmp/shapes.db", table_schema=table_schema)
schema = await store.get_schema()
result = await store.select_rows(limit=10, order_by="revenue", order="desc")
```
