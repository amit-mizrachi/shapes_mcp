# Shared Modules Reference

The `shared/modules/` package contains all domain models shared between the MCP server and chat server. Every model extends `ShapesBaseModel` (a thin Pydantic `BaseModel` subclass). The package is organized into three subpackages: `api/`, `llm/`, and `data/`.

---

## Base

### `ShapesBaseModel` — `shared/modules/shapes_base_model.py`

Project-wide Pydantic base class. All other models inherit from it, providing a single place to add shared model configuration.

**Used by:** Every other module in `shared/modules/` (12 files).

---

## API Models — `shared/modules/api/`

Request/response shapes for the chat HTTP API.

### `MessageItem` — `shared/modules/api/message_item.py`

A single chat message turn with `role` and `content` fields.

```python
from shared.modules.api.message_item import MessageItem

msg = MessageItem(role="user", content="What is the average salary?")
```

**Used by:** `ChatRequest` (internally), test files for chat orchestrator and request validation.

---

### `ChatRequest` — `shared/modules/api/chat_request.py`

Incoming API payload — wraps a list of `MessageItem` (1-50 items).

```python
from shared.modules.api.chat_request import ChatRequest

request = ChatRequest(messages=[MessageItem(role="user", content="How many employees?")])
```

**Used by:** `chat-server/src/server.py` (endpoint handler), `chat-server/src/chat_orchestrator.py`, tests.

---

### `ChatResponse` — `shared/modules/api/chat_response.py`

Outgoing API payload — contains the `answer` text and a list of `ToolCallEvent` objects.

```python
from shared.modules.api.chat_response import ChatResponse

response = ChatResponse(answer="There are 42 employees.", tool_calls=[...])
```

**Used by:** `chat-server/src/server.py`, `chat-server/src/chat_orchestrator.py`, tests.

---

### `ToolCallEvent` / `ToolCallEventStatus` — `shared/modules/api/tool_call_event.py`

Records a single tool invocation attempt with status (`success`, `error`, `malformed`), tool name, arguments, optional error message, and retry attempt number. Surfaced in API responses for frontend trace display.

```python
from shared.modules.api.tool_call_event import ToolCallEvent, ToolCallEventStatus

event = ToolCallEvent(
    status=ToolCallEventStatus.SUCCESS,
    tool="aggregate",
    arguments={"operation": "count"},
)
```

**Used by:** `chat-server/src/chat_orchestrator.py`, `ChatResponse` (internally).

---

## LLM Models — `shared/modules/llm/`

Structured representations of LLM output, used by all LLM client implementations.

### `ToolCall` — `shared/modules/llm/tool_call.py`

A single tool invocation parsed from an LLM's raw response — `id`, `name`, and `arguments`.

```python
from shared.modules.llm.tool_call import ToolCall

tc = ToolCall(id="call_1", name="get_schema", arguments={})
```

**Used by:** `claude_llm_client.py`, `gemini_llm_client.py`, `chat_orchestrator.py`, e2e tests, unit tests (8 external files).

---

### `LLMResponse` — `shared/modules/llm/llm_response.py`

Complete structured output from an LLM call: optional `text`, list of `ToolCall` objects, and malformed function call tracking (`malformed_function_call`, `malformed_message`).

```python
from shared.modules.llm.llm_response import LLMResponse

response = LLMResponse(
    text="Here are the results...",
    tool_calls=[ToolCall(id="1", name="aggregate", arguments={"operation": "avg"})],
)
```

**Used by:** All LLM clients, `chat_orchestrator.py`, `llm_client.py` (abstract base), e2e tests, unit tests (8 external files).

---

## Data Models — `shared/modules/data/`

Domain types for schema metadata, query parameters, and query results. Used across the MCP server's data layer.

### `ColumnInfo` — `shared/modules/data/column_info.py`

Describes a single table column: `name`, `detected_type`, and `samples` (representative values).

```python
from shared.modules.data.column_info import ColumnInfo

col = ColumnInfo(name="salary_amount", detected_type="numeric", samples=["50000", "72000"])
```

**Used by:** `csv_parser.py`, all enrichment rules, `TableSchema`, `ParsedCSV`, query builder tests, enrichment tests (16 external files — the most widely imported module).

---

### `TableSchema` — `shared/modules/data/table_schema.py`

Full schema descriptor: `table_name` + list of `ColumnInfo`.

```python
from shared.modules.data.table_schema import TableSchema

schema = TableSchema(table_name="people", columns=[col1, col2])
```

**Used by:** `data_store.py` (abstract), `sqlite_data_store.py`, `sqlite_query_builder.py`, `sqlite_ingester.py`, `data_ingestor.py`, tests (9 external files).

---

### `FilterCondition` — `shared/modules/data/filter_condition.py`

A query filter with `column`, `operator`, and `value`. Validates operators (`=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`) and enforces type-appropriate values.

```python
from shared.modules.data.filter_condition import FilterCondition

f = FilterCondition(column="city", operator="IN", value=["London", "Paris"])
```

**Used by:** `tool_handlers.py`, `sqlite_data_store.py`, `sqlite_query_builder.py`, `data_store.py`, `TransformExpression` (internally), e2e and unit tests (9 external files).

---

### `TransformExpression` / `TransformCase` — `shared/modules/data/transform_expression.py`

Conditional math (CASE WHEN) for deriving computed columns before aggregation or selection. Used to normalize mixed units, currencies, or categories.

- `TransformCase`: A single branch — list of `FilterCondition` conditions + `then_multiply` or `then_value`.
- `TransformExpression`: Full specification — `source_column`, up to 10 `cases`, `else_multiply`/`else_value` fallback, and an `alias` for the output column.

```python
from shared.modules.data.transform_expression import TransformExpression, TransformCase
from shared.modules.data.filter_condition import FilterCondition

transform = TransformExpression(
    source_column="salary_amount",
    cases=[
        TransformCase(
            when=[FilterCondition(column="salary_type", value="Monthly")],
            then_multiply=12,
        ),
    ],
    else_multiply=1,
    alias="annual_salary",
)
```

**Used by:** `tool_handlers.py`, `sqlite_data_store.py`, `sqlite_query_builder.py`, `data_store.py`, tests (7 external files).

---

### `QueryResult` — `shared/modules/data/query_result.py`

Output of a data query: `columns` (header names), `rows` (list of dicts), `count` (rows returned), and optional `total_count` (total before pagination).

```python
from shared.modules.data.query_result import QueryResult

result = QueryResult(
    columns=["full_name", "city"],
    rows=[{"full_name": "John Smith", "city": "London"}],
    count=1,
    total_count=42,
)
```

**Used by:** `tool_handlers.py`, `sqlite_data_store.py`, `data_store.py`, tests (5 external files).

---

### `ParsedCSV` — `shared/modules/data/parsed_csv.py`

Represents an ingested CSV file: `table_name`, list of `ColumnInfo` columns, and raw `rows`. Exposes a `headers` property for column name extraction.

```python
from shared.modules.data.parsed_csv import ParsedCSV

csv = ParsedCSV(table_name="people", columns=[col1, col2], rows=[{"name": "Alice"}])
print(csv.headers)  # ["name"]
```

**Used by:** `csv_parser.py`, `data_ingestor.py`, `sqlite_ingester.py`, `column_enricher.py`, tests (6 external files).
