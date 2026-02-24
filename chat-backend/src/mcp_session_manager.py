from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from mcp_client import MCPClient

logger = logging.getLogger(__name__)


class MCPSessionManager:
    """Creates ephemeral MCP sessions with concurrency control and tool caching."""

    def __init__(self, url: str, max_concurrent: int):
        self._url = url
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tools: list[dict] = []

    async def initialize(self) -> None:
        """Fetch and cache tool definitions once at startup."""
        async with MCPClient(self._url) as client:
            self._tools = await client.list_tools()
        logger.info("MCP tools cached: %s", [t["name"] for t in self._tools])

    def get_tools(self) -> list[dict]:
        return self._tools

    @asynccontextmanager
    async def session(self) -> AsyncIterator[MCPClient]:
        """Create an ephemeral session, gated by semaphore."""
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            raise ConnectionError("MCP server busy (max concurrent requests reached)")
        try:
            async with MCPClient(self._url) as client:
                yield client
        finally:
            self._semaphore.release()
