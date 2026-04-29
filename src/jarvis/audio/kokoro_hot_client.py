# -*- coding: utf-8 -*-
"""
Jarvis Kokoro Hot Client v4.0.5.1

Mantiene un subprocess Kokoro vivo y guarda log visible:
  ~/.local/share/jarvis/logs/kokoro_hot_server.log

# >>> JARVIS_V4051_KOKORO_HOT_CLIENT_DEBUG
"""

from __future__ import annotations

import json
import os
import re
import select
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/share/jarvis")).expanduser()
TMP_DIR = STATE_DIR / "tmp"
LOG_DIR = STATE_DIR / "logs"
LOG_FILE = LOG_DIR / "kokoro_hot_server.log"
BUS_DB = STATE_DIR / "events_bus.db"
PROJECT = Path(os.environ.get("JARVIS_PROJECT", "~/Descargas/jarvis-local-voice-agent-v1.0.1/jarvis-local-voice-agent")).expanduser()
SRC = PROJECT / "src"
SERVER_FILE = SRC / "jarvis" / "audio" / "kokoro_hot_server.py"
_CONFIG = Path("~/.config/jarvis/config.yaml").expanduser()
_PROC: subprocess.Popen[str] | None = None
_LOG_FH = None


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
                (datetime.now().isoformat(timespec="seconds"), topic, str(summary or "")[:160], "kokoro_hot", json.dumps(payload or {}, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _tail(path: Path, max_chars: int = 4000) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
        return data[-max_chars:]
    except Exception as exc:
        return f"<no pude leer {path}: {exc}>"


def _read_config_value(key: str) -> str | None:
    try:
        text = _CONFIG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = re.search(rf"(?m)^\s*{re.escape(key)}\s*:\s*['\"]?([^'\"\n#]+)", text)
    if m:
        return m.group(1).strip()
    return None


def kokoro_python() -> Path:
    raw = os.environ.get("JARVIS_KOKORO_PYTHON") or _read_config_value("kokoro_python") or "~/.local/share/jarvis/kokoro/venv/bin/python"
    return Path(raw).expanduser()


def default_voice() -> str:
    return os.environ.get("JARVIS_KOKORO_VOICE") or _read_config_value("kokoro_voice") or "em_alex"


def default_lang() -> str:
    return os.environ.get("JARVIS_KOKORO_LANG") or _read_config_value("kokoro_lang") or "e"


def default_speed() -> str:
    return os.environ.get("JARVIS_KOKORO_SPEED") or _read_config_value("kokoro_speed") or "0.95"


def disabled() -> bool:
    return os.environ.get("JARVIS_KOKORO_HOT_DISABLE", "0").strip().lower() in {"1", "true", "yes", "on"}


def timeout_seconds() -> float:
    try:
        return max(3.0, min(90.0, float(os.environ.get("JARVIS_KOKORO_HOT_TIMEOUT", "45"))))
    except Exception:
        return 45.0


def _start_server() -> subprocess.Popen[str] | None:
    global _PROC, _LOG_FH
    if disabled():
        return None
    if _PROC is not None and _PROC.poll() is None:
        return _PROC
    py = kokoro_python()
    if not py.exists():
        emit("tts.hot.failed", "kokoro python no existe", {"python": str(py)})
        return None
    if not SERVER_FILE.exists():
        emit("tts.hot.failed", "server file no existe", {"server": str(SERVER_FILE)})
        return None
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")
    env.setdefault("JARVIS_KOKORO_LANG", default_lang())
    try:
        # Reabrir log por proceso. No usamos DEVNULL porque necesitamos ver el error real.
        _LOG_FH = open(LOG_FILE, "ab", buffering=0)
        _LOG_FH.write(("\n--- start " + datetime.now().isoformat(timespec="seconds") + " ---\n").encode("utf-8"))
        t0 = time.perf_counter()
        _PROC = subprocess.Popen(
            [str(py), "-u", str(SERVER_FILE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=_LOG_FH,
            text=True,
            bufsize=1,
            env=env,
        )
        emit("tts.hot.started", "Kokoro hot server iniciado", {"python": str(py), "pid": _PROC.pid, "log": str(LOG_FILE), "start_ms": int((time.perf_counter() - t0) * 1000)})
        return _PROC
    except Exception as exc:
        emit("tts.hot.failed", "no pude iniciar Kokoro hot server", {"error": str(exc), "python": str(py), "log": str(LOG_FILE)})
        _PROC = None
        return None


def _read_json_line(proc: subprocess.Popen[str], rid: str, timeout: float) -> dict[str, Any] | None:
    if proc.stdout is None:
        return None
    deadline = time.monotonic() + timeout
    fd = proc.stdout.fileno()
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        ready, _, _ = select.select([fd], [], [], min(0.5, remaining))
        if not ready:
            if proc.poll() is not None:
                return None
            continue
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except Exception:
            # Algunas librerías imprimen texto no-JSON. Se ignora.
            continue
        if not rid or str(obj.get("id", "")) == str(rid):
            return obj
    return None


def _request(req: dict[str, Any], timeout: float | None = None) -> dict[str, Any] | None:
    proc = _start_server()
    if proc is None or proc.stdin is None:
        return None
    rid = str(req.get("id") or uuid.uuid4().hex)
    req["id"] = rid
    try:
        proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        return _read_json_line(proc, rid, timeout or timeout_seconds())
    except Exception as exc:
        emit("tts.hot.failed", "request error", {"error": str(exc), "log": str(LOG_FILE)})
        return None


def request_synthesis(text: str, output: str | os.PathLike[str], voice: str | None = None, speed: str | float | None = None, lang: str | None = None) -> dict[str, Any] | None:
    req = {
        "text": str(text or ""),
        "voice": str(voice or default_voice()),
        "speed": str(speed or default_speed()),
        "lang": str(lang or default_lang()),
        "output": str(Path(output).expanduser()),
    }
    t0 = time.perf_counter()
    res = _request(req)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if not res:
        emit("tts.hot.timeout", str(text)[:120], {"elapsed_ms": elapsed_ms, "timeout": timeout_seconds(), "log": str(LOG_FILE), "log_tail": _tail(LOG_FILE, 2000)})
        return None
    if not res.get("ok"):
        emit("tts.hot.failed", str(text)[:120], {"response": res, "elapsed_ms": elapsed_ms, "log": str(LOG_FILE)})
        return None
    emit("tts.hot.generated", str(text)[:120], {**res, "elapsed_ms": elapsed_ms, "log": str(LOG_FILE)})
    return res


def synthesize_play_cache(text: str, voice: str | None = None, speed: str | float | None = None, lang: str | None = None) -> bool:
    if disabled():
        return False
    text = str(text or "").strip()
    if not text:
        return False
    voice = str(voice or default_voice())
    speed = str(speed or default_speed())
    lang = str(lang or default_lang())
    try:
        from jarvis.audio import tts_cache
        cached = tts_cache.get_cached(text, voice, speed)
        if cached is not None:
            tts_cache.play_wav(cached)
            return True
    except Exception:
        tts_cache = None
    out = TMP_DIR / "jarvis_kokoro.wav"
    res = request_synthesis(text, out, voice=voice, speed=speed, lang=lang)
    if not res:
        return False
    if not out.exists() or out.stat().st_size <= 44:
        emit("tts.hot.failed", str(text)[:120], {"error": "wav no generado", "path": str(out), "log": str(LOG_FILE), "log_tail": _tail(LOG_FILE, 2000)})
        return False
    try:
        if tts_cache is not None:
            tts_cache.save_from_file(out, text, voice, speed)
    except Exception:
        pass
    try:
        from jarvis.audio.wav_pad import play_wav_padded
        return bool(play_wav_padded(out, quiet=True))
    except Exception:
        try:
            subprocess.run(["aplay", "-q", str(out)], check=False)
            return True
        except Exception:
            return False


def debug(text: str) -> int:
    print(f"python={kokoro_python()}")
    print(f"server={SERVER_FILE}")
    print(f"log={LOG_FILE}")
    print(f"disabled={disabled()}")
    print(f"voice={default_voice()} lang={default_lang()} speed={default_speed()} timeout={timeout_seconds()}")
    diag = _request({"cmd": "diagnose"}, timeout=timeout_seconds())
    print("DIAGNOSE:")
    print(json.dumps(diag, ensure_ascii=False, indent=2) if diag else "FAILED_DIAGNOSE")
    out = TMP_DIR / "jarvis_kokoro_hot_debug.wav"
    res = request_synthesis(text, out, voice=default_voice(), speed=default_speed(), lang=default_lang())
    print("SYNTH:")
    print(json.dumps(res, ensure_ascii=False, indent=2) if res else "FAILED_SYNTH")
    print("LOG_TAIL:")
    print(_tail(LOG_FILE, 5000))
    if res and out.exists() and out.stat().st_size > 44:
        try:
            from jarvis.audio.wav_pad import play_wav_padded
            play_wav_padded(out, quiet=True)
        except Exception:
            subprocess.run(["aplay", "-q", str(out)], check=False)
        return 0
    return 1


# >>> JARVIS_V4053_HOT_CLIENT_PRELOAD_ASYNC
# Helper añadido por v4.0.5.3: arranca el Kokoro hot server en background
# para que el pipeline se cargue antes de la primera respuesta real.
def preload_async() -> bool:
    try:
        return _start_server() is not None
    except Exception:
        return False
# <<< JARVIS_V4053_HOT_CLIENT_PRELOAD_ASYNC

def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Jarvis Kokoro hot client")
    parser.add_argument("cmd", choices=["status", "test", "debug"])
    parser.add_argument("text", nargs="*", default=[])
    ns = parser.parse_args(argv)
    if ns.cmd == "status":
        print(f"python={kokoro_python()}")
        print(f"server={SERVER_FILE}")
        print(f"log={LOG_FILE}")
        print(f"disabled={disabled()}")
        print(f"proc_alive={_PROC is not None and _PROC.poll() is None}")
        print("nota=proc_alive en este comando solo refleja este proceso CLI; en el servicio Jarvis será otro proceso.")
        return 0
    text = " ".join(ns.text).strip() or "Prueba de voz rápida, señor."
    if ns.cmd == "debug":
        return debug(text)
    if ns.cmd == "test":
        ok = synthesize_play_cache(text)
        print("OK" if ok else "FAILED")
        if not ok:
            print("LOG_TAIL:")
            print(_tail(LOG_FILE, 5000))
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
# <<< JARVIS_V4051_KOKORO_HOT_CLIENT_DEBUG

# >>> JARVIS_V4056_HOT_CLIENT_COMPAT_API
# Compat API para que kokoro_bridge.py v4.0.5.5 pueda llamar al hot client.
# No cambia el protocolo del servidor; solo expone nombres estándar:
#   speak(), speak_hot(), kokoro_hot_speak(), synthesize_to_file(), play_wav()

def play_wav(path, *args, **kwargs) -> bool:
    """Reproduce WAV usando el padding existente si está disponible."""
    try:
        from jarvis.audio.wav_pad import play_wav_padded
        return bool(play_wav_padded(path, quiet=True))
    except Exception:
        try:
            import subprocess
            subprocess.run(["aplay", "-q", str(path)], check=False)
            return True
        except Exception:
            return False


def synthesize_to_file(
    text=None,
    out_path=None,
    output=None,
    path=None,
    voice=None,
    speed=None,
    lang=None,
    **kwargs,
):
    """
    API compatible para generar WAV sin reproducir.
    Devuelve dict de request_synthesis o None.
    """
    target = out_path or output or path or kwargs.get("wav_path") or kwargs.get("file")
    if target is None:
        from pathlib import Path
        target = Path.home() / ".local/share/jarvis/tmp/jarvis_kokoro.wav"
    try:
        return request_synthesis(
            str(text or ""),
            target,
            voice=voice,
            speed=speed,
            lang=lang,
        )
    except Exception:
        return None


def speak(
    text=None,
    voice=None,
    speed=None,
    lang=None,
    logger=None,
    **kwargs,
) -> bool:
    """
    API compatible para generar + cachear + reproducir con Kokoro hot.
    """
    try:
        ok = synthesize_play_cache(
            str(text or ""),
            voice=voice,
            speed=speed,
            lang=lang,
        )
        return bool(ok)
    except Exception as exc:
        try:
            if logger is not None and hasattr(logger, "warning"):
                logger.warning("kokoro_hot_client.speak falló: %s", exc)
        except Exception:
            pass
        return False


def speak_hot(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def hot_speak(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def kokoro_hot_speak(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def synthesize_and_play(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def synthesize_play(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def synth_and_play(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)


def say(*args, **kwargs) -> bool:
    return speak(*args, **kwargs)

# <<< JARVIS_V4056_HOT_CLIENT_COMPAT_API

# === JARVIS_V4070_ALEX_MAX_CLIENT_TIMING_BEGIN ===
# Jarvis v4.0.7.0 — timing de Kokoro Hot/Alex.
try:
    import time as _jarvis_v4070_time
    import logging as _jarvis_v4070_logging

    def _jarvis_v4070_publish(topic, payload):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload, source="kokoro_alex_max")
        except Exception:
            pass

    def _jarvis_v4070_log(level, msg, *args):
        try:
            getattr(_jarvis_v4070_logging.getLogger("jarvis"), level)(msg, *args)
        except Exception:
            pass

    if "request_synthesis" in globals() and callable(request_synthesis):
        if not getattr(request_synthesis, "__jarvis_v4070_alex_timing__", False):
            _jarvis_v4070_orig_request_synthesis = request_synthesis

            def request_synthesis(*args, **kwargs):
                start = _jarvis_v4070_time.monotonic()
                ok = False
                err = None
                try:
                    result = _jarvis_v4070_orig_request_synthesis(*args, **kwargs)
                    ok = bool(result)
                    return result
                except Exception as exc:
                    err = str(exc)
                    raise
                finally:
                    elapsed_ms = int((_jarvis_v4070_time.monotonic() - start) * 1000)
                    _jarvis_v4070_log("info", "KOKORO_HOT_SYNTH elapsed_ms=%s ok=%s error=%s", elapsed_ms, ok, err or "")
                    _jarvis_v4070_publish("tts.kokoro.synth.timing", {"elapsed_ms": elapsed_ms, "ok": ok, "error": err})

            request_synthesis.__jarvis_v4070_alex_timing__ = True
            request_synthesis.__wrapped__ = _jarvis_v4070_orig_request_synthesis

    if "play_wav" in globals() and callable(play_wav):
        if not getattr(play_wav, "__jarvis_v4070_alex_timing__", False):
            _jarvis_v4070_orig_play_wav = play_wav

            def play_wav(*args, **kwargs):
                start = _jarvis_v4070_time.monotonic()
                ok = False
                err = None
                try:
                    result = _jarvis_v4070_orig_play_wav(*args, **kwargs)
                    ok = bool(result)
                    return result
                except Exception as exc:
                    err = str(exc)
                    raise
                finally:
                    elapsed_ms = int((_jarvis_v4070_time.monotonic() - start) * 1000)
                    _jarvis_v4070_log("info", "KOKORO_HOT_PLAY elapsed_ms=%s ok=%s error=%s", elapsed_ms, ok, err or "")
                    _jarvis_v4070_publish("tts.kokoro.play.timing", {"elapsed_ms": elapsed_ms, "ok": ok, "error": err})

            play_wav.__jarvis_v4070_alex_timing__ = True
            play_wav.__wrapped__ = _jarvis_v4070_orig_play_wav

    if "synthesize_play_cache" in globals() and callable(synthesize_play_cache):
        if not getattr(synthesize_play_cache, "__jarvis_v4070_alex_timing__", False):
            _jarvis_v4070_orig_synthesize_play_cache = synthesize_play_cache

            def synthesize_play_cache(*args, **kwargs):
                start = _jarvis_v4070_time.monotonic()
                ok = False
                err = None
                try:
                    result = _jarvis_v4070_orig_synthesize_play_cache(*args, **kwargs)
                    ok = bool(result)
                    return result
                except Exception as exc:
                    err = str(exc)
                    raise
                finally:
                    elapsed_ms = int((_jarvis_v4070_time.monotonic() - start) * 1000)
                    _jarvis_v4070_log("info", "TTS provider usado: kokoro-hot-max | total_ms=%s ok=%s", elapsed_ms, ok)
                    _jarvis_v4070_publish("tts.kokoro.hotmax.timing", {"elapsed_ms": elapsed_ms, "ok": ok, "error": err})

            synthesize_play_cache.__jarvis_v4070_alex_timing__ = True
            synthesize_play_cache.__wrapped__ = _jarvis_v4070_orig_synthesize_play_cache

except Exception:
    pass
# === JARVIS_V4070_ALEX_MAX_CLIENT_TIMING_END ===
