# Bug Report: Gemini MALFORMED_FUNCTION_CALL on Complex Tool Calls

## Status

**Unresolved.** Gemini fails to answer queries that require the `transform` parameter in `aggregate` or `select_rows` tool calls.

## Symptom

When a user asks a question that requires salary normalization (e.g., "what is the average salary per country?"), the LLM returns:

> "Sorry, I had trouble formatting my response. Please try again."

The tool trace shows the LLM successfully called simpler tools (`get_schema`, basic `aggregate`) but failed when it attempted to construct a complex `aggregate` call with a nested `transform` parameter.

## Affected Query Types

Any question where the LLM needs to use the `transform` parameter to normalize data before aggregating. Examples:

- "What is the average salary per country?"
- "Who are the highest paid employees?" (when salary types are mixed)
- "Compare average salaries between cities"
- Any salary aggregation where `salary_type` has mixed values (Yearly, Monthly, Hourly)

The system prompt explicitly instructs the LLM to use `transform` for these cases:

```
Before aggregating numeric columns, check if related columns indicate different units or categories.
For example, if a 'salary_amount' column exists alongside 'salary_type' (Yearly/Monthly/Hourly)
or 'salary_currency' (USD/GBP/ILS), you MUST use the transform parameter to normalize values,
or filter to a single type/currency before aggregating.
```

## Observed Behavior (from Docker logs)

### Attempt 1: "what is the average salary per country?"

```
07:32:17 Gemini API call → 200 OK   → tool_call: get_schema()
07:32:18 MCP tool executed           → schema returned successfully
07:32:18 Gemini API call → 200 OK   → tool_calls: aggregate(count, group_by=salary_type),
                                                   aggregate(count, group_by=salary_currency)
07:32:34 MCP tools executed          → counts returned successfully
07:32:37 Gemini API call → 200 OK   → tool_calls: aggregate(count, group_by=salary_type) [re-exploration]
                                                   aggregate(count, group_by=salary_currency)
07:32:37 MCP tools executed          → counts returned successfully
07:32:41 Gemini API call → 200 OK   → finish_reason: MALFORMED_FUNCTION_CALL ← FAILURE
         WARNING: "Gemini produced a malformed function call"
         Response: "Sorry, I had trouble formatting my response. Please try again."
```

### Attempt 2: "what is the average salary per country?" (retry)

```
07:33:38 Gemini API call → 200 OK   → tool_call: get_schema()
07:33:38 MCP tool executed           → schema returned successfully
07:33:47 Gemini API call → 200 OK   → finish_reason: MALFORMED_FUNCTION_CALL ← FAILURE
         WARNING: "Gemini produced a malformed function call"
         Response: "Sorry, I had trouble formatting my response. Please try again."
```

In both cases, the LLM understood the query, explored the data schema, and then **failed at the point where it tried to construct the `aggregate` call with a `transform` parameter**.

## Root Cause

### 1. Schema Complexity Exceeds Gemini's Function Calling Capability

The `transform` parameter requires 3 levels of nested Pydantic models:

```
aggregate()
  └─ transform: TransformExpression          (level 1)
       ├─ source_column: str
       ├─ alias: str
       ├─ else_multiply: float | None
       ├─ else_value: float | None
       └─ cases: list[TransformCase]          (level 2)
            ├─ then_multiply: float | None
            ├─ then_value: float | None
            └─ when: list[FilterCondition]    (level 3)
                 ├─ column: str
                 ├─ operator: str
                 └─ value: str | int | float | list   ← union type
```

FastMCP auto-generates a JSON Schema from these Pydantic models, producing `$defs` with `$ref` pointers. The `GeminiLLMClient._resolve_refs()` method inlines these references, but the resulting schema is still deeply nested — and Gemini's function calling struggles to produce valid JSON conforming to it.

### 2. Union Types in the Schema

`FilterCondition.value` is typed as `str | int | float | list`, which generates an `anyOf` construct in JSON Schema:

```json
{
  "anyOf": [
    {"type": "string"},
    {"type": "integer"},
    {"type": "number"},
    {"type": "array"}
  ]
}
```

Gemini's function calling has documented limitations with `anyOf`/`oneOf` constructs. When combined with deep nesting, this makes it very likely for the model to produce structurally invalid JSON.

### 3. Unsupported Schema Keys Not Fully Stripped

