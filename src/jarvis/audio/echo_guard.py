from __future__ import annotations

import time
from typing import Any

# Jarvis v3.2 Echo Guard
# Compatible exports for the already patched daemon.py and wakeword.py:
# - mark_tts_start
# - mark_tts_end(hard_cooldown=..., soft_cooldown=..., soft_threshold=...)
# - should_discard_audio_frame
# - should_suppress_detection
# - reset_openwakeword_model
# - is_tts_cooldown_active
# - EchoGuard class wrapper

_SPEAKING: bool = False
_HARD_UNTIL: float = 0.0
_SOFT_UNTIL: float = 0.0
_SOFT_THRESHOLD: float = 0.985
_LAST_TTS_END: float = 0.0

DEFAULT_HARD_COOLDOWN = 8.0
DEFAULT_SOFT_COOLDOWN = 14.0
DEFAULT_SOFT_THRESHOLD = 0.985


def _now() -> float:
    return time.monotonic()


def mark_tts_start(*args: Any, **kwargs: Any) -> None:
    """Mark that Jarvis started speaking. Accepts unused args for compatibility."""
    global _SPEAKING, _HARD_UNTIL, _SOFT_UNTIL
    _SPEAKING = True
    # While speaking, hard block is effectively active.
    _HARD_UNTIL = float("inf")
    _SOFT_UNTIL = float("inf")


def mark_tts_end(
    hard_cooldown: float | None = None,
    soft_cooldown: float | None = None,
    soft_threshold: float | None = None,
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Mark that Jarvis finished speaking.

    Supports the keyword arguments currently used by daemon.py:
      mark_tts_end(hard_cooldown=hard, soft_cooldown=soft, soft_threshold=threshold)

    The hard window discards audio frames completely.
    The soft window allows only very high-confidence wake scores.
    """
    global _SPEAKING, _HARD_UNTIL, _SOFT_UNTIL, _SOFT_THRESHOLD, _LAST_TTS_END

    now = _now()
    hard = DEFAULT_HARD_COOLDOWN if hard_cooldown is None else float(hard_cooldown)
    soft = DEFAULT_SOFT_COOLDOWN if soft_cooldown is None else float(soft_cooldown)
    threshold = DEFAULT_SOFT_THRESHOLD if soft_threshold is None else float(soft_threshold)

    _SPEAKING = False
    _LAST_TTS_END = now
    _HARD_UNTIL = now + max(0.0, hard)
    _SOFT_UNTIL = now + max(0.0, soft)
    _SOFT_THRESHOLD = threshold


# Backward/alternate names some patches may have used.
tts_started = mark_tts_start
tts_ended = mark_tts_end
mark_start = mark_tts_start
mark_end = mark_tts_end


def is_hard_cooldown_active() -> bool:
    return _SPEAKING or _now() < _HARD_UNTIL


def is_soft_cooldown_active() -> bool:
    return _SPEAKING or _now() < _SOFT_UNTIL


def is_tts_cooldown_active() -> bool:
    return is_hard_cooldown_active() or is_soft_cooldown_active()


def should_discard_audio_frame(*args: Any, **kwargs: Any) -> bool:
    """
    Used by wakeword.py before feeding frames to openWakeWord.
    During hard cooldown we discard frames so echo does not enter the model.
    """
    return is_hard_cooldown_active()


def should_suppress_detection(
    score: float | None = None,
    *args: Any,
    **kwargs: Any,
) -> bool:
    """
    Used by wakeword.py right before accepting a wake detection.

    During hard cooldown: suppress everything.
    During soft cooldown: suppress scores below _SOFT_THRESHOLD.
    Outside cooldown: allow normal wakeword logic.
    """
    if is_hard_cooldown_active():
        return True

    if is_soft_cooldown_active():
        try:
            s = float(score if score is not None else 0.0)
        except Exception:
            s = 0.0
        return s < _SOFT_THRESHOLD

    return False


def reset_openwakeword_model(model: Any = None, logger: Any = None, *args: Any, **kwargs: Any) -> bool:
    """Best-effort reset/clear of openWakeWord internal prediction buffers."""
    if model is None:
        return False

    # Preferred if available.
    try:
        reset = getattr(model, "reset", None)
        if callable(reset):
            reset()
            return True
    except Exception as exc:
        if logger:
            try:
                logger.debug("No se pudo resetear openWakeWord con reset(): %s", exc)
            except Exception:
                pass

    # Fallback: clear common buffer fields if present.
    cleared = False
    for attr in ("prediction_buffer", "prediction_buffers", "prediction_history"):
        try:
            buf = getattr(model, attr, None)
            if isinstance(buf, dict):
                for value in buf.values():
                    if hasattr(value, "clear"):
                        value.clear()
                        cleared = True
            elif hasattr(buf, "clear"):
                buf.clear()
                cleared = True
        except Exception as exc:
            if logger:
                try:
                    logger.debug("No se pudo limpiar buffer %s: %s", attr, exc)
                except Exception:
                    pass

    return cleared


class EchoGuard:
    """Class wrapper for compatibility with earlier patch attempts."""

    mark_start = staticmethod(mark_tts_start)
    mark_end = staticmethod(mark_tts_end)
    tts_started = staticmethod(mark_tts_start)
    tts_ended = staticmethod(mark_tts_end)
    is_suppressed = staticmethod(should_suppress_detection)
    should_suppress_detection = staticmethod(should_suppress_detection)
    should_discard_audio_frame = staticmethod(should_discard_audio_frame)
    reset_model = staticmethod(reset_openwakeword_model)
    reset_openwakeword_model = staticmethod(reset_openwakeword_model)
    is_tts_cooldown_active = staticmethod(is_tts_cooldown_active)
