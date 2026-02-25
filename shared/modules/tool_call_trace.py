from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolCallTrace:
    name: str
    arguments: dict
    result: str
