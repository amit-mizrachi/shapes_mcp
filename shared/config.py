from pydantic import BaseModel


class Config(BaseModel):
    model_config = {"frozen": True}

    # MCP Server
    db_path: str = "/app/db/data.db"
    csv_file_path: str = "/app/data/people-list-export.csv"
    shared_memory_uri: str = "file:data?mode=memory&cache=shared"

    # Chat Backend
    mcp_server_url: str = "http://mcp-server:3001/mcp"
    mcp_max_concurrent: int = 10
    anthropic_model: str = "claude-sonnet-4-20250514"


config = Config()
