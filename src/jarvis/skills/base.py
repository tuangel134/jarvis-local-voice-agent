from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from jarvis.actions.specs import ActionSpec
from jarvis.brain.intent_classifier import Intent


class Skill(ABC):
    name = 'base'
    description = ''
    ACTIONS: tuple[ActionSpec, ...] = ()

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def describe_actions(self) -> list[ActionSpec]:
        actions = getattr(self, 'ACTIONS', ()) or ()
        return list(actions)

    @abstractmethod
    def can_handle(self, intent: Intent) -> bool:
        raise NotImplementedError

    @abstractmethod
    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
