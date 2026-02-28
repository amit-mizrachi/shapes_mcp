from __future__ import annotations

from datetime import datetime
from typing import Optional

from shared.modules.data.column_info import ColumnInfo

_DATE_FORMATS = [
    "%d/%m/%Y",  # 28/01/1977
    "%m/%d/%Y",  # 07/12/1989
    "%Y-%m-%d",  # 1989-07-12
    "%d-%m-%Y",  # 28-01-1977
    "%m-%d-%Y",  # 07-12-1989
    "%Y/%m/%d",  # 1989/07/12
]

_DETECTION_THRESHOLD = 0.8


def detect_date_columns(
    columns: list[ColumnInfo], sample_rows: list[dict],
) -> list[tuple[str, str]]:
    """Return (column_name, date_format) pairs for columns that look like dates."""
    result: list[tuple[str, str]] = []
    for column in columns:
        if column.detected_type == "numeric":
            continue
        date_format = _detect_date_format(column.name, sample_rows)
        if date_format is not None:
            result.append((column.name, date_format))
    return result


def _detect_date_format(column_name: str, sample_rows: list[dict]) -> Optional[str]:
    values = [
        str(row.get(column_name, "")).strip()
        for row in sample_rows
        if str(row.get(column_name, "")).strip()
    ]
    if not values:
        return None

    for date_format in _DATE_FORMATS:
        parsed_count = sum(1 for value in values if _try_parse(value, date_format))
        if parsed_count / len(values) >= _DETECTION_THRESHOLD:
            return date_format

    return None


def _try_parse(value: str, date_format: str) -> bool:
    try:
        datetime.strptime(value, date_format)
        return True
    except ValueError:
        return False
