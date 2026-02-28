# Fix: Malformed Function Call Retry Mechanism

## Problem

When Gemini's function calling produces structurally invalid JSON (e.g., for complex nested tool parameters like `transform`), the API returns `finish_reason: MALFORMED_FUNCTION_CALL` with no usable content. Previously, this was handled by returning a static error message — "Sorry, I had trouble formatting my response. Please try again." — directly to the user as if it were the LLM's answer. There was no retry, no fallback, and no indication that a recoverable failure occurred.

## What Changed

Three files were modified to add a retry mechanism that gives the LLM a second chance when it produces a malformed function call.

### 1. `shared/modules/llm/llm_response.py`

Added `malformed_function_call: bool = False` to the shared `LLMResponse` model. This flag signals to the orchestrator that the LLM attempted a tool call but failed to produce valid JSON.

- Backward-compatible: defaults to `False`
- Provider-agnostic: any LLM client can set it, but currently only Gemini does
- Claude client is unaffected — it never sets this flag

### 2. `chat-server/src/llm_clients/gemini_llm_client.py`

Updated `_parse_response()` to set `LLMResponse(malformed_function_call=True)` when `MALFORMED_FUNCTION_CALL` is detected, instead of returning the static error text. Also enhanced logging to capture `finish_message` from the Gemini response for debugging.

**Before:**
```python
return LLMResponse(text="Sorry, I had trouble formatting my response. Please try again.")
```

**After:**
```python
return LLMResponse(malformed_function_call=True)
```

### 3. `chat-server/src/chat_orchestrator.py`

Added retry logic to the agentic loop in `execute()`:

- When `llm_response.malformed_function_call` is `True`, the orchestrator appends a corrective hint as a user message and retries the LLM call
- Maximum 2 retries to avoid burning through the iteration budget
- If retries are exhausted, returns a clear error message explaining the limitation
- The retry hint tells the LLM: "Your previous function call was malformed. Please try again with a simpler structure."

**Retry flow:**
```
LLM produces malformed call
  → orchestrator detects flag
  → appends corrective hint to message history
  → re-invokes LLM (attempt 1/2)
  → if still malformed, retry once more (attempt 2/2)
  → if still failing, return clear error to user
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Flag lives on shared `LLMResponse`, not Gemini-specific | Any future provider that encounters similar issues can reuse the same retry mechanism |
| Retry lives in the orchestrator, not the LLM client | The client's job is to report; the orchestrator decides retry policy. Clean separation of concerns |
| Corrective hint injected as user message | Gives the LLM context about what went wrong and nudges it toward a simpler call structure |
| Max 2 retries | Balances recovery chance vs. token/latency cost. Uses 2 of the 10 iteration budget |
| Claude client unchanged | Claude handles complex schemas natively and never triggers this code path |
