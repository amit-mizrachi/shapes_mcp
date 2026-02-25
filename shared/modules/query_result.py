from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict]
    count: int
