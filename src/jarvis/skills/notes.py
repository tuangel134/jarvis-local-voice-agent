from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.paths import ensure_dir


class NotesSkill(Skill):
    name = 'notes'
    description = 'Crea y lee notas markdown locales.'
    ACTIONS = (
        ActionSpec(
            name="create",
            namespace="notes",
            description="Crea una nota markdown local.",
            intents=("create_note",),
            examples=("crea una nota",),
            risk_level=RiskLevel.SAFE,
            backend="filesystem",
        ),
        ActionSpec(
            name="read_latest",
            namespace="notes",
            description="Lee la nota markdown más reciente.",
            intents=("read_note",),
            examples=("lee mi última nota",),
            risk_level=RiskLevel.SAFE,
            backend="filesystem",
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {'create_note', 'read_note'}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        notes_dir = ensure_dir(self.config.get('paths', {}).get('notes_dir', '~/NotasJarvis'))
        if intent.name == 'create_note':
            content = str(entities.get('content') or intent.raw_text).strip()
            stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            path = Path(notes_dir) / f'nota_{stamp}.md'
            path.write_text(f'# Nota Jarvis {stamp}\n\n{content}\n', encoding='utf-8')
            return {'ok': True, 'message': f'Nota creada en {path}.'}
        notes = sorted(Path(notes_dir).glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not notes:
            return {'ok': True, 'message': 'No hay notas guardadas todavía.'}
        latest = notes[0]
        text = latest.read_text(encoding='utf-8', errors='ignore').strip()
        preview = ' '.join(text.split())[:250]
        return {'ok': True, 'message': f'Última nota: {preview}.'}
