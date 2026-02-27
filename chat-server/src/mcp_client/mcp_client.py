import logging
from contextlib import AsyncExitStack

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

logger = logging.getLogger(__name__)


class MCPClient:
    """Ephemeral MCP client. One per request, disposed after use."""

    def __init__(self, url: str):
        self._url = url
        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def __aenter__(self) -> "MCPClient":
        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(self._url)
            )
            self._session = await stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
        except Exception:
            await stack.aclose()
            raise
        self._exit_stack = stack
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._session = None
        if self._exit_stack:
            try:
                await self._exit_stack.__aexit__(*exc_info)
            except Exception:
                logger.debug("Error closing MCP resources", exc_info=True)
            finally:
                self._exit_stack = None

    async def list_tools(self) -> list[dict]:
        if self._session is None:
            raise RuntimeError("MCPClient must be used as an async context manager")
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
        if self._session is None:
            raise RuntimeError("MCPClient must be used as an async context manager")
        result = await self._session.call_tool(name, arguments)
        parts = []
        for content in result.content:
            if hasattr(content, "text"):
                parts.append(content.text)
            else:
                parts.append(str(content))
        return "\n".join(parts)
