from __future__ import annotations

from typing import Any

from jarvis.actions.catalog import ActionCatalog
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.apps import AppsSkill
from jarvis.skills.base import Skill
from jarvis.skills.browser import BrowserSkill
from jarvis.skills.files import FilesSkill
from jarvis.skills.music import MusicSkill
from jarvis.skills.notes import NotesSkill
from jarvis.skills.reminders import RemindersSkill
from jarvis.skills.services import ServicesSkill
from jarvis.skills.network import NetworkSkill
from jarvis.skills.power import PowerSkill
from jarvis.skills.devices import DevicesSkill
from jarvis.skills.display import DisplaySkill
from jarvis.skills.shell_safe import ShellSafeSkill
from jarvis.skills.system import SystemSkill
from jarvis.skills.windows import WindowsSkill


class SkillRegistry:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.catalog = ActionCatalog()
        self.skills: list[Skill] = [
            BrowserSkill(config),
            MusicSkill(config),
            AppsSkill(config),
            FilesSkill(config),
            SystemSkill(config),
            ServicesSkill(config),
            WindowsSkill(config),
            NetworkSkill(config),
            PowerSkill(config),
            DevicesSkill(config),
            DisplaySkill(config),
            NotesSkill(config),
            RemindersSkill(config),
            ShellSafeSkill(config),
        ]
        for skill in self.skills:
            self.catalog.register_skill(skill)

    def find(self, intent: Intent) -> Skill | None:
        for skill in self.skills:
            if skill.can_handle(intent):
                return skill
        return None

    def resolve_action(self, intent: Intent):
        return self.catalog.resolve_intent(intent)

    def list(self) -> list[dict[str, str]]:
        return [{'name': skill.name, 'description': skill.description} for skill in self.skills]

    def list_actions(self, namespace: str | None = None) -> list[dict[str, object]]:
        return self.catalog.list_actions(namespace=namespace)

    def list_action_namespaces(self) -> list[str]:
        return self.catalog.list_namespaces()

    def search_actions(self, query: str, namespace: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        return self.catalog.search_actions(query, namespace=namespace, limit=limit)
