# MCP Chat

A CSV-agnostic data exploration platform that combines an **MCP (Model Context Protocol)** server with an **LLM-powered chat interface**. Drop any CSV file into the `data/` directory, spin up the containers, and ask questions about your data in natural language.

The system parses the CSV into SQLite, exposes structured query tools via MCP, and uses an LLM agent (Claude or Gemini) that autonomously calls those tools to answer your questions — complete with filtering, aggregation, sorting, and conditional value normalization.

## Architecture

```
┌──────────────┐     ┌───────────────┐     ┌────────────┐
│   Frontend   │────▶│  Chat Backend │────▶│ MCP Server │
│  (React/Vite)│ API │   (FastAPI)   │ MCP │  (FastMCP) │
│   port 3000  │◀────│   port 3002   │◀────│  port 3001 │
└──────────────┘     └───────────────┘     └────────────┘
                            │                     │
                            ▼                     ▼
                    Claude / Gemini API     SQLite (from CSV)
```

**Three Docker Compose services:**

| Service | Description |
|---------|-------------|
| **MCP Server** | Ingests a CSV into SQLite on startup. Exposes `get_schema()`, `select_rows()`, and `aggregate()` tools via MCP Streamable HTTP transport. Table name is derived from the CSV filename (e.g., `orders.csv` &rarr; table `orders`). |
| **Chat Backend** | FastAPI service that receives conversation history, orchestrates an LLM agent loop with per-request ephemeral MCP client sessions, and returns answers with tool call traces. Supports Claude and Gemini as LLM providers. |
| **Chat Frontend** | React SPA served by Nginx. Renders markdown responses (tables, code blocks, lists), maintains full conversation history for follow-up questions, and displays tool call traces for transparency. |

Only port **3000** (Nginx) is exposed to the host. The MCP server and chat backend communicate over the internal Docker network.

## Quick Start

