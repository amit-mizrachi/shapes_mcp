from __future__ import annotations

import logging

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Ephemeral MCP client. One per request, disposed after use."""

    def __init__(self, url: str):
        self._url = url
        self._session: ClientSession | None = None
        self._streams = None

    async def __aenter__(self) -> MCPClient:
        self._streams = streamable_http_client(self._url)
        read, write, _ = await self._streams.__aenter__()
        try:
            self._session = ClientSession(read, write)
            await self._session.__aenter__()
            await self._session.initialize()
        except Exception:
            await self._streams.__aexit__(None, None, None)
            self._streams = None
            raise
        return self

    async def __aexit__(self, *exc_info) -> None:
        try:
            if self._session:
                await self._session.__aexit__(*exc_info)
        except Exception:
            logger.debug("Error closing MCP session", exc_info=True)
        finally:
            try:
                if self._streams:
                    await self._streams.__aexit__(*exc_info)
            except Exception:
                logger.debug("Error closing MCP streams", exc_info=True)

    async def list_tools(self) -> list[dict]:
        result = await self._session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._session.call_tool(name, arguments)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)
