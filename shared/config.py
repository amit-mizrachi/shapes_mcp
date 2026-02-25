from pydantic import BaseModel


class Config(BaseModel):
    model_config = {"frozen": True}

    # MCP Server
    db_path: str = "/app/db/data.db"
    data_dir: str = "/app/data"

    # Chat Backend
    mcp_server_url: str = "http://mcp-server:3001/mcp"
    mcp_max_concurrent: int = 10
    anthropic_model: str = "claude-sonnet-4-20250514"


config = Config()