```bash
# 1. Clone and configure
git clone <repo-url> && cd shapes_mcp
cp .env.example .env
# Edit .env and add your API key(s)

# 2. Create data/ and place any CSV file in it
mkdir -p data
cp your-data.csv data/

# 3. Update the CSV path in shared/config.py
# Set "mcp_server.csv_file_path" to match your filename

# 4. Build and run
docker compose up --build

# 5. Open the UI
open http://localhost:3000
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | When using Claude | Anthropic API key |
| `GOOGLE_API_KEY` | When using Gemini | Google AI API key |

The active LLM provider is set in `shared/config.py` via `chat_server.llm_provider` (default: `"gemini"`).

## MCP Tools

The MCP server exposes three tools that the LLM agent uses autonomously:

### `get_schema()`

Discover table structure, column names, data types, and sample values. Returns a `date_context` object for date arithmetic. **Called first** by the agent to understand available data.

### `select_rows()`

Retrieve rows with rich query capabilities:

- **Filtering** — multiple conditions with AND/OR logic. Operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `LIKE`, `NOT LIKE`, `IN`, `NOT IN`, `IS NULL`, `IS NOT NULL`
- **Field selection** — return only specific columns
- **Sorting** — by any column, ascending or descending
- **Distinct** — unique value combinations
- **Transform** — conditional CASE WHEN logic for normalizing mixed units/currencies before display
- **Pagination** — configurable limit (default 20, max 100)

### `aggregate()`

Run aggregations with grouping:

- **Operations** — `count`, `sum`, `avg`, `min`, `max`
- **Group by** — single or multi-column grouping
- **HAVING** — filter groups by the aggregated result
- **Sort by `@result`** — order groups by the computed aggregate (e.g., top 5 cities by count)
- **Transform** — normalize values before aggregating (e.g., convert mixed units to a common base)

## Features

### CSV-Agnostic Ingestion
Drop any CSV into `data/`. The system automatically parses it, detects column types (numeric vs. text), sanitizes column names, and loads it into SQLite.

### Date Column Enrichment
Date columns are automatically detected and enriched with three derived columns:
- `{col}_days` — days since epoch (1970-01-01), for duration/age math
- `{col}_month` — month number (1–12)
- `{col}_year` — four-digit year

### Multi-Dimensional Value Normalization
The `transform` parameter enables CASE WHEN logic so the LLM can normalize mixed units across multiple dimensions (e.g., converting water usage that varies by both unit *and* frequency into a common base) — all within safe, parameterized SQL.

### Typed Message Hierarchy

The chat orchestrator communicates with LLM clients through a typed message hierarchy rather than raw dicts. All message types inherit from `ChatMessage`:

| Type | Fields | Description |
|------|--------|-------------|
| `SystemMessage` | `content: str` | System prompt injected at the start of every conversation. |
| `UserMessage` | `content: str` | A user's natural-language input, or a retry hint after a malformed tool call. |
| `AssistantMessage` | `text: str \| None`, `tool_calls: list[ToolCall]` | The LLM's response — may contain text, tool calls, or both. Validated to require at least one. |
| `ToolMessage` | `results: list[ToolResult]` | Tool execution results returned to the LLM for the next reasoning step. |
| `ToolResult` | `tool_call_id: str`, `name: str`, `content: str`, `is_error: bool` | A single tool's output, linked back to its call by ID. |

Each LLM client's `_convert_messages` method pattern-matches on these types and translates them to the provider's wire format (e.g., Claude's `tool_use`/`tool_result` blocks, Gemini's `FunctionCall`/`FunctionResponse` parts).

### Multi-Provider LLM Support
Swap between Claude and Gemini by changing a single config value. Both providers are abstracted behind an `LLMClient` interface with a typed `list[ChatMessage]` contract. Adding a new provider requires implementing the interface and adding one branch to the factory.

### Malformed Tool Call Recovery
When an LLM returns a malformed function call (common with complex schemas), the system automatically retries with a hint message — up to 2 retries per iteration.

### Tool Call Tracing
Every MCP tool execution is recorded and returned to the frontend, making the entire agent reasoning process visible and debuggable.

### Security

| Measure | Implementation |
|---------|---------------|
| SQL injection prevention | Parameterized queries; column names validated against schema |
| Read-only database | `PRAGMA query_only = ON` on every connection |
| Input validation | Pydantic models validate all tool inputs; operator whitelist; magnitude limits |
| Query limits | Hard cap of 100 rows per query |
| Request limits | Max 50 messages per request, 120s timeout |
| Container isolation | Non-root user, internal-only ports for backend services |
| Secret handling | API keys via env vars, `.env` in `.gitignore` |
| Concurrency control | Semaphore limits MCP connections to 10 concurrent |

## Example Questions

Once the app is running, try asking:

- "What columns are in the dataset?"
- "Show me the first 10 rows"
- "How many records are there?"
- "What is the average age grouped by job title?"
- "Show me the top 5 cities with the most people"
- "Find all rows where name contains 'Smith'"
- "Who is the youngest person in the dataset?"
- "What are the distinct values in the status column?"

## Project Structure

```
shapes_mcp/
├── docker-compose.yml                 # Service orchestration
├── .env.example                       # Environment template
├── pyproject.toml                     # Test configuration
├── shared/                            # Shared Python modules
│   ├── config.py                      # Centralized configuration
│   └── modules/
│       ├── api/                       # Request/response models
│       ├── data/                      # Domain models (filters, transforms, schema)
│       ├── llm/                       # LLM models
│       │   ├── llm_response.py        # Provider-agnostic LLM response
│       │   ├── tool_call.py           # Tool call (id, name, arguments)
│       │   ├── tool_result.py         # Tool result (content, is_error)
│       │   └── messages/              # Typed message hierarchy
│       │       ├── chat_message.py    # ChatMessage base class
│       │       ├── system_message.py  # SystemMessage
│       │       ├── user_message.py    # UserMessage
│       │       ├── assistant_message.py # AssistantMessage
│       │       └── tool_message.py    # ToolMessage
│       └── shapes_base_model.py       # Base Pydantic model
├── mcp-server/                        # MCP Server service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── server.py                  # FastMCP setup & lifespan
│       ├── tool_handlers.py           # get_schema, select_rows, aggregate
│       ├── data_store/
│       │   ├── csv_parser.py          # CSV parsing & type detection
│       │   ├── interfaces/            # DataStore & DataIngestor ABCs
│       │   └── sqlite/               # SQLite implementation
│       └── enrichment/                # Column enrichment pipeline
│           ├── column_enricher.py     # Enrichment orchestrator
│           └── rules/                 # Pluggable enrichment rules
│               └── date_enrichment_rule.py
├── chat-server/                       # Chat Backend service
│   ├── Dockerfile
│   ├── requirements.txt
│   └── src/
│       ├── server.py                  # FastAPI app (/chat, /health)
│       ├── chat_orchestrator.py       # LLM ↔ MCP agent loop
│       ├── llm_clients/
│       │   ├── llm_client.py          # Abstract LLMClient interface
│       │   ├── claude_llm_client.py   # Anthropic Claude adapter
│       │   ├── gemini_llm_client.py   # Google Gemini adapter
│       │   └── llm_client_factory.py  # Provider selection factory
│       └── mcp_client/
│           ├── mcp_client.py          # Per-request ephemeral MCP client
│           └── mcp_client_manager.py  # Concurrency control & tool caching
├── chat-frontend/                     # Frontend service
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── src/
│       ├── App.tsx                    # Main chat component
│       ├── api/chat.ts               # HTTP client
│       ├── hooks/                     # useChat, useAutoScroll
│       └── components/               # ChatInput, MessageList, ToolCallTrace, etc.
└── tests/                             # Test suite
    ├── unit/                          # Unit tests per service
    ├── e2e/                           # End-to-end pipeline tests
    └── fixtures/                      # Test CSV files
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| MCP Server | Python 3.12, FastMCP, aiosqlite |
| Chat Backend | Python 3.12, FastAPI, Uvicorn, Anthropic SDK, Google GenAI SDK |
| Frontend | React 18, TypeScript, Vite, react-markdown, remark-gfm |
| Infrastructure | Docker Compose, Nginx |
| Data Validation | Pydantic |
| Testing | pytest |

