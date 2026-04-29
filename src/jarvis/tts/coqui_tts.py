from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis.audio.speaker import Speaker
from jarvis.tts.base import TTSProvider
from jarvis.utils.paths import ensure_dir


class CoquiTTS(TTSProvider):
    name = 'coqui'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts.coqui')
        self.cfg = config.get('tts', {}).get('coqui', {})
        self.speaker = Speaker(config)
        self._tts = None

    def _load(self):
        if self._tts is not None:
            return self._tts
        try:
            from TTS.api import TTS
        except Exception as exc:
            raise RuntimeError('Coqui TTS no está instalado. Instala opcional: pip install TTS') from exc
        model = self.cfg.get('model', 'tts_models/multilingual/multi-dataset/xtts_v2')
        device = self.cfg.get('device', 'cpu')
        self._tts = TTS(model).to(device)
        return self._tts

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        tts = self._load()
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        kwargs = {'text': text, 'file_path': str(out)}
        if self.cfg.get('speaker_wav'):
            kwargs['speaker_wav'] = str(Path(self.cfg['speaker_wav']).expanduser())
        if self.cfg.get('language'):
            kwargs['language'] = self.cfg.get('language')
        tts.tts_to_file(**kwargs)
        return out

    def speak(self, text: str) -> None:
        temp = ensure_dir(self.config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))
        wav = self.synthesize(text, temp / 'jarvis_coqui.wav')
        self.speaker.play_wav(wav)
