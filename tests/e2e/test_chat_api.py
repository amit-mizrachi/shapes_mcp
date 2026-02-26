"""E2E: FastAPI + real MCP pipeline + mocked LLM."""

import json
import sqlite3
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from shared.modules.chat_result import ChatResult
from shared.modules.llm_response import LLMResponse
from shared.modules.tool_call import ToolCall
from repository.sqlite.sqlite_ingester import SqliteIngester
from repository.sqlite.sqlite_repository import SqliteRepository


@pytest.fixture()
def real_mcp_pipeline(sample_csv_path):
    """Set up a real SQLite-backed MCP pipeline."""
    db_name = f"e2e_chat_{uuid.uuid4().hex[:8]}"
    db_uri = f"file:{db_name}?mode=memory&cache=shared"
    keeper = sqlite3.connect(db_uri, uri=True)

    ingester = SqliteIngester(db_uri)
    result = ingester.ingest(str(sample_csv_path))
    repo = SqliteRepository(db_uri, result.table_name, result.columns)

    yield repo, result

    keeper.close()


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
    """FastAPI app with real MCP tools + mocked LLM."""
    repo, result = real_mcp_pipeline

    # Build a mock MCP manager that yields a real-ish tool calling interface
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

    with patch("main.MCPClientManager") as mock_mgr_cls, \
         patch("main.ClaudeLLMClient") as mock_llm_cls, \
         patch("main.ChatOrchestrator") as mock_orch_cls:

        mock_mgr_cls.return_value = MagicMock(initialize=AsyncMock())
        mock_llm_cls.return_value = mock_llm_for_e2e

        from chat_orchestrator import ChatOrchestrator
        real_orch = ChatOrchestrator(mock_llm_for_e2e, mock_manager)

        import main
        main.mcp_manager = mock_manager
        main.orchestrator = real_orch

        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


def _make_tool_caller(repo):
    """Create a side_effect function that routes tool calls to the real repository."""
    import tools
    from unittest.mock import MagicMock

    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"repository": repo}

    async def call_tool(name, arguments):
        if name == "get_schema":
            return await tools.get_schema(ctx)
        elif name == "select_rows":
            return await tools.select_rows(**arguments, ctx=ctx)
        elif name == "aggregate":
            return await tools.aggregate(**arguments, ctx=ctx)
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
