from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

from jarvis.audio.speaker import Speaker
from jarvis.tts.base import TTSProvider
from jarvis.utils.paths import ensure_dir


class ElevenLabsTTS(TTSProvider):
    name = 'elevenlabs'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts.elevenlabs')
        self.cfg = config.get('tts', {}).get('elevenlabs', {})
        self.speaker = Speaker(config)

    def _key(self) -> str:
        env = self.cfg.get('api_key_env', 'ELEVENLABS_API_KEY')
        return os.getenv(env, '')

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        api_key = self._key()
        voice_id = self.cfg.get('voice_id')
        if not api_key:
            raise RuntimeError('ELEVENLABS_API_KEY no está configurada.')
        if not voice_id:
            raise RuntimeError('voice_id de ElevenLabs vacío en config.yaml.')
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        url = f'https://api.elevenlabs.io/v1/text-to-speech/{voice_id}'
        payload = {
            'text': text,
            'model_id': self.cfg.get('model', 'eleven_multilingual_v2'),
            'voice_settings': {'stability': 0.45, 'similarity_boost': 0.75},
        }
        res = requests.post(url, headers={'xi-api-key': api_key, 'Accept': 'audio/mpeg'}, json=payload, timeout=90)
        if res.status_code >= 300:
            raise RuntimeError(f'ElevenLabs falló: {res.status_code} {res.text[:300]}')
        out.write_bytes(res.content)
        return out

    def speak(self, text: str) -> None:
        temp = ensure_dir(self.config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))
        mp3 = self.synthesize(text, temp / 'jarvis_elevenlabs.mp3')
        import subprocess, shutil
        if shutil.which('ffplay'):
            subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', str(mp3)], check=False)
        else:
            raise RuntimeError('Para reproducir MP3 de ElevenLabs instala ffmpeg.')
