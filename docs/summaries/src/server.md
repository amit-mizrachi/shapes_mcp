# `server.py` -- MCP data server entry point

## Overview

`server.py` is the main entry point for the MCP (Model Context Protocol) data server. It boots a `FastMCP` HTTP server that exposes three MCP tools (`get_schema`, `select_rows`, `aggregate`) over a streamable-HTTP transport, plus a `/health` endpoint for liveness checks.

On startup, the server reads a CSV file, enriches the parsed data with derived date columns, ingests the result into an ephemeral SQLite database, and exposes the data through the registered tools. When the server shuts down, the SQLite database file is automatically deleted.

**Source:** `mcp-server/src/server.py`

---

## Module-level constants and objects

### Logging configuration

```python
logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
```

Configures root-level logging at `INFO` and creates a module-scoped logger used throughout the file.

### `host`

```python
host = Config.get("mcp_server.host")
```

- **Type:** `str`
- **Default:** `"0.0.0.0"`

Network interface the server binds to. Read from the shared `Config` registry.

### `port`

```python
port = Config.get("mcp_server.port")
```

- **Type:** `int`
- **Default:** `3001`

TCP port the server listens on.

### `streamable_http_path`

```python
streamable_http_path = Config.get("mcp_server.streamable_http_path")
```

- **Type:** `str`
- **Default:** `"/mcp"`

URL path where the MCP streamable-HTTP transport is mounted.

### `mcp_server`

```python
mcp_server = FastMCP(
    "MCP Data Server",
    lifespan=server_lifespan,
    host=host,
    port=port,
    streamable_http_path=streamable_http_path,
)
```

- **Type:** `FastMCP`

The core MCP server instance. It is created with a custom `server_lifespan` async context manager that manages the data pipeline lifecycle.

### `http_app`

```python
http_app = mcp_server.streamable_http_app()
```

- **Type:** Starlette ASGI application

The Starlette HTTP application extracted from the MCP server. This is the object passed to `uvicorn.run()` and is also the target for registering additional HTTP routes such as `/health`.

---

## Functions

### `server_lifespan(server)`

```python
@asynccontextmanager
async def server_lifespan(server: FastMCP):
```

Async context manager that controls the server's startup and shutdown lifecycle.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `server` | `FastMCP` | The MCP server instance (injected by `FastMCP`). |

**Yields:** `dict` -- A dictionary containing a `"data_store"` key whose value is a fully initialized `DataStore` instance. This dictionary becomes available to MCP tool handlers through the request context.

**Behavior:**

1. **Startup** -- Reads the database path from config, ensures the parent directory exists, parses the CSV, enriches it, ingests it into SQLite, and yields the resulting `DataStore`.
2. **Shutdown** -- Deletes the ephemeral SQLite database file if it exists.

**Example (conceptual -- normally invoked automatically by `FastMCP`):**

```python
async with server_lifespan(mcp_server) as context:
    data_store = context["data_store"]
    schema = await data_store.get_schema()
    print(schema.table_name)
```

**Config keys used:**

| Key | Default | Purpose |
|-----|---------|---------|
| `mcp_server.db_path` | `"/app/db/shapes.db"` | File path for the ephemeral SQLite database. |
| `mcp_server.csv_file_path` | `"/app/data/people-list-export.csv"` | CSV file to load on startup. |

---

### `build_data_store(csv_file_path)`

```python
def build_data_store(csv_file_path: str) -> DataStore:
```

Synchronous factory function that executes the full data pipeline: parse, enrich, ingest, and return a queryable data store.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `csv_file_path` | `str` | Absolute path to the source CSV file. |

**Returns:** `DataStore` -- A concrete `SqliteDataStore` instance backed by the ingested data.

**Pipeline steps:**

1. **Parse** -- `CSVParser.parse(csv_file_path)` reads the CSV, sanitizes column names, detects column types (numeric vs. text), and collects sample values.
2. **Enrich** -- `ColumnEnricher` applies a chain of enrichment rules to the parsed data:
   - `NominalDateRule` -- Adds a `{col}_days` column for each detected date column (days since epoch `1970-01-01`).
   - `MonthExtractionRule` -- Adds a `{col}_month` column (1--12).
   - `YearExtractionRule` -- Adds a `{col}_year` column (four-digit year).
3. **Ingest** -- `SqliteIngester` creates a SQLite table matching the enriched schema and bulk-inserts all rows.
4. **Return** -- `SqliteDataStore` wraps the ingested table, providing async query methods.

**Example:**

