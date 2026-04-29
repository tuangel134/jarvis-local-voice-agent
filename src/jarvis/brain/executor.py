from __future__ import annotations

import logging
from typing import Any

from jarvis.actions.risk import ActionRiskEngine
from jarvis.brain.intent_classifier import Intent
from jarvis.brain.response_builder import short_action_response
from jarvis.llm.router import LLMRouter
from jarvis.skills.registry import SkillRegistry


class Executor:
    def __init__(self, config: dict[str, Any], skills: SkillRegistry, llm: LLMRouter, logger: logging.Logger | None = None):
        self.config = config
        self.skills = skills
        self.llm = llm
        self.logger = logger or logging.getLogger('jarvis.executor')
        self.risk_engine = ActionRiskEngine(config)

    def execute(self, intent: Intent) -> str:
        skill = self.skills.find(intent)
        action_spec = self.skills.resolve_action(intent)
        risk_decision = self.risk_engine.evaluate(action_spec, intent.entities) if action_spec else None

        if skill:
            if action_spec and risk_decision:
                self.logger.info(
                    'Ejecutando skill=%s intent=%s action=%s risk=%s confirm=%s strict=%s',
                    skill.name,
                    intent.name,
                    action_spec.action_id,
                    risk_decision.risk_label,
                    risk_decision.requires_confirmation,
                    risk_decision.strict_mode,
                )
                if not risk_decision.allowed:
                    return (
                        f'La acción {action_spec.action_id} es {risk_decision.risk_label} y requiere confirmación explícita. '
                        f'{risk_decision.reason}'
                    )
            else:
                self.logger.info('Ejecutando skill=%s intent=%s', skill.name, intent.name)

            result = skill.run(intent, intent.entities, {'config': self.config, 'action_spec': action_spec, 'risk': risk_decision})
            if risk_decision and result.get('ok'):
                result.setdefault('action', action_spec.action_id if action_spec else '')
                result.setdefault('risk', risk_decision.to_dict())
            return short_action_response(intent.name, result)

        response = self.llm.answer(intent.raw_text, intent.name, {'entities': intent.entities})
        if response.ok and response.text:
            self.logger.info('LLM usado provider=%s model=%s', response.provider, response.model)
            return response.text
        return f'No pude responder con el modelo configurado. {response.error}'
