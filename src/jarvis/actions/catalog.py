from __future__ import annotations

from typing import Iterable

from jarvis.actions.specs import ActionSpec
from jarvis.brain.intent_model import Intent


class ActionCatalog:
    def __init__(self):
        self._by_id: dict[str, ActionSpec] = {}
        self._intent_to_action: dict[str, str] = {}

    def register(self, specs: Iterable[ActionSpec]) -> None:
        for spec in specs:
            self._by_id[spec.action_id] = spec
            for intent_name in spec.intents:
                self._intent_to_action[intent_name] = spec.action_id

    def register_skill(self, skill: object) -> None:
        describe = getattr(skill, "describe_actions", None)
        if callable(describe):
            self.register(describe())

    def resolve_intent(self, intent: Intent) -> ActionSpec | None:
        action_id = self._intent_to_action.get(intent.name)
        if not action_id:
            return None
        return self._by_id.get(action_id)

    def list_actions(self, namespace: str | None = None) -> list[dict[str, object]]:
        items = []
        for spec in sorted(self._by_id.values(), key=lambda item: (item.namespace, item.name)):
            if namespace and spec.namespace != namespace:
                continue
            items.append(spec.to_dict())
        return items

    def list_namespaces(self) -> list[str]:
        return sorted({spec.namespace for spec in self._by_id.values()})

    def search_actions(self, query: str, namespace: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        q = str(query or '').strip().lower()
        if not q:
            return self.list_actions(namespace=namespace)[:limit]

        terms = [term for term in q.split() if term]
        ranked: list[tuple[int, ActionSpec]] = []
        for spec in self._by_id.values():
            if namespace and spec.namespace != namespace:
                continue
            hay = ' '.join([
                spec.action_id,
                spec.name,
                spec.namespace,
                spec.description,
                ' '.join(spec.intents or ()),
                ' '.join(spec.examples or ()),
                spec.backend or '',
            ]).lower()
            score = 0
            if spec.action_id == q:
                score += 100
            if spec.action_id.startswith(q):
                score += 70
            if spec.namespace == q:
                score += 40
            if q in hay:
                score += 35
            for term in terms:
                if term in hay:
                    score += 8
            if score:
                ranked.append((score, spec))

        ranked.sort(key=lambda item: (-item[0], item[1].namespace, item[1].name))
        out: list[dict[str, object]] = []
        for score, spec in ranked[:limit]:
            item = spec.to_dict()
            item['match_score'] = score
            out.append(item)
        return out