```python
data_store = build_data_store("/app/data/people-list-export.csv")
# data_store is now a SqliteDataStore ready for queries
```

---

### `health(request)`

```python
async def health(request):
```

Lightweight HTTP health-check endpoint.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `request` | Starlette `Request` | The incoming HTTP request (unused). |

**Returns:** `JSONResponse` -- `{"status": "ok"}` with a `200` status code.

**Route:** `GET /health`

**Example:**

```bash
curl http://localhost:3001/health
# {"status": "ok"}
```

---

## Tool registrations

Three MCP tools are registered on the server by calling `mcp_server.tool()` as a decorator on handler functions imported from `tool_handlers`:

```python
mcp_server.tool()(tool_handlers.get_schema)
mcp_server.tool()(tool_handlers.select_rows)
mcp_server.tool()(tool_handlers.aggregate)
```

Each tool is an `async` function that receives parameters from the MCP client and returns a JSON string.

### Tool: `get_schema`

```python
async def get_schema(context: Context) -> str:
```

Returns the database schema -- table name, column names, detected types, sample values, and date context.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `context` | `mcp.server.fastmcp.Context` | MCP request context carrying the lifespan-injected `DataStore`. |

**Returns:** `str` -- JSON string with the following structure:

```json
{
  "table": "people_list_export",
  "date_context": {
    "nominal_date_epoch": "1970-01-01",
    "today_as_nominal_days": 20512
  },
  "columns": [
    {
      "name": "age",
      "detected_type": "numeric",
      "samples": ["32", "45", "28"]
    }
  ]
}
```

**Usage note:** Clients should call this tool first to discover available columns before issuing `select_rows` or `aggregate` queries.

---

### Tool: `select_rows`

```python
async def select_rows(
    filters: list[FilterCondition] | None = None,
    fields: list[str] | None = None,
    limit: int = 20,
    order_by: str | None = None,
    order: str = "asc",
    distinct: bool = False,
    transform: TransformExpression | None = None,
    filter_logic: str = "AND",
    context: Context = None,
) -> str:
```

Retrieves rows from the data table with optional filtering, sorting, field selection, deduplication, and conditional value transformation.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `filters` | `list[FilterCondition] \| None` | `None` | Row filters. Each filter has `column`, `operator` (one of `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`), and `value`. |
| `fields` | `list[str] \| None` | `None` | Columns to return. `None` returns all columns. |
| `limit` | `int` | `20` | Maximum rows to return. Clamped to range `[1, 100]`. |
| `order_by` | `str \| None` | `None` | Column name to sort by (or a transform alias). |
| `order` | `str` | `"asc"` | Sort direction: `"asc"` or `"desc"`. |
| `distinct` | `bool` | `False` | If `True`, return only unique combinations of selected fields. |
| `transform` | `TransformExpression \| None` | `None` | Conditional math expression (CASE WHEN) to compute a derived column. |
| `filter_logic` | `str` | `"AND"` | How multiple filters combine: `"AND"` or `"OR"`. |
| `context` | `Context` | `None` | MCP request context. |

**Returns:** `str` -- JSON string:

```json
{
  "data": [{"name": "Alice", "age": 32}],
  "count": 1,
  "total_count": 150
}
```

`total_count` is the number of rows matching the filters before the `limit` is applied.

**Example -- filter and sort:**

```json
{
  "filters": [{"column": "age", "operator": ">", "value": 30}],
  "fields": ["name", "age"],
  "order_by": "age",
  "order": "desc",
  "limit": 10
}
```

**Example -- transform (normalize mixed units):**

```json
{
  "transform": {
    "source_column": "usage_amount",
    "cases": [
      {"when": [{"column": "unit", "value": "gallons"}], "then_multiply": 3.785},
      {"when": [{"column": "unit", "value": "liters"}], "then_multiply": 1}
    ],
    "else_multiply": 1,
    "alias": "usage_liters"
  },
  "order_by": "usage_liters",
  "order": "desc"
}
```

---

### Tool: `aggregate`

```python
async def aggregate(
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
    context: Context = None,
) -> str:
```

