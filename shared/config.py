from datetime import date


class Config:
    _values = {
        # ── Shared ──
        "mcp_server.default_query_limit": 20,
        "mcp_server.max_query_limit":     100,

        # ── MCP Server ──
        "mcp_server.db_path":              "/app/db/shapes.db",
        "mcp_server.csv_file_path":        "/app/data/people-list-export.csv",
        "mcp_server.enrichment.detection_sample_size" : 20,
        "mcp_server.enrichment.max_samples": 3,
        "mcp_server.enrichment.nominal_date_epoch": "1970-01-01",
        "mcp_server.host":                 "0.0.0.0",
        "mcp_server.port":                 3001,
        "mcp_server.streamable_http_path": "/mcp",
        "mcp_server.numeric_threshold":    0.8,

        # ── Chat Server ──
        "chat_server.mcp_server_url":                "http://mcp-server:3001/mcp",
        "chat_server.mcp_max_concurrent":            10,
        "chat_server.semaphore_timeout":             30.0,
        "chat_server.mcp_connection.retry_attempts": 3,
        "chat_server.mcp_connection.retry_sleep":    3,
        "chat_server.timeout_seconds":               120,
        "chat_server.llm_provider":                  "gemini",
        "chat_server.anthropic_model":   "claude-sonnet-4-20250514",
        "chat_server.max_tokens":        10000,
        "chat_server.gemini_model":      "gemini-2.5-pro",
        "chat_server.gemini_max_tokens": 10000,
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
            "DATA QUALITY RULES:\n"
            "- Before aggregating numeric columns, check if related columns indicate different units or categories.\n"
            "  If you find mixed units, currencies, or types, you MUST normalize the data using the tool's\n"
            "  transform parameter (CASE WHEN logic) rather than asking the user to choose.\n"
            "  Read the tool description carefully — it documents the transform structure and gives examples.\n"
            "- A single value may need MULTIPLE normalizations (e.g., a distance column may vary by both unit (km/mi) AND measurement method).\n"
            "  Combine all dimensions into one transform — do not normalize only one and ignore the others.\n"
            "- NEVER ask the user to clarify or choose a subset when you can normalize or convert the data yourself.\n"
            "  Your job is to handle data complexity autonomously. Use the full capabilities of each tool.\n"
            "- When results are truncated (count < total_count), ALWAYS tell the user how many total results exist.\n"
            "\n"
            "DATE COLUMNS:\n"
            "- Date columns are enriched with three derived columns: {col}_days, {col}_month, {col}_year.\n"
            "- {col}_days is the number of days since the nominal epoch (1970-01-01). Use for age/duration math.\n"
            "- {col}_month is the month number (1-12). {col}_year is the four-digit year.\n"
            "- get_schema() returns a date_context object with nominal_date_epoch and today_as_nominal_days.\n"
            "- To compute age in years: (today_as_nominal_days - dob_days) / 365.25\n"
            "- To find youngest/most recent: sort by _days DESC (higher = more recent).\n"
            "- To find oldest/earliest: sort by _days ASC (lower = earlier).\n"
            "\n"
            "QUERY TIPS:\n"
            "- Use LIKE operator for partial text matching (e.g., job LIKE '%Manager%' finds all Manager roles).\n"
            "- When a question asks about 'all' records, set limit to 100 or be aware the default is 20.\n"
            "- Use aggregate() with group_by to discover what distinct values exist in a column before filtering.\n"
            f"- Today's date is {date.today().isoformat()}.\n"
            "\n"
            "Always base your answers on actual query results, not assumptions."
        ),
    }

    @classmethod
    def get(cls, key: str):
        return cls._values[key]
