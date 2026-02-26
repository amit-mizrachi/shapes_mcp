from __future__ import annotations

import asyncio
import logging
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

logging.basicConfig(
    level=Config.get("shared.log_level"),
    format=Config.get("shared.log_format"),
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    mcp_manager = MCPClientManager(
        url=Config.get("chat_server.mcp_server_url"),
        max_concurrent=Config.get("chat_server.mcp_max_concurrent"),
        semaphore_timeout=Config.get("chat_server.semaphore_timeout"),
    )

    retry_attempts = Config.get("chat_server.retry_attempts")
    retry_sleep = Config.get("chat_server.retry_sleep")
    for attempt in range(1, retry_attempts + 1):
        try:
            await mcp_manager.initialize()
            logger.info("MCP connection established (attempt %d)", attempt)
            break
        except Exception:
            if attempt == retry_attempts:
                logger.error("Failed to connect to MCP server after %d attempts", retry_attempts)
                raise
            logger.warning("MCP connection attempt %d/%d failed, retrying in %ds...", attempt, retry_attempts, retry_sleep)
            await asyncio.sleep(retry_sleep)

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
    app.state.timeout = Config.get("chat_server.timeout_seconds")

    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.get("chat_server.cors_origins"),
    allow_methods=Config.get("chat_server.cors_methods"),
    allow_headers=Config.get("chat_server.cors_headers"),
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
