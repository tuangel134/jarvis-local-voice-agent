from __future__ import annotations

import shlex
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.security import validate_shell_command
from jarvis.utils.shell import run_command


class ShellSafeSkill(Skill):
    name = 'shell_safe'
    description = 'Ejecuta comandos permitidos y bloquea comandos peligrosos.'
    ACTIONS = (
        ActionSpec(
            name="run_safe",
            namespace="shell",
            description="Ejecuta un comando shell previamente permitido por las reglas de seguridad.",
            intents=("safe_shell",),
            examples=("ejecuta ls",),
            risk_level=RiskLevel.SENSITIVE,
            backend="validate_shell_command + run_command",
            requires_confirmation=True,
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name == 'safe_shell'

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        command = str(entities.get('command', '')).strip()
        decision = validate_shell_command(command, self.config)
        if not decision.allowed:
            return {'ok': False, 'error': 'Eso puede ser peligroso. No lo voy a ejecutar sin confirmación manual. ' + decision.reason}
        args = decision.sanitized or shlex.split(command)
        result = run_command(args, timeout=20)
        if not result.ok:
            return {'ok': False, 'error': f'El comando falló: {result.stderr or result.stdout}'}
        out = result.stdout.strip()
        if not out:
            return {'ok': True, 'message': 'Comando ejecutado sin salida.'}
        return {'ok': True, 'message': 'Resultado: ' + out[:450]}
