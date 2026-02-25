import glob
import logging
import os
import sqlite3
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tools
from config import config
from repository.sqlite.sqlite_ingester import SqliteIngester
from repository.sqlite.sqlite_repository import SqliteRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    logger.info("Starting MCP server")
    # Keeper connection: holds the shared in-memory DB alive for the server's lifetime.
    keeper_connection = sqlite3.connect(config.shared_memory_uri, uri=True)
    try:
        logger.info("Initializing database ingestor")
        ingester = SqliteIngester(config.shared_memory_uri)

        logger.info("Ingesting CSV data to database")
        ingest_result = ingester.ingest(config.csv_file_path)

        logger.info("Initializing SQL Repository")
        repository = SqliteRepository(config.shared_memory_uri, ingest_result.table_name, ingest_result.columns)

        yield {"repository": repository}
    finally:
        keeper_connection.close()


mcp_server = FastMCP(
    "MCP Data Server",
    lifespan=server_lifespan,
    host="0.0.0.0",
    port=3001,
    streamable_http_path="/mcp",
)

mcp_server.tool()(tools.get_schema)
mcp_server.tool()(tools.select_rows)
mcp_server.tool()(tools.aggregate)

http_app = mcp_server.streamable_http_app()

async def health(request):
    return JSONResponse({"status": "ok"})

http_app.add_route("/health", health)

if __name__ == "__main__":
    uvicorn.run(http_app, host="0.0.0.0", port=3001)
