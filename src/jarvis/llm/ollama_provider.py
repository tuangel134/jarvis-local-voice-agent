from __future__ import annotations

import logging
from typing import Any

import requests

from jarvis.llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    name = 'ollama'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.llm.ollama')
        self.base_url = config.get('ollama', {}).get('base_url', 'http://localhost:11434').rstrip('/')
        self.model = config.get('llm', {}).get('local_model', 'qwen2.5:3b')
        self.timeout = int(config.get('llm', {}).get('timeout_seconds', 60))

    def is_available(self) -> bool:
        try:
            res = requests.get(f'{self.base_url}/api/tags', timeout=3)
            return res.ok
        except Exception:
            return False

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        payload = {
            'model': kwargs.get('model', self.model),
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': kwargs.get('temperature', self.config.get('llm', {}).get('temperature', 0.4)),
                'num_predict': kwargs.get('max_tokens', self.config.get('llm', {}).get('max_tokens', 1024)),
            },
        }
        try:
            res = requests.post(f'{self.base_url}/api/chat', json=payload, timeout=self.timeout)
            if res.status_code >= 300:
                return LLMResponse('', self.name, payload['model'], False, res.text[:400])
            data = res.json()
            return LLMResponse(data.get('message', {}).get('content', '').strip(), self.name, payload['model'])
        except Exception as exc:
            return LLMResponse('', self.name, payload['model'], False, str(exc))
