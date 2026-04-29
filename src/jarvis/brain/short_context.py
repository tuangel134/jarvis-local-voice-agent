from __future__ import annotations

import json
import os
import re
from pathlib import Path

STATE_PATH = Path(
    os.getenv(
        "JARVIS_SHORT_CONTEXT_FILE",
        str(Path.home() / ".local" / "share" / "jarvis" / "state" / "short_context.json"),
    )
)

POST_Q_PATH = Path(
    os.getenv(
        "JARVIS_POST_QUESTION_LISTEN_FILE",
        str(Path.home() / ".local" / "share" / "jarvis" / "state" / "post_question_listen.json"),
    )
)

AFFIRMATIVES = {
    "si", "sí", "claro", "ok", "okay", "vale", "dale", "va", "por favor",
    "si por favor", "sí por favor", "aja", "ajá",
}
NEGATIVES = {"no", "nop", "no gracias", "negativo"}

FRAGMENT_PREFIXES = (
    "y ",
    "mañana",
    "y mañana",
    "pasado mañana",
    "y pasado mañana",
    "hoy",
    "y hoy",
    "esta tarde",
    "y esta tarde",
    "en la tarde",
    "y en la tarde",
    "en la noche",
    "y en la noche",
    "luego",
    "y luego",
    "después",
    "despues",
    "y después",
    "y despues",
    "también",
    "tambien",
)

def _normalize(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"^[¡¿\s]+", "", text)
    text = re.sub(r"[\s\?\!\.,;:¡¿]+$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def remember_turn(user_text: str | None = None, assistant_text: str | None = None) -> None:
    data = _load_json(STATE_PATH)
    if user_text is not None:
        data["last_user_text"] = str(user_text)[:400]
    if assistant_text is not None:
        data["last_assistant_text"] = str(assistant_text)[:500]
    _save_json(STATE_PATH, data)

def _get_last_user_text() -> str:
    return str(_load_json(STATE_PATH).get("last_user_text", "") or "").strip()

def _get_last_assistant_text() -> str:
    data = _load_json(STATE_PATH)
    text = str(data.get("last_assistant_text", "") or "").strip()
    if text:
        return text
    pq = _load_json(POST_Q_PATH)
    return str(pq.get("assistant_text", "") or "").strip()

def _looks_like_fragment(text: str) -> bool:
    norm = _normalize(text)
    if not norm:
        return False
    max_words = int(os.getenv("JARVIS_SHORT_CONTEXT_MAX_WORDS", "5"))
    if len(norm.split()) > max_words:
        return False
    return norm.startswith(FRAGMENT_PREFIXES)

def _rewrite_yes_no(current_text: str, previous_assistant: str) -> str:
    norm = _normalize(current_text)
    q_norm = _normalize(previous_assistant)
    if norm in AFFIRMATIVES:
        if "pronóstico" in q_norm or "pronostico" in q_norm:
            return "Sí, quiero saber el pronóstico"
        if "temperatura" in q_norm and "clima" in q_norm:
            return "Sí, quiero saber la temperatura y el pronóstico"
        if "clima" in q_norm:
            return "Sí, quiero saber más sobre el clima"
        return current_text
    if norm in NEGATIVES:
        if "pronóstico" in q_norm or "pronostico" in q_norm or "clima" in q_norm:
            return "No, no quiero más detalles del clima"
        return current_text
    return current_text

def _rewrite_fragment(current_text: str, previous_user: str, previous_assistant: str) -> str:
    norm = _normalize(current_text)
    prev_user_norm = _normalize(previous_user)
    prev_assistant_norm = _normalize(previous_assistant)

    if norm.startswith("y "):
        norm_tail = norm[2:].strip()
    else:
        norm_tail = norm

    climate_hint = (
        "clima" in prev_user_norm
        or "pronóstico" in prev_user_norm
        or "pronostico" in prev_user_norm
        or "clima" in prev_assistant_norm
        or "pronóstico" in prev_assistant_norm
        or "pronostico" in prev_assistant_norm
        or "temperatura" in prev_assistant_norm
    )
    if climate_hint:
        if norm_tail in {"mañana", "pasado mañana", "hoy"}:
            return f"cómo está el clima {norm_tail}"
        if norm_tail in {"esta tarde", "en la tarde", "en la noche"}:
            return f"cómo está el clima {norm_tail}"
        if norm_tail:
            return f"cómo está el clima {norm_tail}"

    if prev_user_norm and norm_tail:
        return f"{prev_user_norm} {norm_tail}"

    return current_text

def expand_short_context(current_text: str) -> str:
    current = (current_text or "").strip()
    if not current:
        return current

    previous_user = _get_last_user_text()
    previous_assistant = _get_last_assistant_text()

    if previous_assistant.strip().endswith("?"):
        rewritten = _rewrite_yes_no(current, previous_assistant)
        if rewritten != current:
            return rewritten

    if _looks_like_fragment(current):
        rewritten = _rewrite_fragment(current, previous_user, previous_assistant)
        if rewritten != current:
            return rewritten

    return current
