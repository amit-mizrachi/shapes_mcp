from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Per-request MCP client. Create a new instance for each /chat request."""

    def __init__(self):
        self._session: ClientSession | None = None
        self._streams = None
        self._tools_cache: list[dict] | None = None

    async def connect(self, url: str) -> None:
        self._streams = streamablehttp_client(url)
        read_stream, write_stream, _ = await self._streams.__aenter__()
        try:
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()
        except Exception:
            await self._streams.__aexit__(None, None, None)
            self._streams = None
            raise

    async def list_tools(self) -> list[dict]:
        if self._tools_cache is not None:
            return self._tools_cache

        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append({
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            })
        self._tools_cache = tools
        return tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._session.call_tool(name, arguments)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)

    async def close(self) -> None:
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error closing MCP session", exc_info=True)
        finally:
            try:
                if self._streams:
                    await self._streams.__aexit__(None, None, None)
            except Exception:
                logger.debug("Error closing MCP streams", exc_info=True)


class MCPSessionPool:
    """Pool of pre-warmed MCP sessions. Borrow one exclusively per request."""

    def __init__(self, url: str, size: int):
        self._url = url
        self._size = size
        self._pool: asyncio.Queue[MCPClient] = asyncio.Queue(maxsize=size)
        self._tools_cache: list[dict] | None = None

    async def initialize(self) -> None:
        """Create all sessions and cache tools. Called once at startup."""
        for i in range(self._size):
            client = MCPClient()
            await client.connect(self._url)
            if self._tools_cache is None:
                self._tools_cache = await client.list_tools()
            await self._pool.put(client)
            logger.info("MCP pool: session %d/%d ready", i + 1, self._size)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[MCPClient]:
        """Borrow a session. Returns it on success, replaces on failure."""
        try:
            client = await asyncio.wait_for(self._pool.get(), timeout=30.0)
        except asyncio.TimeoutError:
            raise ConnectionError("MCP session pool exhausted (all sessions busy)")

        try:
            yield client
            await self._pool.put(client)
        except Exception:
            await client.close()
            try:
                replacement = MCPClient()
                await replacement.connect(self._url)
                await self._pool.put(replacement)
                logger.info("MCP pool: replaced broken session")
            except Exception:
                logger.warning("MCP pool: failed to replace session, pool shrunk by 1")
            raise

    def get_tools(self) -> list[dict]:
        """Return cached tools (identical across all sessions)."""
        return self._tools_cache or []

    async def close(self) -> None:
        """Drain and close all sessions. Called at shutdown."""
        while not self._pool.empty():
            client = self._pool.get_nowait()
            await client.close()
