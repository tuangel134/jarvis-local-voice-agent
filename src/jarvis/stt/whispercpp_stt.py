from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jarvis.stt.base import STTProvider


class WhisperCppSTT(STTProvider):
    name = 'whisper.cpp'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.stt.whispercpp')
        stt = config.get('stt', {})
        self.binary = stt.get('whispercpp_binary', 'whisper-cli')
        self.model = Path(stt.get('whispercpp_model', '~/.local/share/jarvis/models/ggml-base.bin')).expanduser()
        self.language = stt.get('language', 'es')

    def transcribe(self, wav_path: str | Path) -> str:
        binary = shutil.which(self.binary)
        if not binary:
            raise RuntimeError(f'No existe binario whisper.cpp: {self.binary}')
        if not self.model.exists():
            raise RuntimeError(f'No existe modelo whisper.cpp: {self.model}')
        cmd = [binary, '-m', str(self.model), '-f', str(wav_path), '-l', self.language, '-nt']
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'whisper.cpp falló')
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        return ' '.join(line for line in lines if not line.startswith('[')).strip()
