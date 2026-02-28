# `data_ingestor.py` -- Abstract data ingestion interface

## Overview

`data_ingestor.py` defines the `DataIngestor` abstract base class (ABC). It establishes a
contract for components that accept parsed CSV data and persist it into a data store,
returning the resulting table schema. The module lives in the `data_store` package and
serves as the single ingestion interface that the rest of the application depends on,
following the Dependency Inversion Principle.

**Location:** `mcp-server/src/data_store/data_ingestor.py`

**Dependencies:**

| Import | Purpose |
|--------|---------|
| `abc.ABC`, `abc.abstractmethod` | Marks the class as abstract with an unimplemented method |
| `shared.modules.data.parsed_csv.ParsedCSV` | Immutable Pydantic model representing parsed CSV data |
| `shared.modules.data.table_schema.TableSchema` | Immutable Pydantic model representing the schema of a persisted table |

---

## Classes

### `DataIngestor`

```python
class DataIngestor(ABC):
```

Abstract base class that defines the ingestion contract. Any concrete data store backend
(SQLite, PostgreSQL, DuckDB, etc.) must subclass `DataIngestor` and implement the
`ingest` method. This abstraction decouples the CSV-parsing layer from the storage layer
so that storage backends can be swapped without changing upstream code.

#### Methods

##### `ingest(parsed_csv: ParsedCSV) -> TableSchema`

```python
@abstractmethod
def ingest(self, parsed_csv: ParsedCSV) -> TableSchema: ...
```

Persists the data from a `ParsedCSV` object into the underlying data store and returns
a `TableSchema` describing the table that was created or updated.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `parsed_csv` | `ParsedCSV` | An immutable Pydantic model containing the table name, column metadata (name, detected type, sample values), and all data rows as a list of dicts. |

**Returns:**

| Type | Description |
|------|-------------|
| `TableSchema` | An immutable Pydantic model containing the persisted table's name and its column definitions (`list[ColumnInfo]`). |

**Raises:**

Concrete implementations may raise storage-specific exceptions (e.g., `sqlite3.Error`,
connection errors). The abstract method itself imposes no constraint on exception types.

**Example -- implementing and using the interface:**

```python
from data_store.interfaces.data_ingestor import DataIngestor
from shared.modules.data.parsed_csv import ParsedCSV
from shared.modules.data.table_schema import TableSchema


class InMemoryIngestor(DataIngestor):
    """Minimal in-memory implementation for testing."""

    def __init__(self) -> None:
        self.tables: dict[str, list[dict]] = {}

    def ingest(self, parsed_csv: ParsedCSV) -> TableSchema:
        self.tables[parsed_csv.table_name] = list(parsed_csv.rows)
        return TableSchema(
            table_name=parsed_csv.table_name,
            columns=parsed_csv.columns,
        )
```

```python
from shared.modules.data.column_info import ColumnInfo
from shared.modules.data.parsed_csv import ParsedCSV

# Build a ParsedCSV object
csv_data = ParsedCSV(
    table_name="players",
    columns=[
        ColumnInfo(name="name", detected_type="text", samples=["Alice"]),
        ColumnInfo(name="score", detected_type="numeric", samples=["95"]),
    ],
    rows=[
        {"name": "Alice", "score": 95},
        {"name": "Bob", "score": 87},
    ],
)

# Ingest through the interface
ingestor: DataIngestor = InMemoryIngestor()
schema = ingestor.ingest(csv_data)

print(schema.table_name)  # "players"
print([col.name for col in schema.columns])  # ["name", "score"]
```

---

## Related types

The following types appear in the `ingest` method signature. They are documented here for
quick reference; see their respective source files for full details.

### `ParsedCSV`

**Source:** `shared/modules/data/parsed_csv.py`

Immutable Pydantic model representing CSV data that has been parsed and is ready for
ingestion.

| Field | Type | Description |
|-------|------|-------------|
| `table_name` | `str` | Name to use for the destination table |
| `columns` | `list[ColumnInfo]` | Column metadata (name, detected type, sample values) |
| `rows` | `list[dict]` | Data rows; each dict maps column name to its value |

| Property | Return type | Description |
|----------|-------------|-------------|
| `headers` | `list[str]` | Convenience property returning `[col.name for col in self.columns]` |

### `TableSchema`

**Source:** `shared/modules/data/table_schema.py`

Immutable Pydantic model representing the schema of a table after it has been persisted.

| Field | Type | Description |
|-------|------|-------------|
| `table_name` | `str` | Name of the table in the data store |
| `columns` | `list[ColumnInfo]` | Column definitions for the table |

### `ColumnInfo`

**Source:** `shared/modules/data/column_info.py`

Immutable Pydantic model representing a single column's metadata.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | -- | Column name |
| `detected_type` | `str` | -- | Type detected during parsing (e.g., `"numeric"`, `"text"`) |
| `samples` | `list[str]` | `[]` | Sample values from the source data |

---

## Known implementations

| Class | Module | Storage backend |
|-------|--------|-----------------|
| `SqliteIngester` | `mcp-server/src/data_store/sqlite_ingester.py` | SQLite (via `sqlite3`) |

---

## Design notes

- The module uses `from __future__ import annotations` for PEP 604 style type unions and
  deferred evaluation of type hints.
- `DataIngestor` intentionally contains no state and no constructor. Concrete subclasses
  are free to accept configuration (database paths, connection pools, etc.) in their own
  `__init__` methods.
- There are no dunder methods with custom logic. The class relies solely on the default
  behavior inherited from `ABC`.
