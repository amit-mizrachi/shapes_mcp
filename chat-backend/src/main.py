from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import Settings
from orchestrator import ChatOrchestrator
from mcp_session_manager import MCPSessionManager
from llm.claude import ClaudeLLMClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

settings = Settings()
mcp_manager: MCPSessionManager | None = None
orchestrator: ChatOrchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_manager, orchestrator

    mcp_manager = MCPSessionManager(
        url=settings.MCP_SERVER_URL,
        max_concurrent=settings.MCP_MAX_CONCURRENT,
    )

    for attempt in range(10):
        try:
            await mcp_manager.initialize()
            logger.info("MCP client ready (max_concurrent=%d)", settings.MCP_MAX_CONCURRENT)
            break
        except Exception as e:
            logger.warning("MCP init attempt %d/10 failed: %s", attempt + 1, e)
            if attempt < 9:
                await asyncio.sleep(3)
            else:
                raise RuntimeError("Could not connect to MCP server") from e

    llm_client = ClaudeLLMClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.ANTHROPIC_MODEL,
    )
    orchestrator = ChatOrchestrator(llm_client, mcp_manager)
    logger.info("Chat backend started. MCP server URL: %s", settings.MCP_SERVER_URL)
    yield


app = FastAPI(title="Chat Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)


class MessageItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[MessageItem] = Field(..., min_length=1, max_length=50)


class ChatResponse(BaseModel):
    answer: str
    tool_calls: list[dict] = []


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    for msg in request.messages:
        if len(msg.content) > 5000:
            raise HTTPException(status_code=422, detail="Message content exceeds 5000 character limit.")

    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    try:
        result = await orchestrator.chat(messages)
        return ChatResponse(answer=result.answer, tool_calls=result.tool_calls)
    except ConnectionError as e:
        logger.warning("MCP connection error: %s", e)
        raise HTTPException(status_code=503, detail="Server busy. Please try again shortly.")
    except Exception as e:
        error_type = type(e).__name__
        logger.error("Chat error (%s): %s", error_type, e, exc_info=True)
        if "rate_limit" in str(e).lower() or "429" in str(e):
            raise HTTPException(status_code=429, detail="Rate limit reached. Please wait and try again.")
        raise HTTPException(status_code=500, detail="An internal error occurred.")
