from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jarvis.tts.base import TTSProvider


class SystemTTS(TTSProvider):
    name = 'system'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts.system')
        sys_cfg = config.get('tts', {}).get('system', {})
        self.provider = sys_cfg.get('provider', 'espeak-ng')
        self.voice = sys_cfg.get('voice', 'es')
        self.speed = str(sys_cfg.get('speed', 150))

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        binary = shutil.which(self.provider) or shutil.which('espeak-ng') or shutil.which('espeak')
        if not binary:
            raise RuntimeError('No está instalado espeak-ng/espeak.')
        out = Path(out_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [binary, '-v', self.voice, '-s', self.speed, '-w', str(out), text]
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'espeak falló')
        return out

    def speak(self, text: str) -> None:
        if shutil.which('spd-say'):
            subprocess.run(['spd-say', '-l', 'es', text], check=False)
            return
        binary = shutil.which(self.provider) or shutil.which('espeak-ng') or shutil.which('espeak')
        if not binary:
            raise RuntimeError('No hay fallback TTS del sistema. Instala espeak-ng.')
        subprocess.run([binary, '-v', self.voice, '-s', self.speed, text], check=False)
