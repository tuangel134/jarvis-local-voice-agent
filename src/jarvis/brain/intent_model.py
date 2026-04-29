from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Intent:
    name: str
    confidence: float = 1.0
    entities: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
