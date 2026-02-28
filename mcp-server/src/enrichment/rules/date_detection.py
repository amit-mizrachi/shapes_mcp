from __future__ import annotations

from datetime import datetime

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
    for col in columns:
        if col.detected_type == "numeric":
            continue
        fmt = _detect_date_format(col.name, sample_rows)
        if fmt is not None:
            result.append((col.name, fmt))
    return result


def _detect_date_format(col_name: str, sample_rows: list[dict]) -> str | None:
    values = [
        str(r.get(col_name, "")).strip()
        for r in sample_rows
        if str(r.get(col_name, "")).strip()
    ]
    if not values:
        return None

    for fmt in _DATE_FORMATS:
        parsed_count = sum(1 for v in values if _try_parse(v, fmt))
        if parsed_count / len(values) >= _DETECTION_THRESHOLD:
            return fmt

    return None


def _try_parse(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value, fmt)
        return True
    except ValueError:
        return False
