from __future__ import annotations

import logging
import os
from typing import Any

import requests

from jarvis.llm.base import LLMProvider, LLMResponse


class OpenAIProvider(LLMProvider):
    name = 'openai'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.llm.openai')
        self.model = config.get('openai', {}).get('model', 'gpt-4o-mini')
        self.base_url = config.get('openai', {}).get('base_url', 'https://api.openai.com/v1/chat/completions')
        self.timeout = int(config.get('llm', {}).get('timeout_seconds', 60))

    def _key(self) -> str:
        env = self.config.get('openai', {}).get('api_key_env', 'OPENAI_API_KEY')
        return os.getenv(env, '')

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        key = self._key()
        model = kwargs.get('model', self.model)
        if not key:
            return LLMResponse('', self.name, model, False, 'OPENAI_API_KEY no configurada.')
        payload = {
            'model': model,
            'messages': messages,
            'temperature': kwargs.get('temperature', self.config.get('llm', {}).get('temperature', 0.4)),
            'max_tokens': kwargs.get('max_tokens', self.config.get('llm', {}).get('max_tokens', 1024)),
        }
        try:
            res = requests.post(self.base_url, headers={'Authorization': f'Bearer {key}'}, json=payload, timeout=self.timeout)
            if res.status_code >= 300:
                return LLMResponse('', self.name, model, False, res.text[:500])
            data = res.json()
            return LLMResponse(data['choices'][0]['message']['content'].strip(), self.name, model)
        except Exception as exc:
            return LLMResponse('', self.name, model, False, str(exc))
