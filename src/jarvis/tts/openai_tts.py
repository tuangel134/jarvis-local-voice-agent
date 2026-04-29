from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from jarvis.audio.speaker import Speaker
from jarvis.tts.base import TTSProvider
from jarvis.utils.paths import ensure_dir


class OpenAITTS(TTSProvider):
    name = 'openai'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts.openai')
        self.cfg = config.get('tts', {}).get('openai_tts', {})
        self.speaker = Speaker(config)

    def _key(self) -> str:
        env = self.cfg.get('api_key_env', 'OPENAI_API_KEY')
        return os.getenv(env, '')

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        api_key = self._key()
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY no está configurada.')
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        payload = {
            'model': self.cfg.get('model', 'gpt-4o-mini-tts'),
            'voice': self.cfg.get('voice', 'alloy'),
            'input': text,
            'response_format': 'wav',
        }
        res = requests.post(
            'https://api.openai.com/v1/audio/speech',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=90,
        )
        if res.status_code >= 300:
            raise RuntimeError(f'OpenAI TTS falló: {res.status_code} {res.text[:300]}')
        out.write_bytes(res.content)
        return out

    def speak(self, text: str) -> None:
        temp = ensure_dir(self.config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))
        wav = self.synthesize(text, temp / 'jarvis_openai.wav')
        self.speaker.play_wav(wav)
