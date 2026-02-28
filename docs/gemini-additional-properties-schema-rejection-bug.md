# Bug Report: Gemini 400 INVALID_ARGUMENT on Tool Schemas

## Status
Unresolved. Blocked from using Gemini as LLM provider.

## Symptom
When the chat-backend is configured with `llm_provider: "gemini"`, every `/chat` request returns HTTP 500. The Gemini API rejects the tool schemas with a `400 INVALID_ARGUMENT` error.

## Error
```
google.genai.errors.ClientError: 400 INVALID_ARGUMENT.
{
  "error": {
    "code": 400,
    "message": "Invalid JSON payload received. Unknown name \"additional_properties\" at 'tools[0].function_declarations[1].parameters.properties[0].value.any_of[0].items': Cannot find field.\nInvalid JSON payload received. Unknown name \"additional_properties\" at 'tools[0].function_declarations[2].parameters.properties[3].value.any_of[0].items': Cannot find field.",
    "status": "INVALID_ARGUMENT",
    "details": [
      {
        "fieldViolations": [
          {
            "field": "tools[0].function_declarations[1].parameters.properties[0].value.any_of[0].items",
            "description": "Unknown name \"additional_properties\""
          },
          {
            "field": "tools[0].function_declarations[2].parameters.properties[3].value.any_of[0].items",
            "description": "Unknown name \"additional_properties\""
          }
        ]
      }
    ]
  }
}
```

## Root Cause

The three MCP tools (`get_schema`, `select_rows`, `aggregate`) are defined in `mcp-server/src/tools.py` using Python type hints (`list[dict] | None`). FastMCP auto-generates JSON Schemas from these type hints. The generated schemas include `additionalProperties` on nested objects (specifically inside the `filters: list[dict]` parameter).

The data flow:
1. **FastMCP** generates JSON Schema for each tool from Python type hints → includes `additionalProperties`
2. **chat-backend** fetches these schemas via `MCPClient.list_tools()` during startup and caches them
3. **GeminiLLMClient._convert_tools()** (`chat-server/src/llm_clients/gemini_llm_client.py:89`) passes `inputSchema` directly to Gemini as `parameters` in `FunctionDeclaration`
4. **google-genai SDK** converts the schema keys to snake_case (`additionalProperties` → `additional_properties`) before sending to the API
5. **Gemini API** does not recognize `additional_properties` and rejects the payload

The two affected tools are:
- `tools[0].function_declarations[1]` = `select_rows` — the `filters` parameter (`list[dict]`) generates a schema with `anyOf` containing an `items` object with `additionalProperties`
- `tools[0].function_declarations[2]` = `aggregate` — same `filters` parameter, same issue

Claude handles these schemas fine because the Anthropic API accepts standard JSON Schema including `additionalProperties`. Gemini's function calling API supports only a subset of JSON Schema.

## Affected Files
- `chat-server/src/llm_clients/gemini_llm_client.py` — `_convert_tools()` at line 89 passes raw MCP schemas without sanitization
- `mcp-server/src/tools.py` — tool definitions with `list[dict]` type hints that produce the problematic schema

## Reproduction
1. Set `chat_server.llm_provider` to `"gemini"` in `shared/config.py`
2. `docker compose up --build`
3. Send any message via the frontend at http://localhost:3000
4. Backend returns 500, logs show the error above

## Notes
- Claude provider works fine with the same tool schemas
- The issue is specifically with nested schema fields inside `anyOf` / `items` — top-level `additionalProperties` might also be affected but isn't triggered currently
- The google-genai SDK (v1.65.0) does the camelCase→snake_case conversion automatically, which is why the error says `additional_properties` (snake) even though the source schema has `additionalProperties` (camel)
