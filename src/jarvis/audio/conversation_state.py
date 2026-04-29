from __future__ import annotations

import json
import os
import time
from pathlib import Path

STATE_PATH = Path(
    os.getenv(
        "JARVIS_CONVERSATION_STATE_FILE",
        str(Path.home() / ".local" / "share" / "jarvis" / "state" / "conversation_state.json"),
    )
)

_RUNTIME_STATE: dict = {}


def _load() -> dict:
    data: dict = {}
    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            data.update(parsed)
    except Exception:
        pass

    if _RUNTIME_STATE:
        data.update(_RUNTIME_STATE)
    return data


def _save(data: dict) -> None:
    global _RUNTIME_STATE
    snapshot = dict(data)
    _RUNTIME_STATE = snapshot
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception:
        # No rompemos el runtime si el archivo falla; la copia en memoria sigue viva.
        pass


def _reset_false_wake_state(data: dict) -> None:
    data["false_wake_count"] = 0
    data.pop("false_wake_at", None)
    data.pop("hard_cooldown_until", None)


def note_assistant_response(text: str) -> None:
    text = (text or "").strip()
    data = _load()
    data["assistant_text"] = text[:500]
    data["followup_expected"] = bool(text.endswith("?"))
    data["followup_used"] = False
    _reset_false_wake_state(data)
    _save(data)


def note_tts_done() -> None:
    data = _load()
    now = time.time()
    data["tts_done_at"] = now

    media_active = bool(data.get("media_active", False))
    media_requested = bool(data.get("media_guard_requested", False))
    if media_requested or media_active:
        try:
            media_guard_seconds = float(os.getenv("JARVIS_MEDIA_GUARD_SECONDS", "12.0"))
        except Exception:
            media_guard_seconds = 12.0
        data["media_guard_until"] = now + media_guard_seconds
        data["media_active"] = True
        data["media_guard_requested"] = False

    _save(data)


def note_false_wake() -> None:
    data = _load()
    now = time.time()
    data["false_wake_at"] = now
    count = int(data.get("false_wake_count", 0) or 0) + 1
    data["false_wake_count"] = count

    if bool(data.get("media_active", False)):
        try:
            threshold = int(os.getenv("JARVIS_MEDIA_FALSE_WAKE_COUNT_THRESHOLD", "1"))
        except Exception:
            threshold = 1
        try:
            cooldown_seconds = float(os.getenv("JARVIS_MEDIA_HARD_COOLDOWN_SECONDS", "12.0"))
        except Exception:
            cooldown_seconds = 12.0

        if count >= threshold:
            current_until = float(data.get("hard_cooldown_until", 0.0) or 0.0)
            data["hard_cooldown_until"] = max(current_until, now + cooldown_seconds)
            current_media_until = float(data.get("media_guard_until", 0.0) or 0.0)
            data["media_guard_until"] = max(current_media_until, now + cooldown_seconds)

    _save(data)


def note_classified_intent(intent_name: str, entities: dict | None = None) -> None:
    name = str(intent_name or "").strip()
    entities = dict(entities or {})
    data = _load()

    if name in {"stop_music", "pause_music"}:
        data["media_active"] = False
        data["media_guard_requested"] = False
        data.pop("media_guard_until", None)
        _reset_false_wake_state(data)
        _save(data)
        return

    media_intents = {"open_url", "play_music", "play_media"}
    autoplay = bool(entities.get("autoplay", False))
    platform = str(entities.get("platform", "") or "").strip().lower()
    target = str(entities.get("target", "") or "").strip().lower()

    if name in media_intents and (autoplay or platform == "youtube" or target == "youtube"):
        data["media_guard_requested"] = True
        _reset_false_wake_state(data)
        _save(data)
        return

    _reset_false_wake_state(data)
    _save(data)


def should_bypass_to_followup() -> bool:
    data = _load()

    if bool(data.get("media_active", False)):
        return False

    if not bool(data.get("followup_expected", False)):
        return False

    try:
        window = float(os.getenv("JARVIS_FOLLOWUP_LISTEN_WINDOW_SECONDS", "6.0"))
    except Exception:
        window = 6.0

    try:
        age = time.time() - float(data.get("tts_done_at", 0.0))
    except Exception:
        return False

    if age < 0 or age > window:
        return False
    if bool(data.get("followup_used", False)):
        return False

    data["followup_used"] = True
    _save(data)
    return True


