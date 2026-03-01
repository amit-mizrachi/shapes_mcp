# Shapes MCP — Ingestion Process: Interview Preparation Guide

## How to Open Your Answer

> "The ingestion process is a synchronous, startup-time pipeline that transforms a raw CSV file into a queryable SQLite database, then exposes it through MCP (Model Context Protocol) tools that an LLM can call. It runs once when the server boots — there's no ongoing streaming or background workers. The pipeline has four stages: **Parse → Enrich → Ingest → Serve**."

---

## The Big Picture (30-Second Version)

```
CSV File on Disk
       │
       ▼
  ┌──────────┐     ┌───────────────┐     ┌────────────────┐     ┌──────────────┐
  │ CSVParser │ ──▶ │ ColumnEnricher│ ──▶ │ SqliteIngester │ ──▶ │SqliteDataStore│
  │  (parse)  │     │   (enrich)    │     │   (ingest)     │     │   (query)    │
  └──────────┘     └───────────────┘     └────────────────┘     └──────────────┘
   Raw CSV →        ParsedCSV →           Enriched CSV →         TableSchema →
   ParsedCSV        Enriched ParsedCSV    TableSchema             Ready for
                                          + SQLite DB              MCP tools
```

The whole thing is orchestrated by a single function — `build_data_store()` in `server.py` — called from FastMCP's `server_lifespan` async context manager.

---

## Stage 0: Server Startup (The Trigger)

**File:** `mcp-server/src/server.py`

When the MCP server boots (via `uvicorn`), FastMCP calls the `server_lifespan` async context manager. This is the orchestrator:

```python
@asynccontextmanager
async def server_lifespan(server: FastMCP):
    database_path = Path(Config.get("mcp_server.db_path"))   # /app/db/shapes.db
    database_path.parent.mkdir(parents=True, exist_ok=True)   # ensure dir exists

    csv_file_path = Config.get("mcp_server.csv_file_path")    # /app/data/people-list-export.csv
    data_store = build_data_store(csv_file_path)               # THE PIPELINE
    yield {"data_store": data_store}                           # expose to tools

    # CLEANUP: delete the DB file on shutdown
    if database_path.exists():
        database_path.unlink()
```

**Key design decisions to mention:**
- The database is **ephemeral** — it's deleted on shutdown and recreated on every boot. This means the CSV is always the source of truth.
- The `data_store` is injected into FastMCP's lifespan context, making it available to all tool handlers via `context.request_context.lifespan_context`.
- The `build_data_store()` function is the entire pipeline in 4 lines:

```python
def build_data_store(csv_file_path: str) -> DataStore:
    parsed_csv = CSVParser.parse(csv_file_path)           # Stage 1
    enricher = ColumnEnricher(rules=[DateEnrichmentRule()])
    enriched_csv = enricher.enrich(parsed_csv)            # Stage 2
    ingester: DataIngestor = SqliteIngester()
    table_schema = ingester.ingest(enriched_csv)          # Stage 3
    return SqliteDataStore(table_schema=table_schema)     # Stage 4
```

---

## Stage 1: CSV Parsing

**File:** `mcp-server/src/data_store/csv_parser.py`

**Purpose:** Read a raw CSV file and produce a structured `ParsedCSV` object with sanitized column names, detected types, and sample values.

### Step-by-step:

### 1.1 Read the file
```python
with open(csv_path, newline="", encoding="utf-8-sig") as file:
    reader = csv.DictReader(file)
    raw_columns = reader.fieldnames
    rows = list(reader)
```
- Uses `utf-8-sig` encoding to handle the BOM (Byte Order Mark) that Excel often adds to CSVs.
- `DictReader` gives us each row as a `{column_name: value}` dictionary.
- Validates: file must exist, be readable, have headers, and have at least one data row. Otherwise raises `ValueError`.

### 1.2 Sanitize column names
```python
def _sanitize_identifier(raw_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw_name.lower()).strip("_")
```
- Converts to lowercase.
- Replaces any run of non-alphanumeric characters with a single underscore.
- Strips leading/trailing underscores.
- Example: `"Full Name"` → `"full_name"`, `"Salary ($)"` → `"salary"`

**Why this matters:** These become SQL column names and need to be safe identifiers — no spaces, no special characters, no SQL injection risk.

