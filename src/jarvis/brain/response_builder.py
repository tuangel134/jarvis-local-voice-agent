from __future__ import annotations

from typing import Any


def short_action_response(intent: str, result: dict[str, Any]) -> str:
    if result.get('message'):
        return str(result['message'])
    if result.get('ok'):
        return 'Hecho.'
    return str(result.get('error') or 'No pude completar la acción.')
