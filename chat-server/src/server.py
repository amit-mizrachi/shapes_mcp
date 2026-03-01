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
    mcp_manager = MCPClientManager()
    await mcp_manager.initialize()

    llm_client = LLMClientFactory.create()

    app.state.orchestrator = ChatOrchestrator(llm_client=llm_client, mcp_manager=mcp_manager)

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
        logger.info("Received chat request: %s", request)
        response = await asyncio.wait_for(
            raw_request.app.state.orchestrator.execute(request),
            timeout=Config.get("chat_server.chat_request_timeout_seconds"),
        )
        return response
    except asyncio.TimeoutError:
        logger.error("Request timed out: %s", request)
        return JSONResponse(status_code=504, content={"detail": "Request timed out"})
    except Exception:
        logger.exception("Unhandled error in /chat")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