def should_accept_wake_score(score) -> bool:
    try:
        score = float(score)
    except Exception:
        return True

    data = _load()
    now = time.time()

    try:
        tts_age = now - float(data.get("tts_done_at", 0.0))
    except Exception:
        tts_age = 999.0

    try:
        false_age = now - float(data.get("false_wake_at", 0.0))
    except Exception:
        false_age = 999.0

    try:
        media_guard_until = float(data.get("media_guard_until", 0.0))
    except Exception:
        media_guard_until = 0.0

    try:
        hard_cooldown_until = float(data.get("hard_cooldown_until", 0.0))
    except Exception:
        hard_cooldown_until = 0.0

    if hard_cooldown_until > now:
        return False

    media_active = bool(data.get("media_active", False))

    try:
        followup_window = float(os.getenv("JARVIS_FOLLOWUP_LISTEN_WINDOW_SECONDS", "6.0"))
    except Exception:
        followup_window = 6.0

    if bool(data.get("followup_expected", False)) and tts_age >= 0 and tts_age <= followup_window and not media_active:
        return False

    try:
        dead_zone = float(os.getenv("JARVIS_POST_TTS_DEAD_ZONE_SECONDS", "0.35"))
    except Exception:
        dead_zone = 0.35

    try:
        guard_seconds = float(os.getenv("JARVIS_POST_TTS_GUARD_SECONDS", "4.20"))
    except Exception:
        guard_seconds = 4.20

    try:
        guard_threshold = float(os.getenv("JARVIS_POST_TTS_GUARD_THRESHOLD", "0.50"))
    except Exception:
        guard_threshold = 0.50

    if tts_age >= 0 and tts_age < dead_zone:
        return False

    if tts_age >= dead_zone and tts_age <= guard_seconds:
        return score >= guard_threshold

    try:
        recovery_seconds = float(os.getenv("JARVIS_FALSE_WAKE_RECOVERY_SECONDS", "6.0"))
    except Exception:
        recovery_seconds = 6.0

    try:
        recovery_threshold = float(os.getenv("JARVIS_FALSE_WAKE_RECOVERY_THRESHOLD", "0.60"))
    except Exception:
        recovery_threshold = 0.60

    if false_age >= 0 and false_age <= recovery_seconds and not media_active:
        return score >= recovery_threshold

    if media_active:
        try:
            block_after_false = float(os.getenv("JARVIS_MEDIA_FALSE_WAKE_BLOCK_SECONDS", "8.0"))
        except Exception:
            block_after_false = 8.0

        if false_age >= 0 and false_age <= block_after_false:
            return False

    if media_guard_until > now:
        try:
            media_threshold = float(os.getenv("JARVIS_MEDIA_GUARD_THRESHOLD", "0.995"))
        except Exception:
            media_threshold = 0.995
        return score >= media_threshold

    return True


# Compatibilidad si el daemon aún importa esto de parches previos.
def current_direct_listen_mode() -> str:
    return ""


def apply_direct_listen_policy(text: str) -> str:
    return text

