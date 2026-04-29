from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

STATE_PATH = Path(
    os.getenv(
        "JARVIS_FOLLOWUP_HINT_FILE",
        str(Path.home() / ".local" / "share" / "jarvis" / "state" / "followup_hint.json"),
    )
)

QUESTION_STARTERS = (
    "que ", "qué ", "como ", "cómo ", "cual ", "cuál ", "cuales ", "cuáles ",
    "donde ", "dónde ", "cuando ", "cuándo ", "quien ", "quién ", "quienes ", "quiénes ",
    "por que ", "por qué ", "cuanto ", "cuánto ", "cuanta ", "cuánta ",
    "puedes ", "podrias ", "podrías ", "me puedes ", "me podrias ", "me podrías ",
    "sabes ", "hay ", "tienes ", "es ", "son ", "esta ", "está ", "estan ", "están ",
    "debo ", "puedo ", "seria ", "sería ",
)

QUESTION_PATTERNS = (
    r"^(?:jarvis[, ]+)?(?:que|qué|como|cómo|cual|cuál|donde|dónde|cuando|cuándo|quien|quién|por que|por qué)\b",
    r"^(?:jarvis[, ]+)?(?:puedes|podrias|podrías|me puedes|me podrias|me podrías|sabes|hay|tienes|debo|puedo)\b",
)

def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text

def looks_like_question(text: str) -> bool:
    norm = _normalize(text)
    if not norm:
        return False
    if "?" in norm or "¿" in norm:
        return True
    if norm.startswith(QUESTION_STARTERS):
        return True
    for pattern in QUESTION_PATTERNS:
        if re.search(pattern, norm):
            return True
    return False

def _write_state(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def mark_last_user_text(text: str) -> None:
    _write_state(
        {
            "ts": time.time(),
            "question": looks_like_question(text),
            "text": (text or "")[:300],
        }
    )

def should_bypass_echo_guard() -> bool:
    try:
        window = float(os.getenv("JARVIS_FOLLOWUP_ECHO_BYPASS_WINDOW_SECONDS", "10"))
    except Exception:
        window = 10.0

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False

    try:
        age = time.time() - float(data.get("ts", 0.0))
    except Exception:
        return False

    if age < 0:
        return False
    if age > window:
        return False
    return bool(data.get("question", False))
