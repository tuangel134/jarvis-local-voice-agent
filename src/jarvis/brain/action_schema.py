from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


ALLOWED_ACTIONS = {
    "open_app",
    "open_url",
    "open_folder", "open_file",
    "play_music",
    "stop_music",
    "pause_music",
    "resume_music",
    "get_time",
    "get_date",
    "system_status",
    "service_status",
    "create_note",
    "read_note",
    "search_file",
    "create_reminder",
    "list_reminders",
    "safe_shell",
    "chat",
    "heavy_reasoning",
    "unknown",
}


@dataclass
class SemanticAction:
    action: str = "unknown"
    confidence: float = 0.0
    query: str = ""
    platform: str = ""
    app_name: str = ""
    url_name: str = ""
    url: str = ""
    folder: str = ""
    path: str = ""
    service: str = ""
    note: str = ""
    search_query: str = ""
    command: str = ""
    text: str = ""
    needs_confirmation: bool = False
    reason: str = ""
    source: str = "unknown"
    raw: dict[str, Any] = field(default_factory=dict)

    def normalized_action(self) -> str:
        action = (self.action or "unknown").strip().lower()
        return action if action in ALLOWED_ACTIONS else "unknown"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.normalized_action()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str = "semantic") -> "SemanticAction":
        if not isinstance(data, dict):
            return cls(action="unknown", confidence=0.0, source=source, raw={})

        allowed_fields = set(cls.__dataclass_fields__.keys())
        clean: dict[str, Any] = {}

        for key, value in data.items():
            if key in allowed_fields:
                clean[key] = value

        clean.setdefault("source", source)
        clean["raw"] = data

        action = str(clean.get("action", "unknown")).strip().lower()
        clean["action"] = action if action in ALLOWED_ACTIONS else "unknown"

        try:
            clean["confidence"] = float(clean.get("confidence", 0.0))
        except Exception:
            clean["confidence"] = 0.0

        clean["confidence"] = max(0.0, min(1.0, clean["confidence"]))

        for key in [
            "query",
            "platform",
            "app_name",
            "url_name",
            "url",
            "folder",
            "path",
            "service",
            "note",
            "search_query",
            "command",
            "text",
            "reason",
        ]:
            clean[key] = str(clean.get(key, "") or "").strip()

        clean["needs_confirmation"] = bool(clean.get("needs_confirmation", False))

        return cls(**clean)

    @classmethod
    def from_json(cls, text: str, source: str = "groq") -> "SemanticAction":
        text = (text or "").strip()

        try:
            data = json.loads(text)
            return cls.from_dict(data, source=source)
        except Exception:
            pass

        import re

        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return cls(action="unknown", confidence=0.0, text=text, source=source)

        try:
            data = json.loads(match.group(0))
            return cls.from_dict(data, source=source)
        except Exception:
            return cls(action="unknown", confidence=0.0, text=text, source=source)
