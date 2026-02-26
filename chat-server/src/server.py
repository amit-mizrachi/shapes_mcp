from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.config import Config
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.chat_response import ChatResponse
from agent_loop_orchestrator import AgentLoopOrchestrator
from llm_clients.claude_llm_client import ClaudeLLMClient
from llm_clients.gemini_llm_client import GeminiLLMClient
from mcp_client.mcp_client_manager import MCPClientManager

_MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:3001/mcp")
_MCP_MAX_CONCURRENT = 10
_SEMAPHORE_TIMEOUT = 30.0
_RETRY_ATTEMPTS = 10
_RETRY_SLEEP = 3
_TIMEOUT_SECONDS = 120

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    mcp_manager = MCPClientManager(
        url=_MCP_SERVER_URL,
        max_concurrent=_MCP_MAX_CONCURRENT,
        semaphore_timeout=_SEMAPHORE_TIMEOUT,
    )

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            await mcp_manager.initialize()
            logger.info("MCP connection established (attempt %d)", attempt)
            break
        except Exception:
            if attempt == _RETRY_ATTEMPTS:
                logger.error("Failed to connect to MCP server after %d attempts", _RETRY_ATTEMPTS)
                raise
            logger.warning("MCP connection attempt %d/%d failed, retrying in %ds...", attempt, _RETRY_ATTEMPTS, _RETRY_SLEEP)
            await asyncio.sleep(_RETRY_SLEEP)

    provider = Config.get("chat_server.llm_provider")
    if provider == "gemini":
        llm_client = GeminiLLMClient(
            model=Config.get("chat_server.gemini_model"),
            max_tokens=Config.get("chat_server.gemini_max_tokens"),
        )
    else:
        llm_client = ClaudeLLMClient(
            model=Config.get("chat_server.anthropic_model"),
            max_tokens=Config.get("chat_server.max_tokens"),
        )

    app.state.orchestrator = AgentLoopOrchestrator(
        llm_client=llm_client,
        mcp_manager=mcp_manager,
        system_prompt=Config.get("chat_server.system_prompt"),
        max_iterations=Config.get("chat_server.max_iterations"),
    )
    app.state.timeout = _TIMEOUT_SECONDS

    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, raw_request: Request):
    try:
        response = await asyncio.wait_for(
            raw_request.app.state.orchestrator.execute(request),
            timeout=raw_request.app.state.timeout,
        )
        return response
    except asyncio.TimeoutError:
        return JSONResponse(status_code=504, content={"detail": "Request timed out"})
    except Exception:
        logger.exception("Unhandled error in /chat")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
