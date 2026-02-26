class Config:
    _values = {
        # ── Shared ──
        "shared.default_query_limit": 20,

        # ── MCP Server ──
        "mcp_server.numeric_threshold": 0.8,

        # ── Chat Server ──
        "chat_server.llm_provider":      "gemini",
        "chat_server.anthropic_model":   "claude-sonnet-4-20250514",
        "chat_server.max_tokens":        4096,
        "chat_server.gemini_model":      "gemini-2.5-flash",
        "chat_server.gemini_max_tokens": 4096,
        "chat_server.max_iterations":    10,
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
