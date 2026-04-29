from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    name = 'base'

    @abstractmethod
    def synthesize(self, text: str, out_path: str | Path) -> Path:
        raise NotImplementedError

    def speak(self, text: str) -> None:
        raise NotImplementedError
