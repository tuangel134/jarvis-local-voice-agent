from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.audio.microphone import Microphone
from jarvis.utils.paths import ensure_dir


class Recorder:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.microphone = Microphone(config)
        self.temp_dir = ensure_dir(config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))

    def temp_wav(self, prefix: str = 'audio') -> Path:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        return self.temp_dir / f'{prefix}_{stamp}.wav'

    def record_command(self) -> Path:
        return self.microphone.record_until_silence(self.temp_wav('command'))

    def record_wake_chunk(self) -> Path:
        seconds = float(self.config.get('audio', {}).get('wake_chunk_seconds', 2.5))
        return self.microphone.record_seconds(seconds, self.temp_wav('wake'))

    def record_test(self, seconds: int = 5) -> Path:
        return self.microphone.record_seconds(seconds, self.temp_wav('testmic'))
