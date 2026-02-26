from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FilterCondition:
    column: str
    op: str = "="
    value: str | int | float = ""
