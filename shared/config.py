class Config:
    _values = {
        # ── Shared ──
        "shared.log_level":           "INFO",
        "shared.log_format":          "%(asctime)s %(levelname)s %(name)s: %(message)s",
        "shared.default_query_limit": 20,

        # ── MCP Server ──
        "mcp_server.host":              "0.0.0.0",
        "mcp_server.port":              3001,
        "mcp_server.streamable_http_path": "/mcp",
        "mcp_server.db_path":           "/app/db/data.db",
        "mcp_server.csv_file_path":     "/app/data/people-list-export.csv",
        "mcp_server.shared_memory_uri": "file:data?mode=memory&cache=shared",
        "mcp_server.numeric_threshold": 0.8,

        # ── Chat Server ──
        "chat_server.mcp_server_url":     "http://mcp-server:3001/mcp",
        "chat_server.mcp_max_concurrent": 10,
        "chat_server.anthropic_model":    "claude-sonnet-4-20250514",
        "chat_server.max_tokens":         4096,
        "chat_server.timeout_seconds":    120,
        "chat_server.max_iterations":     10,
        "chat_server.semaphore_timeout":  30.0,
        "chat_server.retry_attempts":     10,
        "chat_server.retry_sleep":        3,
        "chat_server.cors_origins":       ["http://localhost:3000"],
        "chat_server.cors_methods":       ["POST", "GET"],
        "chat_server.cors_headers":       ["Content-Type"],
        "chat_server.message_max_length": 5000,
        "chat_server.system_prompt": (
            "You are a helpful data analyst assistant. You have access to a database loaded from a CSV file.\n"
            "\n"
            "IMPORTANT WORKFLOW:\n"
            "1. ALWAYS call get_schema() first to understand what table, columns, and data types are available.\n"
            "2. Use select_rows() to retrieve and inspect raw data rows.\n"
            "3. Use aggregate() for counts, sums, averages, and group-by analysis.\n"
            "4. Present results clearly and concisely. Use markdown tables when showing tabular data.\n"
            "\n"
            "Always base your answers on actual query results, not assumptions."
        ),
    }

    @classmethod
    def get(cls, key: str):
        return cls._values[key]
