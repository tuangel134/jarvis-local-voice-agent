from __future__ import annotations

from jarvis.brain.intent_classifier import Intent


class Planner:
    def plan(self, intent: Intent) -> list[dict[str, str]]:
        return [{'type': 'execute_intent', 'intent': intent.name}]
