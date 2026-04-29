from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel


@dataclass(frozen=True)
class ActionRiskDecision:
    action_id: str
    risk_level: RiskLevel
    risk_label: str
    allowed: bool
    requires_confirmation: bool
    strict_mode: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "risk_level": int(self.risk_level),
            "risk_label": self.risk_label,
            "allowed": self.allowed,
            "requires_confirmation": self.requires_confirmation,
            "strict_mode": self.strict_mode,
            "reason": self.reason,
        }


class ActionRiskEngine:
    """Evaluación ligera de riesgo para la fase 1A.

    No cambia el comportamiento actual por defecto. Solo bloquea acciones
    marcadas para confirmación cuando `actions.enforce_confirmations=true`.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        actions_cfg = self.config.get("actions", {}) if isinstance(self.config, dict) else {}
        self.enforce_confirmations = bool(actions_cfg.get("enforce_confirmations", False))
        self.auto_confirm_safe = bool(actions_cfg.get("auto_confirm_safe", True))
        self.confirm_from_level = self._coerce_level(actions_cfg.get("confirm_from_level", RiskLevel.MODERATE))
        self.level_overrides = {
            str(key): self._coerce_level(value)
            for key, value in (actions_cfg.get("risk_overrides", {}) or {}).items()
        }

    def evaluate(self, spec: ActionSpec, entities: dict[str, Any] | None = None) -> ActionRiskDecision:
        entities = entities or {}
        level = self.level_overrides.get(spec.action_id, spec.risk_level)
        requires = bool(spec.requires_confirmation or level >= self.confirm_from_level)
        strict_mode = self.enforce_confirmations
        allowed = not (strict_mode and requires)

        if allowed and not requires:
            reason = "Acción segura o autoautorizada para esta fase."
        elif allowed and requires:
            reason = "Acción marcada para confirmación en modo estricto, pero la fase 1A no la bloquea."
        else:
            reason = "Acción bloqueada hasta que exista confirmación explícita."

        if spec.action_id == "shell.run_safe" and entities.get("command"):
            reason += " Comando shell detectado: se recomienda confirmación manual."

        return ActionRiskDecision(
            action_id=spec.action_id,
            risk_level=level,
            risk_label=level.label(),
            allowed=allowed,
            requires_confirmation=requires,
            strict_mode=strict_mode,
            reason=reason,
        )

    def _coerce_level(self, value: Any) -> RiskLevel:
        if isinstance(value, RiskLevel):
            return value
        if isinstance(value, str):
            value = value.strip().lower()
            mapping = {
                "safe": RiskLevel.SAFE,
                "moderate": RiskLevel.MODERATE,
                "sensitive": RiskLevel.SENSITIVE,
                "dangerous": RiskLevel.DANGEROUS,
            }
            if value in mapping:
                return mapping[value]
        try:
            return RiskLevel(int(value))
        except Exception:
            return RiskLevel.MODERATE
