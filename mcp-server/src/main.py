import glob
import os
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

from db import DB_PATH, ingest_csv
from tools import get_schema, query_data


@asynccontextmanager
async def lifespan(server: FastMCP):
    data_dir = os.environ.get("DATA_DIR", "/app/data")
    csv_files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not csv_files:
        print(f"WARNING: No CSV files found in {data_dir}")
    else:
        csv_path = csv_files[0]
        print(f"Ingesting {csv_path} ...")
        ingest_csv(csv_path, DB_PATH)
        print("Ingestion complete.")
    yield


mcp = FastMCP(
    "MCP Data Server",
    lifespan=lifespan,
    host="0.0.0.0",
    port=3001,
    streamable_http_path="/mcp",
)

mcp.tool()(get_schema)
mcp.tool()(query_data)

app = mcp.streamable_http_app()


@app.route("/health")
async def health(request):
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3001)
