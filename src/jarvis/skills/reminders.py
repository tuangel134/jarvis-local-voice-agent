from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.paths import ensure_dir


class RemindersSkill(Skill):
    name = 'reminders'
    description = 'Guarda y lista recordatorios locales básicos en JSON.'
    ACTIONS = (
        ActionSpec(
            name="create",
            namespace="reminders",
            description="Guarda un recordatorio local en JSON.",
            intents=("create_reminder",),
            examples=("recuérdame llamar mañana",),
            risk_level=RiskLevel.SAFE,
            backend="json filesystem",
        ),
        ActionSpec(
            name="list",
            namespace="reminders",
            description="Lista recordatorios pendientes guardados localmente.",
            intents=("list_reminders",),
            examples=("qué recordatorios tengo",),
            risk_level=RiskLevel.SAFE,
            backend="json filesystem",
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {'create_reminder', 'list_reminders'}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        path = Path(self.config.get('paths', {}).get('reminders_file', '~/.local/share/jarvis/reminders.json')).expanduser()
        ensure_dir(path.parent)
        data = self._read(path)
        if intent.name == 'create_reminder':
            item = {
                'texto': entities.get('text') or intent.raw_text,
                'fecha_hora': self._extract_datetime(intent.raw_text),
                'creado_en': datetime.now().isoformat(timespec='seconds'),
                'estado': 'pendiente',
            }
            data.append(item)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            return {'ok': True, 'message': 'Recordatorio guardado.'}
        pending = [x for x in data if x.get('estado') == 'pendiente']
        if not pending:
            return {'ok': True, 'message': 'No tienes recordatorios pendientes.'}
        msg = '; '.join(x.get('texto', '') for x in pending[:5])
        return {'ok': True, 'message': f'Tus recordatorios pendientes son: {msg}.'}

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _extract_datetime(self, text: str) -> str | None:
        lower = text.lower()
        for marker in ['mañana', 'hoy', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']:
            if marker in lower:
                return marker
        return None
