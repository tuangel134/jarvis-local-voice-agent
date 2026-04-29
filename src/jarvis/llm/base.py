from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    ok: bool = True
    error: str = ''


class LLMProvider(ABC):
    name = 'base'

    @abstractmethod
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        raise NotImplementedError
