from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class STTProvider(ABC):
    name = 'base'

    @abstractmethod
    def transcribe(self, wav_path: str | Path) -> str:
        raise NotImplementedError