The `_strip_unsupported_keys()` method (in `gemini_llm_client.py:138-146`) only removes `additionalProperties`. However, Pydantic-generated schemas also contain keys that Gemini does not support:

- `title` — generated on every Pydantic model and property
- `default` — generated for optional fields with default values
- `anyOf` — see above; Gemini has limited support

These extra keys may confuse Gemini's schema validator or the model's understanding of the expected structure.

### 4. No Retry on Failure

When Gemini returns `MALFORMED_FUNCTION_CALL`, the current handling in `_parse_response()` immediately returns a static error message as the final text response:

```python
# gemini_llm_client.py:165-167
if finish_reason and "MALFORMED_FUNCTION_CALL" in str(finish_reason):
    logger.warning("Gemini produced a malformed function call")
    return LLMResponse(text="Sorry, I had trouble formatting my response. Please try again.")
```

This `LLMResponse` has no `tool_calls`, so the orchestrator loop in `chat_orchestrator.py:33-37` treats it as the final answer:

```python
if not llm_response.tool_calls:
    return ChatResponse(
        answer=llm_response.text or "",
        tool_calls=tool_call_history,
    )
```

The error message is returned to the user as if it were the LLM's actual answer. There is no retry, no fallback to a simpler query strategy, and no indication to the user that a tool-call failure occurred.

## Data Context

The CSV (`data/people-list-export.csv`) has these salary-related columns:

| Column | Type | Sample Values |
|--------|------|---------------|
| `salary_amount` | numeric | 88000, 78000, 55000 |
| `salary_currency` | text | USD $, GBP £, ILS ₪ |
| `salary_type` | text | Yearly, Monthly, Hourly |
| `country` | text | United States, United Kingdom, Israel |

A correct `aggregate` call for "average salary per country" would require:

```json
{
  "operation": "avg",
  "group_by": "country",
  "transform": {
    "source_column": "salary_amount",
    "cases": [
      {
        "when": [{"column": "salary_type", "operator": "=", "value": "Monthly"}],
        "then_multiply": 12
      },
      {
        "when": [{"column": "salary_type", "operator": "=", "value": "Hourly"}],
        "then_multiply": 2080
      }
    ],
    "else_multiply": 1,
    "alias": "annual_salary"
  },
  "order_by": "@result",
  "order": "desc"
}
```

This is the JSON structure Gemini fails to produce correctly.

## Affected Files

| File | Role |
|------|------|
| `chat-server/src/llm_clients/gemini_llm_client.py:160-167` | `_parse_response()` — catches the malformed call, returns static error |
| `chat-server/src/llm_clients/gemini_llm_client.py:137-146` | `_strip_unsupported_keys()` — only strips `additionalProperties`, misses `title`/`default` |
| `chat-server/src/chat_orchestrator.py:33-37` | Treats the error text as a final answer with no retry |
| `shared/modules/data/transform_expression.py` | Defines the deeply nested `TransformExpression` / `TransformCase` models |
| `shared/modules/data/filter_condition.py:19` | Defines `value: str \| int \| float \| list` — the union type that generates `anyOf` |
| `shared/config.py:44-46` | System prompt instructs LLM to use transform for mixed salary types |

## Reproduction

1. Ensure `chat_server.llm_provider` is set to `"gemini"` in `shared/config.py` (current default)
2. `docker compose up --build`
3. Open `http://localhost:3000`
4. Ask: "What is the average salary per country?"
5. Observe: LLM calls `get_schema`, possibly some exploratory `aggregate` calls, then returns "Sorry, I had trouble formatting my response"
6. Check logs: `docker compose logs chat-backend | grep "malformed"`

## Relationship to Previous Bug

This is a **different issue** from the one documented in `BUG_REPORT_GEMINI_TOOL_SCHEMA.md`. That bug was about Gemini's API **rejecting** the schema entirely (`400 INVALID_ARGUMENT` due to `additionalProperties`). It was fixed by adding `_strip_unsupported_keys()`.

This new bug occurs **at generation time** — Gemini accepts the schema but the model **cannot produce valid JSON** conforming to it. The fix requires either simplifying the schema further or handling the failure gracefully.

## Timeline

- **2026-02-28 07:32:41 UTC** — First observed failure
- **2026-02-28 07:33:47 UTC** — Second observed failure (user retry)
