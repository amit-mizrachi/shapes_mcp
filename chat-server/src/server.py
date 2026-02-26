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
from chat_orchestrator import ChatOrchestrator
from llm_clients.llm_client_factory import LLMClientFactory
from mcp_client.mcp_client_manager import MCPClientManager

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    mcp_server_url = Config.get("chat_server.mcp_server_url")
    mcp_max_concurrent = Config.get("chat_server.mcp_max_concurrent")
    semaphore_timeout = Config.get("chat_server.semaphore_timeout")
    mcp_manager = MCPClientManager(
        url=mcp_server_url,
        max_concurrent=mcp_max_concurrent,
        semaphore_timeout=semaphore_timeout,
    )

    retry_attempts = Config.get("chat_server.mcp_connection.retry_attempts")
    retry_sleep = Config.get("chat_server.mcp_connection.retry_sleep")
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

    llm_provider = Config.get("chat_server.llm_provider")
    llm_client = LLMClientFactory.create(llm_provider)

    app.state.orchestrator = ChatOrchestrator(
        llm_client=llm_client,
        mcp_manager=mcp_manager,
        system_prompt=Config.get("chat_server.system_prompt"),
        max_iterations=Config.get("chat_server.max_iterations"),
    )

    timeout_seconds = Config.get("chat_server.timeout_seconds")
    app.state.timeout = timeout_seconds

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
