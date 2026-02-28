import sqlite3

from shared.config import Config
from shared.modules.data.parsed_csv import ParsedCSV
from shared.modules.data.table_schema import TableSchema


class SqliteIngester:
    def __init__(self, database_path: str | None = None) -> None:
        self._db_uri = database_path or Config.get("mcp_server.db_path")

    def ingest(self, parsed_csv: ParsedCSV) -> TableSchema:
        connection = sqlite3.connect(self._db_uri)
        try:
            self._create_table(connection, parsed_csv)
            self._insert_rows(connection, parsed_csv)
            connection.commit()
        finally:
            connection.close()

        return TableSchema(table_name=parsed_csv.table_name, columns=parsed_csv.columns)

    def _create_table(self, connection: sqlite3.Connection, parsed: ParsedCSV) -> None:
        column_defs = ", ".join(
            f'"{column.name}" {"REAL" if column.detected_type == "numeric" else "TEXT"}'
            for column in parsed.columns
        )
        cursor = connection.cursor()
        cursor.execute(f'DROP TABLE IF EXISTS "{parsed.table_name}"')
        cursor.execute(f'CREATE TABLE "{parsed.table_name}" ({column_defs})')

    def _insert_rows(self, connection: sqlite3.Connection, parsed_csv: ParsedCSV) -> None:
        column_types = {column.name: column.detected_type for column in parsed_csv.columns}
        placeholders = ", ".join("?" for _ in parsed_csv.headers)
        all_values = [
            [self._to_sql_value(row[header], column_types[header]) for header in parsed_csv.headers]
            for row in parsed_csv.rows
        ]
        connection.cursor().executemany(
            f'INSERT INTO "{parsed_csv.table_name}" VALUES ({placeholders})',
            all_values,
        )

    @staticmethod
    def _to_sql_value(raw_value, detected_type: str) -> float | None | str:
        if raw_value is None:
            return None
        if detected_type != "numeric":
            return str(raw_value)
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        stripped = str(raw_value).strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
