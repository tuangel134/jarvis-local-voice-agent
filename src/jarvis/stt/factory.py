from __future__ import annotations

import logging
from typing import Any

from jarvis.stt.base import STTProvider
from jarvis.stt.faster_whisper_stt import FasterWhisperSTT
from jarvis.stt.whispercpp_stt import WhisperCppSTT


def create_stt(config: dict[str, Any], logger: logging.Logger | None = None) -> STTProvider:
    provider = config.get('stt', {}).get('provider', 'faster-whisper')
    if provider == 'whisper.cpp':
        return WhisperCppSTT(config, logger)
    return FasterWhisperSTT(config, logger)
