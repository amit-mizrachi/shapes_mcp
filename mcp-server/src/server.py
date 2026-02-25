import glob
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tools
from repository.sqlite import SqliteIngester, SqliteRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    db_path = os.environ.get("DB_PATH", "/app/db/data.db")
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    logger.info("Starting server (db_path=%s, data_dir=%s)", db_path, data_dir)
    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    repository = None
    if not csv_files:
        logger.warning("No CSV files found in %s", data_dir)
    else:
        csv_path = csv_files[0]
        logger.info("Ingesting %s", csv_path)
        ingester = SqliteIngester(db_path)
        ingest_result = ingester.ingest(csv_path)
        repository = SqliteRepository(ingest_result.db_path, ingest_result.table_name, ingest_result.columns)
        logger.info("Ingestion complete, repository ready")
    yield {"repository": repository}


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


@http_app.route("/health")
async def health(request):
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(http_app, host="0.0.0.0", port=3001)
