# MCP Chat

A CSV-agnostic data exploration tool that combines an MCP (Model Context Protocol) server with an LLM-powered chat interface. Drop any CSV file into the `data/` directory and ask questions about it in natural language.

## Architecture

```
┌──────────────┐     ┌───────────────┐     ┌────────────┐
│   Frontend   │────▶│  Chat Backend │────▶│ MCP Server │
│  (React/Vite)│ API │   (FastAPI)   │ MCP │  (FastMCP) │
│   port 3000  │◀────│   port 3002   │◀────│  port 3001 │
└──────────────┘     └───────────────┘     └────────────┘
                            │                     │
                            ▼                     ▼
                      Claude API            SQLite (from CSV)
```

**Three Docker Compose services:**

1. **MCP Server** — Ingests a CSV into SQLite on startup. Table name derived from CSV filename (e.g., `shapes.csv` → table `shapes`). Exposes `get_schema()` and `query_data()` tools via MCP Streamable HTTP transport.
2. **Chat Backend** — FastAPI service that receives conversation history, orchestrates an LLM agent loop (Claude) with per-request MCP client sessions, and returns answers with tool call traces.
3. **Chat Frontend** — React SPA served by nginx. Renders markdown (tables, code, lists), maintains full conversation history for follow-up questions, proxies API calls to the backend.

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Edit .env and add your Anthropic API key

# 2. Place any CSV file in data/
cp your-data.csv data/

# 3. Build and run
docker compose up --build

# 4. Open http://localhost:3000
```

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Dynamic table name from CSV filename** | CSV-agnostic — `shapes.csv` creates table `shapes`, `orders.csv` creates table `orders` |
| **Per-request MCP client sessions** | Shared sessions are unsafe under concurrency. Each `/chat` request creates and closes its own MCP session |
| **Full conversation history** | Frontend sends the entire message array to enable follow-up questions without server-side session state |
| **Tool call trace in response** | API returns `{"answer": ..., "tool_calls": [...]}` making the MCP integration visible and debuggable |
| **Markdown rendering** | LLM responses contain tables and formatting; `react-markdown` renders them properly |
| **Internal ports not published** | Only port 3000 (nginx) is exposed to the host. MCP server and backend are internal to the Docker network |
| **Health checks** | `depends_on: condition: service_healthy` eliminates startup race conditions |
| **Input validation** | Max 50 messages, 5000 chars each — prevents token-cost abuse |
| **LLM abstraction** | `LLMClient` ABC makes it straightforward to swap Claude for another provider |
| **Read-only parameterized queries** | SQLite opened in read-only mode, all queries use parameter binding, column names validated against schema |

## Example Questions

- "What columns are in the dataset?"
- "Show me the first 5 rows"
- "How many records are there?"
- "What is the average of [numeric column]?"
- "Show me rows where [column] is greater than [value]"

## Project Structure

```
shapes_mcp/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── data/                          # Place CSV files here
├── mcp-server/                    # MCP server (FastMCP + SQLite)
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   └── src/
│       ├── main.py                # Server setup, /health, lifespan
│       ├── db.py                  # CSV ingestion, type detection
│       └── tools.py               # get_schema(), query_data()
├── chat-backend/                  # Chat API (FastAPI)
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt
│   └── src/
│       ├── main.py                # FastAPI app, POST /chat, GET /health
│       ├── orchestrator.py        # LLM ↔ MCP agent loop
│       ├── mcp_client.py          # Per-request MCP client
│       ├── config.py              # Pydantic Settings
│       └── llm/
│           ├── base.py            # LLMClient ABC
│           └── claude.py          # Claude implementation
└── chat-frontend/                 # React UI (Vite + nginx)
    ├── Dockerfile
    ├── .dockerignore
    ├── nginx.conf
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── index.html
        ├── main.tsx
        ├── App.tsx                # Chat orchestration
        ├── App.css
        └── components/
            └── ChatMessage.tsx    # Markdown-enabled message bubble
```
