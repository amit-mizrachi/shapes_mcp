import glob
import os
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tools
from repository.sqlite import SqliteIngester, SqliteRepository


@asynccontextmanager
async def lifespan(server: FastMCP):
    db_path = os.environ.get("DB_PATH", "/app/db/data.db")
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    repo = None
    if not csv_files:
        print(f"WARNING: No CSV files found in {data_dir}")
    else:
        csv_path = csv_files[0]
        print(f"Ingesting {csv_path} ...")
        ingester = SqliteIngester(db_path)
        result = ingester.ingest(csv_path)
        repo = SqliteRepository(result.db_path, result.table_name, result.columns)
        print("Ingestion complete.")
    yield {"repo": repo}


mcp = FastMCP(
    "MCP Data Server",
    lifespan=lifespan,
    host="0.0.0.0",
    port=3001,
    streamable_http_path="/mcp",
)

mcp.tool()(tools.get_schema)
mcp.tool()(tools.select_rows)
mcp.tool()(tools.aggregate)

app = mcp.streamable_http_app()


@app.route("/health")
async def health(request):
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3001)