# === JARVIS_V4136_FALSE_WAKE_TUNE_BEGIN ===
# Jarvis v4.1.3.6
# Suaviza la recuperación tras "comando vacío" para no exigir scores tan altos durante varios segundos.
def should_accept_wake_score(score):
    try:
        score = float(score)
    except Exception:
        return True

    data = _load()
    now = time.time()

    try:
        tts_age = now - float(data.get('tts_done_at', 0.0))
    except Exception:
        tts_age = 999.0

    try:
        false_age = now - float(data.get('false_wake_at', 0.0))
    except Exception:
        false_age = 999.0

    try:
        media_guard_until = float(data.get('media_guard_until', 0.0))
    except Exception:
        media_guard_until = 0.0

    try:
        hard_cooldown_until = float(data.get('hard_cooldown_until', 0.0))
    except Exception:
        hard_cooldown_until = 0.0

    if hard_cooldown_until > now:
        return False

    media_active = bool(data.get('media_active', False))

    try:
        followup_window = float(os.getenv('JARVIS_FOLLOWUP_LISTEN_WINDOW_SECONDS', '6.0'))
    except Exception:
        followup_window = 6.0

    if bool(data.get('followup_expected', False)) and tts_age >= 0 and tts_age <= followup_window and not media_active:
        return False

    try:
        dead_zone = float(os.getenv('JARVIS_POST_TTS_DEAD_ZONE_SECONDS', '0.25'))
    except Exception:
        dead_zone = 0.25

    try:
        guard_seconds = float(os.getenv('JARVIS_POST_TTS_GUARD_SECONDS', '2.40'))
    except Exception:
        guard_seconds = 2.40

    try:
        guard_threshold = float(os.getenv('JARVIS_POST_TTS_GUARD_THRESHOLD', '0.24'))
    except Exception:
        guard_threshold = 0.24

    if tts_age >= 0 and tts_age < dead_zone:
        return False

    if tts_age >= dead_zone and tts_age <= guard_seconds:
        return score >= guard_threshold

    try:
        recovery_seconds = float(os.getenv('JARVIS_FALSE_WAKE_RECOVERY_SECONDS', '2.80'))
    except Exception:
        recovery_seconds = 2.80

    try:
        recovery_threshold = float(os.getenv('JARVIS_FALSE_WAKE_RECOVERY_THRESHOLD', '0.24'))
    except Exception:
        recovery_threshold = 0.24

    if false_age >= 0 and false_age <= recovery_seconds and not media_active:
        return score >= recovery_threshold

    if media_active:
        try:
            block_after_false = float(os.getenv('JARVIS_MEDIA_FALSE_WAKE_BLOCK_SECONDS', '8.0'))
        except Exception:
            block_after_false = 8.0

        if false_age >= 0 and false_age <= block_after_false:
            return False

    if media_guard_until > now:
        try:
            media_threshold = float(os.getenv('JARVIS_MEDIA_GUARD_THRESHOLD', '0.995'))
        except Exception:
            media_threshold = 0.995
        return score >= media_threshold

    return True
# === JARVIS_V4136_FALSE_WAKE_TUNE_END ===

# === JARVIS_V4137_MEDIA_GUARD_AND_FALSE_WAKE_TUNE_BEGIN ===
# Jarvis v4.1.3.7
# Reduce falsas supresiones de MEDIA_GUARD y deja de arrastrar media_active
# indefinidamente después de usar intents no-media.

def _jarvis_v4137_media_session_active(data: dict) -> bool:
    try:
        media_active = bool(data.get('media_active', False))
    except Exception:
        media_active = False
    if not media_active:
        return False
    try:
        last_media_at = float(data.get('last_media_intent_at', 0.0) or 0.0)
    except Exception:
        last_media_at = 0.0
    try:
        last_non_media_at = float(data.get('last_non_media_intent_at', 0.0) or 0.0)
    except Exception:
        last_non_media_at = 0.0
    return last_media_at >= last_non_media_at


def note_tts_done() -> None:
    data = _load()
    now = time.time()
    data['tts_done_at'] = now

    media_requested = bool(data.get('media_guard_requested', False))
    media_active = _jarvis_v4137_media_session_active(data)
    if media_requested or media_active:
        try:
            media_guard_seconds = float(os.getenv('JARVIS_MEDIA_GUARD_SECONDS', '2.20'))
        except Exception:
            media_guard_seconds = 2.20
        data['media_guard_until'] = now + media_guard_seconds
        data['media_active'] = True
        data['media_guard_requested'] = False

    _save(data)


