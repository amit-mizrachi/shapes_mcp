from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from shared.config import Config
from chat_orchestrator import ChatOrchestrator
from shared.modules.api.chat_request import ChatRequest
from shared.modules.api.chat_response import ChatResponse
from mcp_client.mcp_client_manager import MCPClientManager
from llm.claude.claude_llm_client import ClaudeLLMClient

logging.basicConfig(level=Config.get("shared.log_level"), format=Config.get("shared.log_format"))
logger = logging.getLogger(__name__)

mcp_manager: MCPClientManager | None = None
orchestrator: ChatOrchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_manager, orchestrator

    mcp_manager = MCPClientManager(
        url=Config.get("chat_server.mcp_server_url"),
        max_concurrent=Config.get("chat_server.mcp_max_concurrent"),
    )

    retry_attempts = Config.get("chat_server.retry_attempts")
    for attempt in range(retry_attempts):
        try:
            await mcp_manager.initialize()
            logger.info("MCP client ready")
            break
        except Exception as e:
            logger.warning("MCP connection attempt failed, retrying")
            if attempt < retry_attempts - 1:
                await asyncio.sleep(Config.get("chat_server.retry_sleep"))
            else:
                raise RuntimeError("Could not connect to MCP server") from e

    llm_client = ClaudeLLMClient(model=Config.get("chat_server.anthropic_model"))
    orchestrator = ChatOrchestrator(llm_client, mcp_manager)
    logger.info("Chat server started")
    yield


app = FastAPI(title="Chat Server", lifespan=lifespan)

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
async def chat(request: ChatRequest):
    max_length = Config.get("chat_server.message_max_length")
    for msg in request.messages:
        if len(msg.content) > max_length:
            raise HTTPException(status_code=422, detail=f"Message content exceeds {max_length} character limit.")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    try:
        return await orchestrator.chat(messages)
    except ConnectionError as e:
        logger.warning("MCP connection error")
        raise HTTPException(status_code=503, detail="Server busy. Please try again shortly.")
    except Exception as e:
        logger.error("Chat request failed", exc_info=True)
        if "rate_limit" in str(e).lower() or "429" in str(e):
            raise HTTPException(status_code=429, detail="Rate limit reached. Please wait and try again.")
        raise HTTPException(status_code=500, detail="An internal error occurred.")
