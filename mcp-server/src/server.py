import logging
import os
import sqlite3
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tools
from repository.sqlite.sqlite_ingester import SqliteIngester
from repository.sqlite.sqlite_repository import SqliteRepository

_SHARED_MEMORY_URI = "file:data?mode=memory&cache=shared"
_CSV_FILE_PATH = os.environ.get("CSV_FILE_PATH", "/app/data/people-list-export.csv")
_HOST = "0.0.0.0"
_PORT = 3001
_STREAMABLE_HTTP_PATH = "/mcp"

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    logger.info("Starting MCP server")
    # Keeper connection: holds the shared in-memory DB alive for the server's lifetime.
    keeper_connection = sqlite3.connect(_SHARED_MEMORY_URI, uri=True)
    try:
        logger.info("Initializing database ingestor")
        ingester = SqliteIngester(_SHARED_MEMORY_URI)

        logger.info("Ingesting CSV data to database")
        ingest_result = ingester.ingest(_CSV_FILE_PATH)

        logger.info("Initializing SQL Repository")
        repository = SqliteRepository(_SHARED_MEMORY_URI, ingest_result.table_name, ingest_result.columns)

        yield {"repository": repository}
    finally:
        keeper_connection.close()


mcp_server = FastMCP(
    "MCP Data Server",
    lifespan=server_lifespan,
    host=_HOST,
    port=_PORT,
    streamable_http_path=_STREAMABLE_HTTP_PATH,
)

mcp_server.tool()(tools.get_schema)
mcp_server.tool()(tools.select_rows)
mcp_server.tool()(tools.aggregate)

http_app = mcp_server.streamable_http_app()

async def health(request):
    return JSONResponse({"status": "ok"})

http_app.add_route("/health", health)

if __name__ == "__main__":
    uvicorn.run(http_app, host=_HOST, port=_PORT)
