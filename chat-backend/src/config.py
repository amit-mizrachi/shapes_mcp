from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MCP_SERVER_URL: str = "http://mcp-server:3001/mcp"
    MCP_MAX_CONCURRENT: int = 10
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    model_config = {"env_file": ".env"}
