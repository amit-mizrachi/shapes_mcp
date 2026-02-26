from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from .mcp_client import MCPClient

logger = logging.getLogger(__name__)


class MCPClientManager:
    """Creates ephemeral MCP clients with concurrency control and tool caching."""

    def __init__(self, url: str, max_concurrent: int, semaphore_timeout: float):
        self._url = url
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._semaphore_timeout = semaphore_timeout
        self._tools: list[dict] = []

    async def initialize(self) -> None:
        """Fetch and cache tool definitions once at startup."""
        async with MCPClient(self._url) as client:
            logger.info("Caching MCP tools")
            self._tools = await client.list_tools()

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