### 1.3 Derive table name
```python
def path_to_table_name(csv_path: str) -> str:
    basename = os.path.splitext(os.path.basename(csv_path))[0]
    return CSVParser._sanitize_identifier(basename) or "data"
```
- `people-list-export.csv` → `people_list_export`
- Falls back to `"data"` if sanitization produces an empty string.

### 1.4 Detect column types
```python
def detect_column_type(values: list[str], numeric_threshold: float = 0.8) -> str:
```
- Scans all values in the column.
- Skips empty/whitespace values (they don't count toward the total).
- Tries `float()` on each value — if it parses, it's numeric.
- If more than **80%** of non-empty values are numeric → column type is `"numeric"`.
- Otherwise → `"text"`.
- Handles edge cases: scientific notation (`1e5`), negative numbers (`-3.14`), floats.
- If ALL values are empty → defaults to `"text"`.

**Why 80% and not 100%?** Real data is messy. A salary column might have a few entries like "N/A" or "TBD" but should still be treated as numeric.

### 1.5 Collect sample values
```python
def _collect_distinct_samples(rows, column) -> list[str]:
```
- Scans the first **100 rows** (`_MAX_SCAN_ROWS`).
- Collects up to **5 distinct non-empty values** (`_MAX_SAMPLE_VALUES`).
- These samples are later exposed in `get_schema()` so the LLM can understand what kind of data each column contains without querying.

### 1.6 Rekey rows
- Rows arrive keyed by raw column names (`{"Full Name": "Alice"}`).
- They're rekeyed to sanitized names (`{"full_name": "Alice"}`).
- Missing values are replaced with empty strings.

### Output: `ParsedCSV`

```python
class ParsedCSV(ShapesBaseModel):
    table_name: str              # "people_list_export"
    columns: list[ColumnInfo]    # name + detected_type + samples
    rows: list[dict]             # sanitized-key dictionaries
```

A frozen Pydantic model — immutable after creation.

---

## Stage 2: Data Enrichment

**Files:**
- `mcp-server/src/enrichment/column_enricher.py`
- `mcp-server/src/enrichment/rules/date_enrichment_rule.py`
- `mcp-server/src/enrichment/rules/date_detection.py`
- `mcp-server/src/enrichment/enrichment_rule.py` (abstract base)

**Purpose:** Detect patterns in the data and add derived columns that make the data more useful for analytical queries.

### Architecture: Rule-Based Enrichment

The enrichment system follows the **Strategy pattern**:

```
ColumnEnricher (orchestrator)
    │
    ├── EnrichmentRule (abstract base class)
    │     ├── infer_derived_columns()  — detect what to add
    │     └── add_derived_columns()    — compute values
    │
    └── DateEnrichmentRule (concrete implementation)
```

This is extensible — you can add new rules (e.g., currency normalization, email domain extraction) by creating a new `EnrichmentRule` subclass without touching existing code. **Open/Closed Principle**.

### 2.1 The ColumnEnricher orchestrator

```python
class ColumnEnricher:
    def __init__(self, rules: list[EnrichmentRule]):
        self._rules = rules

    def enrich(self, parsed_csv: ParsedCSV) -> ParsedCSV:
```

1. Takes a configurable **sample size** from config (default: 20 rows) for detection.
2. Iterates over all rules. Each rule inspects columns + sample rows and returns new `ColumnInfo` objects for columns it wants to add.
3. Only rules that detected something are marked as "applicable."
4. For each applicable rule, calls `add_derived_columns()` to compute values for ALL rows.
5. Populates sample values for the new columns (same logic as CSV parser: first 100 rows, 5 distinct values).
6. Returns a **new** `ParsedCSV` with original columns + new enriched columns appended.

### 2.2 Date Detection

**File:** `enrichment/rules/date_detection.py`

```python
_DATE_FORMATS = [
    "%d/%m/%Y",   # 28/01/1977
    "%m/%d/%Y",   # 07/12/1989
    "%Y-%m-%d",   # 1989-07-12
    "%d-%m-%Y",   # 28-01-1977
    "%m-%d-%Y",   # 07-12-1989
    "%Y/%m/%d",   # 1989/07/12
]
```

For each **text** column (numeric columns are skipped):
1. Extract non-empty values from the sample rows.
2. Try each date format against ALL sample values.
3. If **>=80%** of values parse successfully with a given format → the column is a date column.
4. Returns `(column_name, detected_format)` pairs.

**Important:** It tries formats in order and returns the **first match**. This means `%d/%m/%Y` is tried before `%m/%d/%Y`, which could matter for ambiguous dates like "01/02/2024" (is it Jan 2 or Feb 1?).

### 2.3 Date Enrichment Rule

**File:** `enrichment/rules/date_enrichment_rule.py`

For each detected date column (e.g., `start_date`), it creates **three derived columns**:

| Derived Column | Type | Value | Purpose |
|---|---|---|---|
| `start_date_days` | numeric | Days since 1970-01-01 | Duration/age calculations |
| `start_date_month` | numeric | 1-12 | Monthly aggregations |
| `start_date_year` | numeric | 4-digit year | Yearly aggregations |

**How `_days` works:**
```python
self._epoch = date.fromisoformat("1970-01-01")  # from config
parsed = datetime.strptime(raw, date_format).date()
days_value = (parsed - self._epoch).days
```
- Someone born on `1990-01-15` → `(1990-01-15 - 1970-01-01).days = 7319`
- To compute age: `(today_as_nominal_days - birth_days) / 365.25`
- The `today_as_nominal_days` value is dynamically computed in `get_schema()` so the LLM always has the current reference point.

**Collision prevention:** If `start_date_days` already exists as a column name, that suffix is skipped.

**Error handling:** If a date value can't be parsed (despite the column being detected as a date), the derived values are set to `None` (becomes SQL `NULL`).

---

## Stage 3: Database Ingestion

**File:** `mcp-server/src/data_store/sqlite/sqlite_ingester.py`

**Purpose:** Take the enriched `ParsedCSV` and persist it into a SQLite database.

### 3.1 Create the table

```python
def _create_table(self, connection, parsed):
    column_defs = ", ".join(
        f'"{column.name}" {"REAL" if column.detected_type == "numeric" else "TEXT"}'
        for column in parsed.columns
    )
    cursor.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
    cursor.execute(f'CREATE TABLE "{parsed.table_name}" ({column_defs})')
```

- **Type mapping:** `"numeric"` → `REAL`, `"text"` → `TEXT`. Only two types.
- **`DROP TABLE IF EXISTS` first** — this ensures a clean slate. If the server restarts, it doesn't fail on a pre-existing table.
- Column names are quoted with double quotes to handle any remaining special characters safely.

### 3.2 Insert all rows

```python
def _insert_rows(self, connection, parsed_csv):
    placeholders = ", ".join("?" for _ in headers)
    connection.cursor().executemany(
        f'INSERT INTO "{parsed_csv.table_name}" VALUES ({placeholders})',
        rows_as_values,
    )
```

- Uses **parameterized queries** (`?` placeholders) — this prevents SQL injection.
- Uses `executemany()` for batch insertion — more efficient than individual inserts.
- All rows inserted in a single transaction (committed once at the end).

### 3.3 Type conversion for insertion

```python
def _to_sql_value(raw_value, detected_type):
    if raw_value is None: return None
    if detected_type != "numeric": return str(raw_value)
    if isinstance(raw_value, (int, float)): return float(raw_value)
    stripped = str(raw_value).strip()
    if not stripped: return None
    try: return float(stripped)
    except ValueError: return None
```

- Numeric columns: tries to convert to `float`. If it fails (e.g., "N/A" in a mostly-numeric column), stores `NULL`.
- Text columns: always converts to string.
- `None` values pass through as SQL `NULL`.
- Enriched values (from date enrichment) are already `int`/`float`, so they flow through the `isinstance` check.

### Output: `TableSchema`

```python
class TableSchema(ShapesBaseModel):
    table_name: str
    columns: list[ColumnInfo]
```

Same structure as the `ParsedCSV` columns but without the row data — just metadata about what was created.

---

## Stage 4: Data Store Initialization

**File:** `mcp-server/src/data_store/sqlite/sqlite_data_store.py`

```python
class SqliteDataStore(DataStore):
    def __init__(self, database_path=None, table_schema=None):
        self._db_uri = database_path or Config.get("mcp_server.db_path")
        self._table_schema = table_schema
        self._valid_columns = {column.name for column in table_schema.columns}
```

- Stores the schema in memory for fast validation.
- Builds a set of valid column names used to **validate every incoming query** before it touches the database.
- Opens connections in **read-only mode** (`PRAGMA query_only = ON`) — the database is immutable after ingestion.
- Uses `aiosqlite` for async query execution (non-blocking I/O).
- Each query gets its own connection (context manager pattern) — opened, used, closed.

---

## How Tools Consume the Ingested Data

**File:** `mcp-server/src/tool_handlers.py`

Three MCP tools are registered:

### `get_schema()`
- Returns the table name, all column metadata (name, type, samples), and a `date_context` with today's nominal days.
- This is always the **first tool the LLM calls** — it needs to understand the data before querying.

### `select_rows()`
- Row retrieval with filters (AND/OR), sorting, distinct, field selection, and transform expressions.
- Validates: order direction, column names, limit bounds.
- Limit is clamped: `max(1, min(user_limit, 100))`.

### `aggregate()`
- Aggregation operations: COUNT, SUM, AVG, MIN, MAX.
- Supports: GROUP BY (single or multi-column), HAVING clauses, ORDER BY `@result` (sort by the aggregated value).
- Transform expressions for normalizing values before aggregation (e.g., converting mixed currencies).

All tools share this error handling pattern:
```python
async def _execute_query(tool_name, coro):
    try:
        query_result = await coro
    except ValueError as error:        # validation failures
        return json.dumps({"error": str(error)})
    except Exception as error:         # unexpected failures
        return json.dumps({"error": f"Internal error: {error}"})
    return _format_query_response(query_result)
```

---

## Design Patterns & Architectural Decisions Worth Mentioning

### 1. Clean Architecture / Dependency Inversion
- `DataIngestor` and `DataStore` are **abstract interfaces** (ABCs).
- `SqliteIngester` and `SqliteDataStore` are concrete implementations.
- The `build_data_store()` function works against abstractions. You could swap SQLite for PostgreSQL by implementing a new `DataStore` without touching the pipeline.

### 2. Strategy Pattern (Enrichment)
- `ColumnEnricher` accepts a list of `EnrichmentRule` implementations.
- Currently only `DateEnrichmentRule`, but the system is designed for easy extension.
- Each rule has a two-phase API: **detect** (`infer_derived_columns`) then **apply** (`add_derived_columns`).

### 3. Shared Models (Pydantic)
- All data flows through well-defined Pydantic models (`ParsedCSV`, `TableSchema`, `ColumnInfo`, `FilterCondition`, `TransformExpression`).
- Models are frozen (immutable) — enforces data integrity between pipeline stages.
- A `ShapesBaseModel` base class provides shared configuration.

### 4. Ephemeral Database
- The SQLite DB is created on startup, deleted on shutdown.
- The CSV is always the source of truth.
- This simplifies the system — no migration logic, no schema drift, no stale data.

### 5. Read-Only Query Mode
- After ingestion, the DB connection uses `PRAGMA query_only = ON`.
- This is a defense-in-depth measure — even if a SQL injection somehow got through validation, it couldn't modify data.

### 6. Parameterized Queries
- All user-facing queries use `?` placeholders, never string interpolation.
- Column names are validated against a whitelist (`_valid_columns`) before being interpolated into SQL.

---

## End-to-End Example

**Input CSV (`people-list-export.csv`):**
```
Full Name,Start Date,Salary Amount,Job
Alice Smith,15/01/2020,75000,Engineer
Bob Jones,01/03/2018,82000,Manager
```

**After Stage 1 (CSVParser.parse):**
```python
ParsedCSV(
    table_name="people_list_export",
    columns=[
        ColumnInfo(name="full_name", detected_type="text", samples=["Alice Smith", "Bob Jones"]),
        ColumnInfo(name="start_date", detected_type="text", samples=["15/01/2020", "01/03/2018"]),
        ColumnInfo(name="salary_amount", detected_type="numeric", samples=["75000", "82000"]),
        ColumnInfo(name="job", detected_type="text", samples=["Engineer", "Manager"]),
    ],
    rows=[
        {"full_name": "Alice Smith", "start_date": "15/01/2020", "salary_amount": "75000", "job": "Engineer"},
        {"full_name": "Bob Jones", "start_date": "01/03/2018", "salary_amount": "82000", "job": "Manager"},
    ],
)
```

**After Stage 2 (ColumnEnricher.enrich):**
```python
# Date detection: start_date matches %d/%m/%Y format
# Three new columns added:

ParsedCSV(
    table_name="people_list_export",
    columns=[
        # ... original 4 columns ...
        ColumnInfo(name="start_date_days", detected_type="numeric", samples=["18276", "17591"]),
        ColumnInfo(name="start_date_month", detected_type="numeric", samples=["1", "3"]),
        ColumnInfo(name="start_date_year", detected_type="numeric", samples=["2020", "2018"]),
    ],
    rows=[
        {
            "full_name": "Alice Smith", "start_date": "15/01/2020",
            "salary_amount": "75000", "job": "Engineer",
            "start_date_days": 18276, "start_date_month": 1, "start_date_year": 2020,
        },
        # ...
    ],
)
```

**After Stage 3 (SqliteIngester.ingest):**
```sql
CREATE TABLE "people_list_export" (
    "full_name" TEXT,
    "start_date" TEXT,
    "salary_amount" REAL,
    "job" TEXT,
    "start_date_days" REAL,
    "start_date_month" REAL,
    "start_date_year" REAL
);
-- 2 rows inserted via executemany with parameterized values
```

**After Stage 4 (SqliteDataStore ready):**
- LLM calls `get_schema()` → sees all 7 columns with types and samples
- LLM calls `aggregate(operation="avg", field="salary_amount", group_by="job")` → gets average salary by job
- LLM calls `select_rows(order_by="start_date_days", order="desc", limit=1)` → gets the most recent hire

---

## Deployment Context

```
Docker Compose (3 services)
┌─────────────────────────────────────────────────┐
│                                                 │
│  chat-frontend (nginx, port 3000)               │
│       │ HTTP                                    │
│       ▼                                         │
│  chat-backend (FastAPI, port 3002)              │
│       │ MCP over Streamable HTTP                │
│       ▼                                         │
│  mcp-server (FastMCP/uvicorn, port 3001)        │
│       │                                         │
│       ├── /mcp  (MCP protocol endpoint)         │
│       └── /health (healthcheck)                 │
│                                                 │
│  Volumes:                                       │
│    ./data → /app/data (read-only, CSV source)   │
│    mcp-db → /app/db (ephemeral SQLite)          │
└─────────────────────────────────────────────────┘
```

- The MCP server is not exposed to the host — only the chat-frontend is (port 3000).
- `chat-backend` depends on `mcp-server` being healthy (healthcheck passes).
- The CSV is mounted read-only — the server cannot modify the source data.

---

## Potential Interview Follow-Up Questions

**Q: Why SQLite and not just keep the data in memory?**
> SQLite gives us SQL query capabilities (WHERE, GROUP BY, HAVING, ORDER BY, aggregations) for free. Implementing all that filtering and aggregation logic in Python would be reinventing the wheel and be slower for large datasets. SQLite also handles indexing, type coercion, and query optimization internally.

**Q: Why not use a proper database like PostgreSQL?**
> For this use case, SQLite is the right tool. The data is loaded once, is read-only, and lives within a single container. There's no need for concurrent writes, multi-user access, or network-accessible storage. SQLite is file-based, zero-config, and extremely fast for read workloads. The architecture supports swapping it out (via the DataStore interface) if needs change.

**Q: What happens if the CSV is malformed?**
> The parser has explicit error handling: missing file → ValueError, permission denied → ValueError, no headers → ValueError, no data rows → ValueError. For individual values, the type detection is tolerant (80% threshold), and the type converter gracefully handles unparseable numeric values by storing NULL.

**Q: How does the system handle schema changes if the CSV columns change?**
> Since the database is ephemeral (dropped and recreated on every startup), schema changes are automatic. Upload a new CSV with different columns, restart the server, and the new schema is picked up. There's no migration logic needed.

**Q: Is there any risk of SQL injection?**
> Multiple layers of defense: (1) All query parameters use `?` placeholders (parameterized queries). (2) Column names are validated against a whitelist before interpolation. (3) The query connection is read-only (`PRAGMA query_only = ON`). (4) Column names in SQL are always quoted with double quotes.

**Q: How would you scale this if the CSV had millions of rows?**
> Current approach loads everything into memory during parsing (DictReader → list). For millions of rows, I'd: (1) Stream the CSV in chunks instead of `list(reader)`. (2) Use batch inserts with configurable batch sizes. (3) Add indexes on frequently queried columns after ingestion. (4) Consider partitioning or moving to a proper OLAP database if query performance becomes an issue. The abstract interfaces make this migration straightforward.

**Q: Why enrich at ingestion time rather than query time?**
> Pre-computing derived date columns (days, month, year) at ingestion time means every query that needs them gets O(1) access instead of parsing date strings on every query. It's a classic space-time tradeoff — a few extra columns in storage save repeated computation across potentially hundreds of queries.
