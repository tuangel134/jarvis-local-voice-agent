from __future__ import annotations

import logging
from typing import Any

from jarvis.llm.base import LLMResponse
from jarvis.llm.groq_provider import GroqProvider
from jarvis.llm.ollama_provider import OllamaProvider
from jarvis.llm.openai_provider import OpenAIProvider
from jarvis.llm.openrouter_provider import OpenRouterProvider
from jarvis.utils.text import normalize


GROQ_FAST_SYSTEM_PROMPT = """Eres Jarvis, un asistente de voz rápido en la computadora de Angel.

Reglas:
- Responde siempre en español.
- Responde breve, natural y útil.
- Eres un asistente de voz, no escribas respuestas enormes si no te lo piden.
- Si el usuario hace una pregunta normal, respóndela directamente.
- Si una acción local ya fue ejecutada por una skill, confirma brevemente.
- No digas que no puedes abrir apps si la skill local ya se encarga de eso.
- No ejecutes comandos peligrosos.
- No sugieras sudo, rm -rf, dd, mkfs, chmod -R 777 ni comandos destructivos.
- Si el usuario pide una tarea enorme, responde con un plan breve o sugiere usar el modelo potente.
"""

GROQ_HEAVY_SYSTEM_PROMPT = """Eres el modelo potente de Jarvis para tareas difíciles.

Responde en español claro, accionable y seguro.
No ejecutes comandos directamente.
Solo razona y devuelve respuesta o plan.
La ejecución local la controla Jarvis con reglas de seguridad.
"""

LOCAL_FALLBACK_SYSTEM_PROMPT = """Eres Jarvis local corriendo en Ollama en la PC de Angel.
Responde en español, breve y útil.
Groq no estuvo disponible o alcanzó límite, así que responde localmente.
"""


DIRECT_ACTION_INTENTS = {
    "open_url",
    "open_app",
    "open_folder",
    "get_time",
    "get_date",
    "system_status",
    "service_status",
    "create_note",
    "read_note",
    "search_file",
    "safe_shell",
    "create_reminder",
    "list_reminders",
    "stop_listening",
}


HEAVY_KEYWORDS = [
    "usa el modelo potente",
    "usa modelo potente",
    "usa la ia avanzada",
    "usa ia avanzada",
    "usa groq potente",
    "analiza este error completo",
    "analiza este log completo",
    "genera un proyecto completo",
    "crea una app completa",
    "programa esto completo",
    "haz un super prompt",
    "haz una super investigación",
    "haz una investigacion profunda",
    "revisa este log largo",
]


FAST_KEYWORDS = [
    "rapido",
    "rápido",
    "contesta rapido",
    "respuesta corta",
]


class LLMRouter:
    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger("jarvis.llm.router")
        self.local = OllamaProvider(config, self.logger)
        self.groq = GroqProvider(config, self.logger)
        self.remote_providers = {
            "groq": self.groq,
            "openai": OpenAIProvider(config, self.logger),
            "openrouter": OpenRouterProvider(config, self.logger),
        }

    def should_use_remote(self, user_text: str, intent: str | None = None) -> bool:
        if intent in DIRECT_ACTION_INTENTS:
            return False

        routing = self.config.get("routing", {})
        if routing.get("mode") == "groq_first_with_local_fallback":
            return True

        text = normalize(user_text)
        return any(k in text for k in HEAVY_KEYWORDS)

    def should_use_heavy_model(self, user_text: str, intent: str | None = None) -> bool:
        text = normalize(user_text)

        if any(k in text for k in HEAVY_KEYWORDS):
            return True

        if intent == "heavy_reasoning":
            return True

        if len(text.split()) > 160:
            return True

        return False

    def answer(self, user_text: str, intent: str = "chat", context: dict[str, Any] | None = None) -> LLMResponse:
        context = context or {}

        # Nunca usar LLM para acciones directas: eso debe resolverlo executor/skills.
        if intent in DIRECT_ACTION_INTENTS:
            return LLMResponse(
                text="Listo.",
                provider="none",
                model="direct_skill",
                ok=True,
            )

        use_groq = self.should_use_remote(user_text, intent)

        if use_groq:
            res = self._groq_answer(user_text, intent, context)

            if res.ok:
                self.logger.info("LLM route=groq provider=%s model=%s", res.provider, res.model)
                return res

            self.logger.warning("Groq falló o alcanzó límite: %s. Usando Ollama local.", res.error)

            local = self._local_answer(user_text, intent, context)
            if local.ok:
                local.text = "Groq no respondió; uso el modelo local. " + local.text
            return local

        local = self._local_answer(user_text, intent, context)
        if local.ok:
            self.logger.info("LLM route=local provider=%s model=%s", local.provider, local.model)
        return local

    def _groq_answer(self, user_text: str, intent: str, context: dict[str, Any]) -> LLMResponse:
        llm_cfg = self.config.get("llm", {})

        heavy = self.should_use_heavy_model(user_text, intent)

        if heavy:
            model = llm_cfg.get("heavy_model", "llama-3.3-70b-versatile")
            system = GROQ_HEAVY_SYSTEM_PROMPT
        else:
            model = llm_cfg.get("groq_fast_model", "llama-3.1-8b-instant")
            system = GROQ_FAST_SYSTEM_PROMPT

        # Forzar modelo Groq elegido sin romper provider existente.
        old_heavy = llm_cfg.get("heavy_model")
        llm_cfg["heavy_model"] = model

        messages = [
            {
                "role": "system",
                "content": system,
            },
            {
                "role": "user",
                "content": (
                    f"Intención detectada: {intent}\n"
                    f"Contexto local seguro: {context}\n"
                    f"Usuario: {user_text}\n\n"
                    "Responde como Jarvis por voz."
                ),
            },
        ]

        try:
            return self.groq.chat(messages)
        finally:
            if old_heavy is not None:
                llm_cfg["heavy_model"] = old_heavy

    def _local_answer(self, user_text: str, intent: str, context: dict[str, Any]) -> LLMResponse:
        messages = [
            {
                "role": "system",
                "content": LOCAL_FALLBACK_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    f"Intención detectada: {intent}\n"
                    f"Contexto local seguro: {context}\n"
                    f"Usuario: {user_text}\n\n"
                    "Responde breve y natural."
                ),
            },
        ]

        return self.local.chat(messages)

    def estimate_complexity(self, text: str) -> float:
        text = normalize(text)
        score = min(len(text.split()) / 220, 0.35)

        if any(k in text for k in HEAVY_KEYWORDS):
            score += 0.50

        return min(score, 1.0)
