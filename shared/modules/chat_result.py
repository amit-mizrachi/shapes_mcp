from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatResult:
    answer: str
    tool_calls: list[dict] = field(default_factory=list)
