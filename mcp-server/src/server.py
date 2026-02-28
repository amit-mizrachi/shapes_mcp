import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

import tool_handlers
from enrichment.column_enricher import ColumnEnricher
from enrichment.rules.nominal_date_rule import NominalDateRule
from enrichment.rules.month_extraction_rule import MonthExtractionRule
from enrichment.rules.year_extraction_rule import YearExtractionRule
from data_store.csv_parser import CSVParser
from data_store.sqlite_ingester import SqliteIngester
from data_store.sqlite_data_store import SqliteDataStore
from shared.config import Config

logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    logger.info("Starting MCP server")
    db_path = Path(Config.get("mcp_server.db_path"))
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data_store = build_data_store(Config.get("mcp_server.csv_file_path"))
        yield {"data_store": data_store}
    finally:
        if db_path.exists():
            db_path.unlink()
            logger.info("Cleaned up database file: %s", db_path)

def build_data_store(csv_path: str) -> SqliteDataStore:
    logger.info("Parsing CSV data")
    parsed_csv = CSVParser.parse(csv_path)

    logger.info("Enriching parsed data")
    enricher = ColumnEnricher(rules=[NominalDateRule(), MonthExtractionRule(), YearExtractionRule()])
    enriched_csv = enricher.enrich(parsed_csv)

    logger.info("Ingesting enriched data to database")
    ingester = SqliteIngester()
    table_schema = ingester.ingest(enriched_csv)

    logger.info("Initializing data store")
    return SqliteDataStore(table_schema=table_schema)


host = Config.get("mcp_server.host")
port = Config.get("mcp_server.port")
streamable_http_path = Config.get("mcp_server.streamable_http_path")
mcp_server = FastMCP("MCP Data Server", lifespan=server_lifespan, host=host, port=port, streamable_http_path=streamable_http_path)

mcp_server.tool()(tool_handlers.get_schema)
mcp_server.tool()(tool_handlers.select_rows)
mcp_server.tool()(tool_handlers.aggregate)

http_app = mcp_server.streamable_http_app()

async def health(request):
    return JSONResponse({"status": "ok"})

http_app.add_route("/health", health)

if __name__ == "__main__":
    uvicorn.run(http_app, host=host, port=port)
