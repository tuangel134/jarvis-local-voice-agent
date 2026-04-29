
from __future__ import annotations

import logging
import subprocess
from typing import Any

from jarvis.brain.context_store import ContextStore
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.security import is_url_allowed


class BrowserSkill(Skill):
    name = "browser"
    description = "Abre URLs permitidas en el navegador por defecto."

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.logger = logging.getLogger("jarvis.browser")

    def can_handle(self, intent: Intent) -> bool:
        return intent.name == "open_url"

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        url = str(entities.get("url", "") or "")
        target = str(entities.get("target", "") or "").lower()
        if not url:
            return {"ok": False, "error": "No detecté la URL."}
        if not is_url_allowed(url, self.config):
            return {"ok": False, "error": "Esa URL no está permitida por seguridad."}
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ContextStore(self.config).set_last_url(url, target)
        return {"ok": True, "message": self._open_message(url, target)}

    def _open_message(self, url: str, target: str) -> str:
        if "youtube" in target or "youtube" in url:
            return "Abriendo YouTube."
        if "tidal" in target or "tidal" in url:
            return "Abriendo TIDAL."
        if "spotify" in target or "spotify" in url:
            return "Abriendo Spotify."
        if "google" in target or "google" in url:
            return "Abriendo Google."
        if "chatgpt" in target or "chatgpt" in url:
            return "Abriendo ChatGPT."
        if "github" in target or "github" in url:
            return "Abriendo GitHub."
        return "Abriendo la URL."