## Configuration

All application settings are centralized in `shared/config.py`. Key values:

| Setting | Default | Description |
|---------|---------|-------------|
| `mcp_server.port` | `3001` | MCP server port |
| `mcp_server.default_query_limit` | `20` | Default rows returned per query |
| `mcp_server.max_query_limit` | `100` | Maximum rows per query |
| `chat_server.llm_provider` | `"gemini"` | Active LLM provider (`"claude"` or `"gemini"`) |
| `chat_server.anthropic_model` | `claude-sonnet-4-20250514` | Claude model ID |
| `chat_server.gemini_model` | `gemini-2.5-pro` | Gemini model ID |
| `chat_server.max_iterations` | `10` | Max agent loop iterations |
| `chat_server.mcp_max_concurrent` | `10` | Max concurrent MCP connections |

## Testing

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run e2e tests
pytest tests/e2e/
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Dynamic table name from CSV filename | CSV-agnostic: `shapes.csv` &rarr; table `shapes`, `orders.csv` &rarr; table `orders` |
| Per-request MCP client sessions | Shared sessions are unsafe under concurrency; each request creates and closes its own session |
| Full conversation history per request | Enables follow-up questions without server-side session state |
| Tool call traces in response | Makes the MCP agent loop visible and debuggable |
| Streamable HTTP transport (not stdio) | Enables containerized deployment where MCP server is a separate network service |
| Typed message hierarchy | `ChatMessage` base class with `SystemMessage`, `UserMessage`, `AssistantMessage`, `ToolMessage` subtypes — eliminates dict-based `isinstance` branching in LLM clients |
| LLM abstraction layer | Straightforward to swap providers or add new ones via the `LLMClient` interface and typed message contract |
| Read-only parameterized queries | Defense in depth: SQLite in read-only mode + parameter binding + column validation |
| Enrichment pipeline with pluggable rules | New enrichment rules (currency, categorical) can be added without modifying existing code |
| Pydantic models as tool schemas | FastMCP auto-generates JSON Schema from type hints, giving the LLM rich validated schemas |
| Centralized config class | Single source of truth for all settings across both services, no scattered magic values |

## License

This project is for personal/educational use.
