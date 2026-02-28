# `csv_parser.py` -- CSV ingestion and schema detection

## Overview

`CSVParser` reads a CSV file from disk, sanitizes its column names into safe SQL identifiers, detects whether each column is numeric or text, and returns a structured `ParsedCSV` object ready for database insertion. All methods are static, so the class is used as a stateless utility rather than instantiated.

**Location:** `mcp-server/src/data_store/csv_parser.py`

**Key dependencies:**

| Import | Purpose |
|--------|---------|
| `shared.config.Config` | Provides the `mcp_server.numeric_threshold` setting (default `0.8`) |
| `shared.modules.data.column_info.ColumnInfo` | Pydantic model representing a single column's name, detected type, and sample values |
| `shared.modules.data.parsed_csv.ParsedCSV` | Pydantic model bundling the table name, column metadata, and re-keyed rows |

**Module-level constants:**

| Name | Value | Purpose |
|------|-------|---------|
| `_SANITIZE_PATTERN` | `re.compile(r"[^a-z0-9]+")` | Matches runs of non-alphanumeric characters for identifier sanitization |
| `_MAX_SAMPLE_VALUES` | `3` | Maximum number of sample values collected per column |

---

## Classes

### `CSVParser`

A stateless utility class. Every method is a `@staticmethod`; the class is never instantiated.

---

#### Methods

##### `parse(csv_path: str) -> ParsedCSV`

Top-level entry point. Orchestrates the full CSV ingestion pipeline: read the file, sanitize column names, detect column types, and return the result.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `csv_path` | `str` | Absolute or relative path to the CSV file |

**Returns:** `ParsedCSV` -- a frozen Pydantic model containing `table_name` (str), `columns` (list of `ColumnInfo`), and `rows` (list of dicts keyed by sanitized column names).

**Raises:** `ValueError` -- if the file is missing, unreadable, has no headers, or has no data rows.

**Example:**

```python
from data_store.csv_parser import CSVParser

result = CSVParser.parse("/app/data/people-list-export.csv")

print(result.table_name)   # "people_list_export"
print(result.headers)       # ["first_name", "last_name", "age", ...]

for col in result.columns:
    print(f"{col.name}: {col.detected_type}  samples={col.samples}")

for row in result.rows[:3]:
    print(row)
```

---

##### `_read_csv(csv_path: str) -> tuple[list[str], list[dict]]`

Reads the CSV file from disk using Python's `csv.DictReader`. Opens the file with `utf-8-sig` encoding to transparently strip a BOM if present.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `csv_path` | `str` | Path to the CSV file |

**Returns:** A two-element tuple:

1. `list[str]` -- the raw header names exactly as they appear in the file.
2. `list[dict]` -- each row as a dict keyed by the raw header names.

**Raises:**

| Exception | Condition |
|-----------|-----------|
| `ValueError` | File not found (`FileNotFoundError` is caught and re-raised) |
| `ValueError` | Permission denied (`PermissionError` is caught and re-raised) |
| `ValueError` | File has no header row |
| `ValueError` | File has headers but zero data rows |

**Example:**

```python
raw_columns, rows = CSVParser._read_csv("/app/data/sales.csv")
# raw_columns: ["Order ID", "Total ($)", "Date"]
# rows: [{"Order ID": "1001", "Total ($)": "59.99", "Date": "2025-03-15"}, ...]
```

---

##### `_sanitize_column_names(raw_columns: list[str]) -> list[str]`

Applies `_sanitize_identifier` to every column name in the list, producing SQL-safe identifiers.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `raw_columns` | `list[str]` | Raw header names from the CSV file |

**Returns:** `list[str]` -- sanitized column names in the same order.

**Example:**

```python
CSVParser._sanitize_column_names(["First Name", "Total ($)", "Date of Birth"])
# ["first_name", "total", "date_of_birth"]
```

---

##### `_sanitize_identifier(raw_name: str) -> str`

Converts a single raw string into a safe SQL identifier by lowercasing it, replacing runs of non-alphanumeric characters with a single underscore, and stripping leading/trailing underscores.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `raw_name` | `str` | The raw identifier string (column name or file name) |

**Returns:** `str` -- the sanitized identifier.

**Example:**