def note_classified_intent(intent_name: str, entities: dict | None = None) -> None:
    name = str(intent_name or '').strip()
    entities = dict(entities or {})
    data = _load()
    now = time.time()

    if name in {'stop_music', 'pause_music'}:
        data['media_active'] = False
        data['media_guard_requested'] = False
        data['last_non_media_intent_at'] = now
        data.pop('media_guard_until', None)
        _reset_false_wake_state(data)
        _save(data)
        return

    media_intents = {'open_url', 'play_music', 'play_media'}
    autoplay = bool(entities.get('autoplay', False))
    platform = str(entities.get('platform', '') or '').strip().lower()
    target = str(entities.get('target', '') or '').strip().lower()

    if name in media_intents and (autoplay or platform == 'youtube' or target == 'youtube'):
        data['media_guard_requested'] = True
        data['media_active'] = True
        data['last_media_intent_at'] = now
        _reset_false_wake_state(data)
        _save(data)
        return

    data['last_non_media_intent_at'] = now
    data['media_guard_requested'] = False
    if float(data.get('last_media_intent_at', 0.0) or 0.0) <= now:
        data['media_active'] = False
        data.pop('media_guard_until', None)
    _reset_false_wake_state(data)
    _save(data)


def should_accept_wake_score(score) -> bool:
    try:
        score = float(score)
    except Exception:
        return True

    data = _load()
    now = time.time()

    try:
        tts_age = now - float(data.get('tts_done_at', 0.0))
    except Exception:
        tts_age = 999.0

    try:
        false_age = now - float(data.get('false_wake_at', 0.0))
    except Exception:
        false_age = 999.0

    try:
        media_guard_until = float(data.get('media_guard_until', 0.0))
    except Exception:
        media_guard_until = 0.0

    try:
        hard_cooldown_until = float(data.get('hard_cooldown_until', 0.0))
    except Exception:
        hard_cooldown_until = 0.0

    if hard_cooldown_until > now:
        return False

    media_active = _jarvis_v4137_media_session_active(data)

    try:
        followup_window = float(os.getenv('JARVIS_FOLLOWUP_LISTEN_WINDOW_SECONDS', '6.0'))
    except Exception:
        followup_window = 6.0

    if bool(data.get('followup_expected', False)) and tts_age >= 0 and tts_age <= followup_window and not media_active:
        return False

    try:
        dead_zone = float(os.getenv('JARVIS_POST_TTS_DEAD_ZONE_SECONDS', '0.14'))
    except Exception:
        dead_zone = 0.14
    try:
        guard_seconds = float(os.getenv('JARVIS_POST_TTS_GUARD_SECONDS', '1.10'))
    except Exception:
        guard_seconds = 1.10
    try:
        guard_threshold = float(os.getenv('JARVIS_POST_TTS_GUARD_THRESHOLD', '0.18'))
    except Exception:
        guard_threshold = 0.18

    if tts_age >= 0 and tts_age < dead_zone:
        return False
    if tts_age >= dead_zone and tts_age <= guard_seconds:
        return score >= guard_threshold

    try:
        recovery_seconds = float(os.getenv('JARVIS_FALSE_WAKE_RECOVERY_SECONDS', '1.10'))
    except Exception:
        recovery_seconds = 1.10
    try:
        recovery_threshold = float(os.getenv('JARVIS_FALSE_WAKE_RECOVERY_THRESHOLD', '0.18'))
    except Exception:
        recovery_threshold = 0.18

    if false_age >= 0 and false_age <= recovery_seconds and not media_active:
        return score >= recovery_threshold

    if media_active:
        try:
            block_after_false = float(os.getenv('JARVIS_MEDIA_FALSE_WAKE_BLOCK_SECONDS', '1.00'))
        except Exception:
            block_after_false = 1.00
        try:
            media_false_threshold = float(os.getenv('JARVIS_MEDIA_FALSE_WAKE_THRESHOLD', '0.30'))
        except Exception:
            media_false_threshold = 0.30
        if false_age >= 0 and false_age <= block_after_false:
            return score >= media_false_threshold

    if media_guard_until > now:
        try:
            media_threshold = float(os.getenv('JARVIS_MEDIA_GUARD_THRESHOLD', '0.30'))
        except Exception:
            media_threshold = 0.30
        return score >= media_threshold

    return True
# === JARVIS_V4137_MEDIA_GUARD_AND_FALSE_WAKE_TUNE_END ===
