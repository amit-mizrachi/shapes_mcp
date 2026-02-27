import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from shared.config import Config
from .mcp_client import MCPClient

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Creates ephemeral MCP clients with concurrency control and tool caching."""

    def __init__(self):
        self._url = Config.get("chat_server.mcp_server_url")
        self._semaphore = asyncio.Semaphore(Config.get("chat_server.mcp_max_concurrent"))
        self._semaphore_timeout = Config.get("chat_server.semaphore_timeout")
        self._tools: list[dict] = []

    async def initialize(self) -> None:
        """Fetch and cache tool definitions once at startup, with retries."""
        retry_attempts = Config.get("chat_server.mcp_connection.retry_attempts")
        retry_sleep = Config.get("chat_server.mcp_connection.retry_sleep")
        for attempt in range(1, retry_attempts + 1):
            try:
                async with MCPClient(self._url) as client:
                    logger.info("Caching MCP tools")
                    self._tools = await client.list_tools()
                logger.info("MCP connection established (attempt %d)", attempt)
                return
            except Exception:
                if attempt == retry_attempts:
                    logger.error("Failed to connect to MCP server after %d attempts", retry_attempts)
                    raise
                logger.warning("MCP connection attempt %d/%d failed, retrying in %ds...", attempt, retry_attempts, retry_sleep)
                await asyncio.sleep(retry_sleep)

    def get_tools(self) -> list[dict]:
        return self._tools

    @asynccontextmanager
    async def client(self) -> AsyncIterator[MCPClient]:
        """Create an ephemeral client, gated by semaphore."""
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._semaphore_timeout)
        except asyncio.TimeoutError:
            raise ConnectionError("MCP server busy (max concurrent requests reached)")
        try:
            async with MCPClient(self._url) as client:
                yield client
        finally:
            self._semaphore.release()
