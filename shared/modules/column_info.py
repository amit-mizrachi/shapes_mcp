from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    detected_type: str
    samples: list[str] = field(default_factory=list)
