from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class RiskLevel(IntEnum):
    SAFE = 0
    MODERATE = 1
    SENSITIVE = 2
    DANGEROUS = 3

    def label(self) -> str:
        return {
            RiskLevel.SAFE: "safe",
            RiskLevel.MODERATE: "moderate",
            RiskLevel.SENSITIVE: "sensitive",
            RiskLevel.DANGEROUS: "dangerous",
        }[self]


@dataclass(frozen=True)
class ActionSpec:
    name: str
    namespace: str
    description: str
    intents: tuple[str, ...] = field(default_factory=tuple)
    examples: tuple[str, ...] = field(default_factory=tuple)
    risk_level: RiskLevel = RiskLevel.SAFE
    backend: str = ""
    requires_confirmation: bool = False
    available: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def action_id(self) -> str:
        return f"{self.namespace}.{self.name}"

    def handles_intent(self, intent_name: str) -> bool:
        return intent_name in set(self.intents or ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "namespace": self.namespace,
            "description": self.description,
            "intents": list(self.intents),
            "examples": list(self.examples),
            "risk_level": int(self.risk_level),
            "risk_label": self.risk_level.label(),
            "backend": self.backend,
            "requires_confirmation": self.requires_confirmation,
            "available": self.available,
            "metadata": dict(self.metadata),
        }