```python
CSVParser._sanitize_identifier("Total ($)")       # "total"
CSVParser._sanitize_identifier("  First Name  ")  # "first_name"
CSVParser._sanitize_identifier("DATE-of-BIRTH")   # "date_of_birth"
CSVParser._sanitize_identifier("123--abc!!!")      # "123_abc"
```

---

##### `path_to_table_name(csv_path: str) -> str`

Derives a SQL table name from a file path. Extracts the file's base name (without extension), then sanitizes it with `_sanitize_identifier`. Falls back to `"data"` if sanitization produces an empty string.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `csv_path` | `str` | Path to the CSV file |

**Returns:** `str` -- the derived table name.

**Example:**

```python
CSVParser.path_to_table_name("/app/data/people-list-export.csv")
# "people_list_export"

CSVParser.path_to_table_name("Sales Report (2025).csv")
# "sales_report_2025"

CSVParser.path_to_table_name("!!.csv")
# "data"  (fallback when sanitization yields empty string)
```

---

##### `_detect_types_and_rekey(raw_columns: list[str], sanitized_columns: list[str], rows: list[dict]) -> tuple[list[ColumnInfo], list[dict]]`

Performs a single pass over all rows to accomplish three things simultaneously:

1. **Re-key** each row dict from raw column names to sanitized column names.
2. **Detect types** by counting how many non-empty values in each column parse as floats.
3. **Collect samples** -- up to `_MAX_SAMPLE_VALUES` (3) values per column.

A column is classified as `"numeric"` if the ratio of successfully-parsed float values to total non-empty values exceeds `Config.get("mcp_server.numeric_threshold")` (default `0.8`). Otherwise it is classified as `"text"`. Columns where every value is empty are also classified as `"text"`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `raw_columns` | `list[str]` | Original column names (used as keys to read from input rows) |
| `sanitized_columns` | `list[str]` | Sanitized column names (used as keys in output rows) |
| `rows` | `list[dict]` | Row dicts keyed by raw column names |

**Returns:** A two-element tuple:

1. `list[ColumnInfo]` -- one entry per column with `name`, `detected_type` (`"numeric"` or `"text"`), and `samples`.
2. `list[dict]` -- the same rows re-keyed with sanitized column names.

**Example:**

```python
raw_cols = ["Age", "City"]
san_cols = ["age", "city"]
rows = [
    {"Age": "30", "City": "NYC"},
    {"Age": "25", "City": "LA"},
    {"Age": "40", "City": "Chicago"},
]

columns, sanitized_rows = CSVParser._detect_types_and_rekey(raw_cols, san_cols, rows)

# columns[0]: ColumnInfo(name="age", detected_type="numeric", samples=["30", "25", "40"])
# columns[1]: ColumnInfo(name="city", detected_type="text", samples=["NYC", "LA", "Chicago"])

# sanitized_rows[0]: {"age": "30", "city": "NYC"}
```

---

##### `detect_column_type(values: list[str]) -> str`

Standalone utility that classifies a list of string values as either `"numeric"` or `"text"`. Uses the same logic as `_detect_types_and_rekey` but operates on a single column in isolation. Empty and whitespace-only values are skipped. If every value is empty, returns `"text"`.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `values` | `list[str]` | The cell values for a single column |

**Returns:** `str` -- either `"numeric"` or `"text"`.

**Example:**

```python
CSVParser.detect_column_type(["10", "20.5", "30"])
# "numeric"

CSVParser.detect_column_type(["hello", "world", "42"])
# "text"  (only 1/3 = 0.33 are numeric, below the 0.8 threshold)

CSVParser.detect_column_type(["", "  ", ""])
# "text"  (all empty)

CSVParser.detect_column_type(["100", "200", "", "N/A", "300"])
# "numeric"  (3 out of 4 non-empty values are numeric = 0.75;
#  whether this returns "numeric" or "text" depends on the configured threshold)
```

---

## Data flow summary

```
CSV file on disk
       |
       v
  _read_csv()          -- raw column names + row dicts
       |
       v
  _sanitize_column_names()  -- SQL-safe column names
       |
       v
  path_to_table_name()      -- SQL-safe table name
       |
       v
  _detect_types_and_rekey() -- ColumnInfo list + re-keyed rows
       |
       v
  ParsedCSV(table_name, columns, rows)
```
