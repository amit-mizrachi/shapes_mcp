import glob
import logging
import os
import sqlite3
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tools
from shared.config import Config
from repository.sqlite.sqlite_ingester import SqliteIngester
from repository.sqlite.sqlite_repository import SqliteRepository

logging.basicConfig(
    level=Config.get("shared.log_level"),
    format=Config.get("shared.log_format"),
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    logger.info("Starting MCP server")
    # Keeper connection: holds the shared in-memory DB alive for the server's lifetime.
    keeper_connection = sqlite3.connect(Config.get("mcp_server.shared_memory_uri"), uri=True)
    try:
        logger.info("Initializing database ingestor")
        ingester = SqliteIngester(Config.get("mcp_server.shared_memory_uri"))

        logger.info("Ingesting CSV data to database")
        ingest_result = ingester.ingest(Config.get("mcp_server.csv_file_path"))

        logger.info("Initializing SQL Repository")
        repository = SqliteRepository(Config.get("mcp_server.shared_memory_uri"), ingest_result.table_name, ingest_result.columns)

        yield {"repository": repository}
    finally:
        keeper_connection.close()


mcp_server = FastMCP(
    "MCP Data Server",
    lifespan=server_lifespan,
    host=Config.get("mcp_server.host"),
    port=Config.get("mcp_server.port"),
    streamable_http_path=Config.get("mcp_server.streamable_http_path"),
)

mcp_server.tool()(tools.get_schema)
mcp_server.tool()(tools.select_rows)
mcp_server.tool()(tools.aggregate)

http_app = mcp_server.streamable_http_app()

async def health(request):
    return JSONResponse({"status": "ok"})

http_app.add_route("/health", health)

if __name__ == "__main__":
    uvicorn.run(http_app, host=Config.get("mcp_server.host"), port=Config.get("mcp_server.port"))
