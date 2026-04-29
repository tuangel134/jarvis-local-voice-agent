# -*- coding: utf-8 -*-
"""
Jarvis WAV playback padding helper v4.0.3.4

Añade silencio al inicio de WAVs antes de mandarlos a aplay.
Esto evita que ALSA/Pulse/PipeWire se coma la primera palabra al abrir el dispositivo.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

# >>> JARVIS_V4034_WAV_PAD_HELPER
STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/share/jarvis")).expanduser()
TMP_DIR = STATE_DIR / "tmp"
BUS_DB = STATE_DIR / "events_bus.db"


def emit(topic: str, summary: str = "", payload: dict[str, Any] | None = None) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(BUS_DB))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "timestamp TEXT,"
                "topic TEXT,"
                "summary TEXT,"
                "source TEXT,"
                "payload TEXT"
                ")"
            )
            conn.execute(
                "INSERT INTO events(timestamp, topic, summary, source, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    topic,
                    str(summary or "")[:160],
                    "wav_pad",
                    json.dumps(payload or {}, ensure_ascii=False),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def lead_silence_ms() -> int:
    try:
        raw = os.environ.get("JARVIS_TTS_LEAD_SILENCE_MS", "650")
        value = int(str(raw).strip())
        if value < 0:
            return 0
        if value > 3000:
            return 3000
        return value
    except Exception:
        return 650


def make_padded_wav(src: str | os.PathLike[str]) -> Path:
    """Crea un WAV temporal con silencio inicial. Si algo falla, regresa el original."""
    src_path = Path(src).expanduser()
    lead_ms = lead_silence_ms()
    if lead_ms <= 0:
        return src_path
    if not src_path.exists() or src_path.stat().st_size <= 44:
        return src_path

    # Evitar padding recursivo si ya nos pasan el archivo temporal padded.
    if src_path.name.startswith("jarvis_tts_padded_"):
        return src_path

    try:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        dst = TMP_DIR / f"jarvis_tts_padded_{src_path.stem}.wav"
        with wave.open(str(src_path), "rb") as reader:
            params = reader.getparams()
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            framerate = reader.getframerate()
            frames = reader.readframes(reader.getnframes())
        silence_frames = int(framerate * (lead_ms / 1000.0))
        silence = b"\x00" * silence_frames * channels * sample_width
        with wave.open(str(dst), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(silence + frames)
        emit("tts.play.padded", src_path.name, {"lead_ms": lead_ms, "source": str(src_path), "path": str(dst)})
        return dst
    except Exception as exc:
        emit("tts.play.pad_failed", src_path.name, {"error": str(exc), "source": str(src_path)})
        return src_path


def play_wav_padded(path: str | os.PathLike[str], quiet: bool = True) -> bool:
    p = Path(path).expanduser()
    if not p.exists():
        return False
    target = make_padded_wav(p)
    logger = logging.getLogger("jarvis")
    cmd = ["aplay"]
    if quiet:
        cmd.append("-q")
    cmd.append(str(target))
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        ok = proc.returncode == 0
        emit("tts.play.exec", target.name, {"cmd": cmd, "returncode": proc.returncode, "path": str(target), "quiet": quiet, "stderr": (proc.stderr or "")[:500]})
        if not ok:
            logger.warning("TTS_PLAYBACK_FAILED cmd=%s rc=%s stderr=%s", cmd, proc.returncode, (proc.stderr or "")[:240])
        return ok
    except Exception as exc:
        emit("tts.play.exec_failed", target.name, {"cmd": cmd, "path": str(target), "error": str(exc)})
        logger.warning("TTS_PLAYBACK_EXCEPTION cmd=%s error=%s", cmd, exc)
        try:
            fallback_cmd = ["aplay", str(target)]
            proc = subprocess.run(fallback_cmd, check=False, capture_output=True, text=True)
            ok = proc.returncode == 0
            emit("tts.play.exec", target.name, {"cmd": fallback_cmd, "returncode": proc.returncode, "path": str(target), "quiet": False, "stderr": (proc.stderr or "")[:500]})
            if not ok:
                logger.warning("TTS_PLAYBACK_FAILED cmd=%s rc=%s stderr=%s", fallback_cmd, proc.returncode, (proc.stderr or "")[:240])
            return ok
        except Exception as exc2:
            emit("tts.play.exec_failed", target.name, {"cmd": ["aplay", str(target)], "path": str(target), "error": str(exc2)})
            logger.warning("TTS_PLAYBACK_EXCEPTION cmd=%s error=%s", ["aplay", str(target)], exc2)
            return False
# <<< JARVIS_V4034_WAV_PAD_HELPER

# === JARVIS_V4065_TTS_LEAD_SILENCE_CALIBRATION_BEGIN ===
# Jarvis v4.0.6.5
# Corrige corte mínimo al inicio de Kokoro Hot: si el sistema intenta usar
# poco padding, fuerza un mínimo seguro. Se puede subir con:
#   JARVIS_TTS_LEAD_SILENCE_MS=600
# Se puede bajar solo si también se baja el mínimo:
#   JARVIS_TTS_LEAD_SILENCE_MIN_MS=300
try:
    import os as _jarvis_v4065_os
    import logging as _jarvis_v4065_logging

    _jarvis_v4065_original_lead_silence_ms = lead_silence_ms

    def lead_silence_ms() -> int:
        logger = _jarvis_v4065_logging.getLogger("jarvis")

        try:
            raw = _jarvis_v4065_os.environ.get("JARVIS_TTS_LEAD_SILENCE_MS")
            if raw is not None and str(raw).strip() != "":
                value = int(float(raw))
            else:
                value = int(_jarvis_v4065_original_lead_silence_ms())
        except Exception:
            value = 450

        try:
            min_ms = int(float(_jarvis_v4065_os.environ.get("JARVIS_TTS_LEAD_SILENCE_MIN_MS", "450")))
        except Exception:
            min_ms = 450

        try:
            max_ms = int(float(_jarvis_v4065_os.environ.get("JARVIS_TTS_LEAD_SILENCE_MAX_MS", "1200")))
        except Exception:
            max_ms = 1200

        adjusted = max(min_ms, min(max_ms, value))

        try:
            if adjusted != value:
                logger.info(
                    "TTS lead silence ajustado: requested_ms=%s adjusted_ms=%s min_ms=%s max_ms=%s",
                    value,
                    adjusted,
                    min_ms,
                    max_ms,
                )
        except Exception:
            pass

        return int(adjusted)

except Exception:
    pass
# === JARVIS_V4065_TTS_LEAD_SILENCE_CALIBRATION_END ===

# === JARVIS_V4136_WAV_PAD_OUTPUT_RECOVERY_BEGIN ===
# Jarvis v4.1.3.6
# Refuerza playback de WAV padded (Kokoro/Piper cache/etc.) re-aplicando la salida preferida del usuario.
try:
    import time as _jarvis_v4136w_time
    import logging as _jarvis_v4136w_logging

    def _jarvis_v4136w_is_playback_error(stderr: str) -> bool:
        low = str(stderr or '').lower()
        return (
            'device or resource busy' in low
            or 'audio open error' in low
            or 'broken pipe' in low
            or 'input/output error' in low
            or 'no such file or directory' in low
            or 'main:831: audio open error' in low
            or 'unable to open slave' in low
            or 'device disconnected' in low
        )

    if 'play_wav_padded' in globals() and callable(play_wav_padded):
        _jarvis_v4136w_orig_play = play_wav_padded
        if not getattr(_jarvis_v4136w_orig_play, '__jarvis_v4136_output_hotplug__', False):
            def play_wav_padded(path, quiet=True):
                p = Path(path).expanduser()
                if not p.exists():
                    return False
                logger = _jarvis_v4136w_logging.getLogger('jarvis')
                target = make_padded_wav(p)
                last_stderr = ''

                for attempt in range(1, 6 + 1):
                    try:
                        from jarvis.config import load_config as _jarvis_v4136w_load_config
                        from jarvis.audio.device_selector import resolve_output_device as _jarvis_v4136w_resolve_output
                        cfg = _jarvis_v4136w_load_config()
                        result = _jarvis_v4136w_resolve_output(cfg)
                        logger.info(
                            'TTS_PLAYBACK_RESELECT attempt=%s/%s requested=%r requested_name=%r chosen=%r chosen_name=%s reason=%s',
                            attempt,
                            6,
                            result.get('requested'),
                            result.get('requested_name'),
                            result.get('device'),
                            result.get('name'),
                            result.get('reason'),
                        )
                    except Exception:
                        pass

                    cmd = ['aplay']
                    if quiet:
                        cmd.append('-q')
                    cmd.append(str(target))
                    try:
                        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
                        stderr = (proc.stderr or '')
                        emit('tts.play.exec', target.name, {'cmd': cmd, 'returncode': proc.returncode, 'path': str(target), 'quiet': quiet, 'stderr': stderr[:500]})
                        if proc.returncode == 0:
                            logger.info('TTS_PLAYBACK_READY cmd=%s', cmd)
                            return True
                        last_stderr = stderr
                        if not _jarvis_v4136w_is_playback_error(stderr):
                            logger.warning('TTS_PLAYBACK_FAILED cmd=%s rc=%s stderr=%s', cmd, proc.returncode, stderr[:240])
                            return False
                        backoff = round(min(0.35 * attempt, 1.75), 2)
                        logger.warning(
                            'TTS_PLAYBACK_RECOVERY attempt=%s/%s rc=%s stderr=%s backoff=%.2fs',
                            attempt,
                            6,
                            proc.returncode,
                            stderr[:240],
                            backoff,
                        )
                        _jarvis_v4136w_time.sleep(backoff)
                    except Exception as exc:
                        last_stderr = str(exc)
                        backoff = round(min(0.35 * attempt, 1.75), 2)
                        logger.warning('TTS_PLAYBACK_EXCEPTION attempt=%s/%s error=%s backoff=%.2fs', attempt, 6, exc, backoff)
                        _jarvis_v4136w_time.sleep(backoff)

                emit('tts.play.exec_failed', target.name, {'cmd': ['aplay', str(target)], 'path': str(target), 'error': last_stderr[:500]})
                logger.warning('TTS_PLAYBACK_GIVEUP path=%s error=%s', target, last_stderr[:240])
                return False

            play_wav_padded.__jarvis_v4136_output_hotplug__ = True
            play_wav_padded.__wrapped__ = _jarvis_v4136w_orig_play
            globals()['play_wav_padded'] = play_wav_padded
except Exception:
    pass
# === JARVIS_V4136_WAV_PAD_OUTPUT_RECOVERY_END ===
