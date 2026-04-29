from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATE_PATH = Path(
    os.getenv(
        "JARVIS_POST_QUESTION_LISTEN_FILE",
        str(Path.home() / ".local" / "share" / "jarvis" / "state" / "post_question_listen.json"),
    )
)

def _load() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def mark_pending_from_assistant(text: str) -> None:
    text = (text or "").strip()
    data = _load()
    data["ts"] = time.time()
    data["assistant_text"] = text[:500]
    data["pending"] = bool(text.endswith("?"))
    _save(data)

def consume_direct_listen_if_pending() -> bool:
    data = _load()
    if not bool(data.get("pending", False)):
        return False

    data["pending"] = False
    _save(data)
    return True