Runs an aggregation operation (count, sum, avg, min, max) on the data table with optional grouping, HAVING filters, and conditional value transformation.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `operation` | `str` | *(required)* | Aggregation function: `"count"`, `"sum"`, `"avg"`, `"min"`, or `"max"`. |
| `field` | `str \| None` | `None` | Column to aggregate. Not required for `"count"` or when `transform` is provided. |
| `group_by` | `str \| list[str] \| None` | `None` | Column(s) to group results by. |
| `filters` | `list[FilterCondition] \| None` | `None` | Row filters (same format as `select_rows`). |
| `limit` | `int` | `20` | Max groups to return. Clamped to `[1, 100]`. |
| `order_by` | `str \| None` | `None` | Column or `"@result"` to sort by the aggregated value. |
| `order` | `str` | `"desc"` | Sort direction: `"asc"` or `"desc"`. |
| `having_operator` | `str \| None` | `None` | Comparison operator for HAVING clause (`=`, `!=`, `>`, `>=`, `<`, `<=`). |
| `having_value` | `float \| None` | `None` | Threshold value for the HAVING clause. |
| `transform` | `TransformExpression \| None` | `None` | Conditional math expression applied before aggregating. |
| `filter_logic` | `str` | `"AND"` | How multiple filters combine: `"AND"` or `"OR"`. |
| `context` | `Context` | `None` | MCP request context. |

**Returns:** `str` -- JSON string:

```json
{
  "data": [{"city": "London", "result": 42}],
  "count": 1
}
```

**Example -- count by group:**

```json
{
  "operation": "count",
  "group_by": "city",
  "order_by": "@result",
  "order": "desc",
  "limit": 5
}
```

**Example -- average with HAVING:**

```json
{
  "operation": "avg",
  "field": "salary",
  "group_by": "department",
  "having_operator": ">",
  "having_value": 50000,
  "order_by": "@result",
  "order": "desc"
}
```

**Example -- aggregate over transformed values:**

```json
{
  "operation": "sum",
  "transform": {
    "source_column": "usage_amount",
    "cases": [
      {"when": [{"column": "unit", "value": "gallons"}, {"column": "frequency", "value": "Monthly"}], "then_multiply": 3.785}
    ],
    "else_multiply": 1,
    "alias": "monthly_liters"
  },
  "group_by": "region",
  "order_by": "@result",
  "order": "desc"
}
```

---

## Main entry point

```python
if __name__ == "__main__":
    uvicorn.run(http_app, host=host, port=port)
```

When the module is executed directly (`python server.py`), it starts the Starlette ASGI application via `uvicorn` on the configured host and port.

**Default address:** `http://0.0.0.0:3001`

**Endpoints available:**

| Path | Protocol | Description |
|------|----------|-------------|
| `/mcp` | MCP streamable-HTTP | MCP tool transport (get_schema, select_rows, aggregate). |
| `/health` | HTTP GET | Liveness health check returning `{"status": "ok"}`. |

---

## Dependency graph

```
server.py
  |
  +-- Config                       (shared.config)
  +-- FastMCP                      (mcp.server.fastmcp)
  +-- uvicorn
  +-- JSONResponse                 (starlette.responses)
  |
  +-- tool_handlers
  |     +-- get_schema
  |     +-- select_rows
  |     +-- aggregate
  |
  +-- CSVParser                    (data_store.csv_parser)
  +-- ColumnEnricher               (enrichment.column_enricher)
  |     +-- NominalDateRule
  |     +-- MonthExtractionRule
  |     +-- YearExtractionRule
  +-- SqliteIngester               (data_store.sqlite_ingester)
  +-- SqliteDataStore              (data_store.sqlite_data_store)
  +-- DataStore                    (data_store.data_store) -- abstract
  +-- DataIngestor                 (data_store.data_ingestor) -- abstract
```

---

## Configuration reference

All configuration values are read from `shared.config.Config`. The following keys are used directly or transitively by `server.py`:

| Key | Default | Used by |
|-----|---------|---------|
| `mcp_server.host` | `"0.0.0.0"` | Server bind address. |
| `mcp_server.port` | `3001` | Server listen port. |
| `mcp_server.streamable_http_path` | `"/mcp"` | MCP transport path. |
| `mcp_server.db_path` | `"/app/db/shapes.db"` | Ephemeral SQLite database file path. |
| `mcp_server.csv_file_path` | `"/app/data/people-list-export.csv"` | Source CSV file path. |
| `mcp_server.default_query_limit` | `20` | Default row limit for queries. |
| `mcp_server.max_query_limit` | `100` | Maximum allowed row limit. |
| `mcp_server.numeric_threshold` | `0.8` | Ratio threshold for numeric type detection. |
| `mcp_server.enrichment.detection_sample_size` | `20` | Rows sampled for enrichment rule detection. |
| `mcp_server.enrichment.max_samples` | `3` | Sample values stored per enriched column. |
| `mcp_server.enrichment.nominal_date_epoch` | `"1970-01-01"` | Epoch used for nominal date calculations. |
