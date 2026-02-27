"""E2E: FastAPI + real MCP pipeline + mocked LLM."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared.modules.llm.llm_response import LLMResponse
from shared.modules.llm.tool_call import ToolCall
from repository.csv_parser import CSVParser
from repository.sqlite_ingester import SqliteIngester
from repository.sqlite_data_store import SqliteDataStore


@pytest.fixture()
def real_mcp_pipeline(sample_csv_path, tmp_path):
    """Set up a real SQLite-backed MCP pipeline."""
    db_path = str(tmp_path / "e2e_chat.db")

    ingester = SqliteIngester(db_path)
    table_schema = ingester.ingest(CSVParser.parse(str(sample_csv_path)))
    repo = SqliteDataStore(db_path, table_schema)

    yield repo, table_schema


@pytest.fixture()
def mock_llm_for_e2e():
    """LLM that calls get_schema, then responds with text."""
    llm = AsyncMock()
    llm.invoke = AsyncMock(side_effect=[
        LLMResponse(
            text="Let me check the schema",
            tool_calls=[ToolCall(id="tc_1", name="get_schema", arguments={})],
        ),
        LLMResponse(text="The data has 5 columns.", tool_calls=[]),
    ])
    return llm


@pytest.fixture()
async def e2e_client(real_mcp_pipeline, mock_llm_for_e2e):
    """FastAPI app with real MCP tools + mocked LLM, bypassing the lifespan."""
    repo, _ = real_mcp_pipeline

    mock_mcp_client = AsyncMock()
    mock_mcp_client.call_tool = AsyncMock(side_effect=_make_tool_caller(repo))

    mock_manager = MagicMock()
    mock_manager.get_tools = MagicMock(return_value=[
        {"name": "get_schema", "description": "Get schema", "inputSchema": {}},
        {"name": "select_rows", "description": "Select rows", "inputSchema": {}},
        {"name": "aggregate", "description": "Aggregate", "inputSchema": {}},
    ])

    @asynccontextmanager
    async def _client():
        yield mock_mcp_client

    mock_manager.client = _client

    from chat_orchestrator import ChatOrchestrator
    from shared.config import Config

    orchestrator = ChatOrchestrator(
        llm_client=mock_llm_for_e2e,
        mcp_manager=mock_manager,
        system_prompt=Config.get("chat_server.system_prompt"),
        max_iterations=Config.get("chat_server.max_iterations"),
    )

    import server
    server.app.state.orchestrator = orchestrator
    server.app.state.timeout = 120

    # Bypass the real lifespan which connects to MCP server
    with patch("server.lifespan", _noop_lifespan):
        transport = ASGITransport(app=server.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def _make_tool_caller(repo):
    """Create a side_effect function that routes tool calls to the real repository."""
    import tool_handlers
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"repository": repo}

    async def call_tool(name, arguments):
        if name == "get_schema":
            return await tool_handlers.get_schema(ctx)
        elif name == "select_rows":
            return await tool_handlers.select_rows(**arguments, context=ctx)
        elif name == "aggregate":
            return await tool_handlers.aggregate(**arguments, context=ctx)
        return json.dumps({"error": f"Unknown tool: {name}"})

    return call_tool


@pytest.mark.e2e
class TestChatAPIE2E:
    async def test_health(self, e2e_client):
        resp = await e2e_client.get("/health")
        assert resp.status_code == 200

    async def test_chat_with_tool_usage(self, e2e_client):
        resp = await e2e_client.post("/chat", json={
            "messages": [{"role": "user", "content": "What data do you have?"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "5 columns" in data["answer"]
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool"] == "get_schema"

    async def test_empty_messages_rejected(self, e2e_client):
        resp = await e2e_client.post("/chat", json={"messages": []})
        assert resp.status_code == 422
