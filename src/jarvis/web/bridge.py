from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Awaitable, Callable, Optional

ChatHandler = Callable[[str], Awaitable[dict[str, Any]] | dict[str, Any]]


class JarvisWebBridge:
    """Bridge between the live Jarvis runtime and the reactive web UI."""

    def __init__(self) -> None:
        self._chat_handler: Optional[ChatHandler] = None
        self._latest_state: str = 'idle'
        self._latest_amp: float = 0.18
        self._latest_intent: str = ''
        self._latest_action: str = ''
        self._latest_subtitle: str = ''
        self._logs: deque[str] = deque(maxlen=220)
        self._last_event_ts: float = time.time()

    def set_chat_handler(self, handler: ChatHandler) -> None:
        self._chat_handler = handler

    def set_state(self, state: str) -> None:
        self._latest_state = state or 'idle'
        self._last_event_ts = time.time()

    def set_audio_level(self, level: float) -> None:
        self._latest_amp = max(0.0, min(1.0, float(level)))
        self._last_event_ts = time.time()

    def set_intent(self, intent: str) -> None:
        self._latest_intent = intent or ''
        self._last_event_ts = time.time()

    def set_action(self, action: str) -> None:
        self._latest_action = action or ''
        self._last_event_ts = time.time()

    def set_subtitle(self, subtitle: str) -> None:
        self._latest_subtitle = subtitle or ''
        self._last_event_ts = time.time()

    def add_log(self, line: str) -> None:
        line = (line or '').rstrip()
        if not line:
            return
        self._logs.append(line)
        self._last_event_ts = time.time()

    def seed_logs(self, lines: list[str]) -> None:
        for line in lines:
            self.add_log(line)

    def snapshot(self) -> dict[str, Any]:
        return {
            'state': self._latest_state,
            'amp': self._latest_amp,
            'intent': self._latest_intent,
            'action': self._latest_action,
            'subtitle': self._latest_subtitle,
            'last_event_ts': self._last_event_ts,
            'logs': list(self._logs),
        }

    async def handle_text(self, text: str) -> dict[str, Any]:
        text = (text or '').strip()
        if not text:
            return {
                'text': 'No recibí un comando válido.',
                'intent': 'empty',
                'action': '',
                'state': 'idle',
            }

        if self._chat_handler is not None:
            result = self._chat_handler(text)
            if asyncio.iscoroutine(result):
                result = await result
            if not isinstance(result, dict):
                result = {'text': str(result)}
            return {
                'text': result.get('text', ''),
                'intent': result.get('intent', ''),
                'action': result.get('action', ''),
                'state': result.get('state', 'speaking'),
            }

        low = text.lower()
        if 'estás ahí' in low or 'estas ahi' in low:
            response = 'Aquí estoy. La interfaz reactiva de Jarvis ya está enlazada y lista para recibir eventos reales.'
            intent = 'presence'
        elif 'abre' in low:
            response = 'Recibí la orden. En cuanto conectemos el ejecutor real, este panel mostrará la acción exacta y su resultado.'
            intent = 'action_request'
        else:
            response = 'Interfaz Jarvis lista. Falta conectar este chat al conductor vivo para ejecutar tareas reales.'
            intent = 'web_ui_stub'

        return {
            'text': response,
            'intent': intent,
            'action': '',
            'state': 'speaking',
        }


bridge = JarvisWebBridge()
