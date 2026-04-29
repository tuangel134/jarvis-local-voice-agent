from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Any

def _assistant(config):
    if isinstance(config, dict) and isinstance(config.get("assistant"), dict):
        return config["assistant"]
    return config if isinstance(config, dict) else {}

def _get(config, key, default=None):
    a = _assistant(config)
    if key in a:
        return a.get(key)
    if isinstance(config, dict):
        return config.get(key, default)
    return default

def _event(topic, payload):
    try:
        from jarvis.bus.event_bus import EventBus
        EventBus().publish(topic, payload, source="kokoro_tts")
    except Exception:
        pass

def _echo_start():
    try:
        from jarvis.audio import echo_guard
        for n in ("mark_tts_start", "tts_started", "mark_start"):
            fn = getattr(echo_guard, n, None)
            if callable(fn):
                fn()
                return
    except Exception:
        pass

def _echo_end():
    try:
        from jarvis.audio import echo_guard
        for n in ("mark_tts_end", "tts_ended", "mark_end"):
            fn = getattr(echo_guard, n, None)
            if callable(fn):
                fn()
                return
    except Exception:
        pass

def kokoro_speak_if_enabled(config: dict | None, text: str, logger: Any | None = None) -> bool:
    provider = str(_get(config, "tts_provider", "piper") or "piper").lower().strip()
    if provider not in {"kokoro", "auto"}:
        return False

    text = str(text or "").strip()
    if not text:
        return True

    home = Path.home()
    kokoro_python = Path(str(_get(config, "kokoro_python", home / ".local/share/jarvis/kokoro/venv/bin/python"))).expanduser()
    if not kokoro_python.exists():
        _event("tts.fallback.used", {"reason": "kokoro_python_missing", "provider": "piper"})
        return False

    voice = str(_get(config, "kokoro_voice", "em_alex") or "em_alex")
    lang = str(_get(config, "kokoro_lang", "e") or "e")
    speed = float(_get(config, "kokoro_speed", 0.95) or 0.95)
    out = home / ".local/share/jarvis/tmp/jarvis_kokoro.wav"
    cli = Path(__file__).with_name("kokoro_cli.py")

    _event("tts.provider.selected", {"provider": "kokoro", "voice": voice, "lang": lang, "speed": speed})

    try:
        _echo_start()
        gen = subprocess.run(
            [str(kokoro_python), str(cli), "--text", text, "--out", str(out), "--voice", voice, "--lang", lang, "--speed", str(speed)],
            text=True,
            capture_output=True,
            timeout=120,
        )
        if gen.returncode != 0:
            _event("tts.fallback.used", {"reason": "kokoro_generation_failed", "stderr": gen.stderr[-500:], "provider": "piper"})
            if logger:
                logger.warning("Kokoro falló; usando Piper")
            return False

        subprocess.run(["aplay", str(out)], check=False)
        _event("tts.kokoro.generated", {"voice": voice, "lang": lang, "speed": speed, "wav": str(out), "text": text})
        if logger:
            logger.info(f"TTS provider usado: kokoro | voice={voice}")
        return True
    except Exception as e:
        _event("tts.fallback.used", {"reason": str(e), "provider": "piper"})
        if logger:
            logger.warning(f"Kokoro falló; usando Piper: {e}")
        return False
    finally:
        _echo_end()

# ---------------------------------------------------------------------------
# v4.0.3.2 Kokoro TTS Cache SAFE FIX
# ---------------------------------------------------------------------------
try:
    import hashlib as _jv4032_hashlib
    import shutil as _jv4032_shutil
    import subprocess as _jv4032_subprocess
    from pathlib import Path as _Jv4032Path

    if "kokoro_speak_if_enabled" in globals() and not getattr(kokoro_speak_if_enabled, "_jv4032_cache_wrapped", False):
        _jv4032_original_kokoro_speak = kokoro_speak_if_enabled

        def _jv4032_cfg(config, key, default=None):
            try:
                a = config.get("assistant", {}) if isinstance(config.get("assistant", {}), dict) else {}
                if key in a:
                    return a.get(key)
                return config.get(key, default)
            except Exception:
                return default

        def _jv4032_event(topic, payload):
            try:
                from jarvis.bus.event_bus import EventBus
                EventBus().publish(topic, payload, source="tts_cache")
            except Exception:
                pass

        def _jv4032_echo_start():
            try:
                from jarvis.audio import echo_guard
                for n in ("mark_tts_start", "tts_started", "mark_start"):
                    fn = getattr(echo_guard, n, None)
                    if callable(fn):
                        fn()
                        return
            except Exception:
                pass

        def _jv4032_echo_end():
            try:
                from jarvis.audio import echo_guard
                for n in ("mark_tts_end", "tts_ended", "mark_end"):
                    fn = getattr(echo_guard, n, None)
                    if callable(fn):
                        fn()
                        return
            except Exception:
                pass

        def _jv4032_cache_path(config, text):
            voice = str(_jv4032_cfg(config, "kokoro_voice", "em_alex") or "em_alex")
            lang = str(_jv4032_cfg(config, "kokoro_lang", "e") or "e")
            speed = str(_jv4032_cfg(config, "kokoro_speed", 0.95) or 0.95)
            key = _jv4032_hashlib.sha256(f"{voice}|{lang}|{speed}|{text}".encode("utf-8")).hexdigest()[:32]
            cache_dir = _Jv4032Path.home() / ".local/share/jarvis/tts_cache/kokoro"
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir / f"{key}.wav"

        def kokoro_speak_if_enabled(config, text, logger=None):
            provider = str(_jv4032_cfg(config or {}, "tts_provider", "piper") or "piper").lower().strip()
            if provider not in {"kokoro", "auto"}:
                return False
            text = str(text or "").strip()
            if not text:
                return True

            cache_file = _jv4032_cache_path(config or {}, text)
            if cache_file.exists() and cache_file.stat().st_size > 1000:
                _jv4032_event("tts.cache.hit", {"wav": str(cache_file), "text": text})
                try:
                    _jv4032_echo_start()
                    _jv4032_subprocess.run(["aplay", str(cache_file)], check=False)
                    if logger:
                        logger.info("TTS provider usado: kokoro-cache")
                    return True
                finally:
                    _jv4032_echo_end()

            _jv4032_event("tts.cache.miss", {"wav": str(cache_file), "text": text})
            ok = _jv4032_original_kokoro_speak(config, text, logger=logger)
            if ok:
                try:
                    tmp = _Jv4032Path.home() / ".local/share/jarvis/tmp/jarvis_kokoro.wav"
                    if tmp.exists() and tmp.stat().st_size > 1000:
                        _jv4032_shutil.copy2(tmp, cache_file)
                        _jv4032_event("tts.cache.saved", {"wav": str(cache_file), "text": text})
                except Exception:
                    pass
            return ok

        kokoro_speak_if_enabled._jv4032_cache_wrapped = True
except Exception:
    pass

# >>> JARVIS_V4034_KOKORO_APLAY_PAD_ALL
# Intercepta aplay dentro de Kokoro para que TODO WAV tenga silencio inicial,
# incluyendo /home/angel/.local/share/jarvis/tmp/jarvis_kokoro.wav cuando NO viene del cache.
def _jarvis_v4034_patch_aplay_padding() -> None:
    try:
        import os as _os
        import subprocess as _subprocess
        from pathlib import Path as _Path
        try:
            from jarvis.audio.wav_pad import make_padded_wav as _jarvis_v4034_make_padded_wav
        except Exception:
            _jarvis_v4034_make_padded_wav = None

        if getattr(_subprocess.run, "_jarvis_v4034_padded", False):
            return

        def _jarvis_v4034_pad_cmd(cmd):
            if _jarvis_v4034_make_padded_wav is None:
                return cmd
            try:
                if isinstance(cmd, (list, tuple)) and cmd:
                    exe = _Path(str(cmd[0])).name
                    if exe != "aplay":
                        return cmd
                    new_cmd = list(cmd)
                    for i, part in enumerate(new_cmd):
                        s = str(part)
                        if s.lower().endswith(".wav"):
                            p = _Path(s).expanduser()
                            if p.exists():
                                new_cmd[i] = str(_jarvis_v4034_make_padded_wav(p))
                                # Silenciar aplay si no estaba silenciado.
                                if "-q" not in new_cmd:
                                    new_cmd.insert(1, "-q")
                                return new_cmd
                    return cmd
            except Exception:
                return cmd
            return cmd

        _orig_run = _subprocess.run
        _orig_call = getattr(_subprocess, "call", None)
        _orig_check_call = getattr(_subprocess, "check_call", None)
        _orig_popen = getattr(_subprocess, "Popen", None)

        def _run(cmd, *args, **kwargs):
            return _orig_run(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
        _run._jarvis_v4034_padded = True
        _subprocess.run = _run

        if _orig_call is not None:
            def _call(cmd, *args, **kwargs):
                return _orig_call(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.call = _call

        if _orig_check_call is not None:
            def _check_call(cmd, *args, **kwargs):
                return _orig_check_call(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.check_call = _check_call

        if _orig_popen is not None:
            def _popen(cmd, *args, **kwargs):
                return _orig_popen(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.Popen = _popen
    except Exception:
        pass

_jarvis_v4034_patch_aplay_padding()
# <<< JARVIS_V4034_KOKORO_APLAY_PAD_ALL

# >>> JARVIS_V405_KOKORO_HOT_BRIDGE_WRAPPER
# Wrapper Kokoro Hot Server: intenta usar proceso persistente antes del Kokoro viejo.
try:
    import os as _jarvis_v405_os
    from jarvis.audio import kokoro_hot_client as _jarvis_v405_hot
except Exception:
    _jarvis_v405_hot = None

def _jarvis_v405_extract_text(args, kwargs):
    for key in ("text", "message", "sentence", "prompt"):
        value = kwargs.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for value in args:
        if isinstance(value, str) and value.strip():
            return value
    return ""

def _jarvis_v405_extract_voice(kwargs):
    return str(kwargs.get("voice") or kwargs.get("voice_id") or kwargs.get("kokoro_voice") or _jarvis_v405_os.environ.get("JARVIS_KOKORO_VOICE") or "em_alex")

def _jarvis_v405_extract_speed(kwargs):
    return str(kwargs.get("speed") or kwargs.get("rate") or kwargs.get("kokoro_speed") or _jarvis_v405_os.environ.get("JARVIS_KOKORO_SPEED") or "0.95")

def _jarvis_v405_extract_lang(kwargs):
    return str(kwargs.get("lang") or kwargs.get("lang_code") or kwargs.get("kokoro_lang") or _jarvis_v405_os.environ.get("JARVIS_KOKORO_LANG") or "e")

def _jarvis_v405_should_hot(text: str) -> bool:
    if _jarvis_v405_hot is None:
        return False
    if _jarvis_v405_os.environ.get("JARVIS_KOKORO_HOT_DISABLE", "0").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    return bool(str(text or "").strip())

for _jarvis_v405_name in ("speak", "say", "tts", "synthesize", "synthesize_to_wav", "synthesize_to_file", "generate_wav", "generate", "kokoro_tts"):
    try:
        _jarvis_v405_original = globals().get(_jarvis_v405_name)
        if _jarvis_v405_original is None or getattr(_jarvis_v405_original, "_jarvis_v405_hot_wrapped", False):
            continue

        def _jarvis_v405_make_wrapper(_orig):
            def _wrapper(*args, **kwargs):
                text = _jarvis_v405_extract_text(args, kwargs)
                if _jarvis_v405_should_hot(text):
                    ok = _jarvis_v405_hot.synthesize_play_cache(
                        text,
                        voice=_jarvis_v405_extract_voice(kwargs),
                        speed=_jarvis_v405_extract_speed(kwargs),
                        lang=_jarvis_v405_extract_lang(kwargs),
                    )
                    if ok:
                        return True
                return _orig(*args, **kwargs)
            _wrapper._jarvis_v405_hot_wrapped = True
            return _wrapper

        globals()[_jarvis_v405_name] = _jarvis_v405_make_wrapper(_jarvis_v405_original)
    except Exception:
        pass
# <<< JARVIS_V405_KOKORO_HOT_BRIDGE_WRAPPER

# >>> JARVIS_V4053_WIRE_HOT_RUNTIME_BRIDGE
# Conecta Kokoro Hot Server al flujo real, no solo a comandos kokoro-hot-test.
# Envuelve funciones de módulo y métodos de clases tipo KokoroBridge/KokoroTTS.
def _jarvis_v4053_wire_hot_runtime() -> None:
    try:
        import os as _os
        import inspect as _inspect
        from pathlib import Path as _Path
        from functools import wraps as _wraps
        try:
            from jarvis.audio import kokoro_hot_client as _hot
        except Exception:
            _hot = None
        if _hot is None:
            return
        if _os.environ.get("JARVIS_KOKORO_HOT_DISABLE", "0").strip().lower() in {"1", "true", "yes", "on"}:
            return

        _SPEAK_NAMES = {
            "speak", "say", "tts", "kokoro_tts", "play", "play_text", "speak_text",
            "synthesize_and_play", "generate_and_play", "run_tts",
        }
        _GEN_NAMES = {
            "synthesize", "synthesise", "synthesize_to_wav", "synthesize_to_file",
            "generate", "generate_wav", "generate_to_file", "make_wav", "text_to_wav",
        }
        _ALL_NAMES = _SPEAK_NAMES | _GEN_NAMES

        def _text_from(args, kwargs):
            for key in ("text", "message", "sentence", "prompt", "content"):
                value = kwargs.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # Saltar self implícito si existe. Buscar la primera cadena que no parezca ruta WAV.
            for value in args:
                if isinstance(value, str) and value.strip():
                    s = value.strip()
                    if not s.lower().endswith((".wav", ".mp3", ".ogg")):
                        return s
            return ""

        def _output_from(args, kwargs):
            for key in ("output", "output_path", "path", "wav_path", "out", "out_path", "filename", "file"):
                value = kwargs.get(key)
                if isinstance(value, (str, _Path)) and str(value).strip():
                    s = str(value).strip()
                    if s.lower().endswith(".wav"):
                        return _Path(s).expanduser()
            # Buscar una ruta .wav en argumentos posicionales.
            for value in args:
                if isinstance(value, (str, _Path)) and str(value).strip().lower().endswith(".wav"):
                    return _Path(str(value).strip()).expanduser()
            try:
                return _Path("~/.local/share/jarvis/tmp/jarvis_kokoro.wav").expanduser()
            except Exception:
                return None

        def _attr_from_self(args, names):
            if not args:
                return None
            obj = args[0]
            for name in names:
                try:
                    value = getattr(obj, name, None)
                    if value is not None:
                        return value
                except Exception:
                    pass
            # Algunos objetos guardan config dict.
            for holder in ("config", "settings", "cfg"):
                try:
                    cfg = getattr(obj, holder, None)
                    if isinstance(cfg, dict):
                        for name in names:
                            if name in cfg:
                                return cfg[name]
                except Exception:
                    pass
            return None

        def _voice(args, kwargs):
            return str(
                kwargs.get("voice") or kwargs.get("voice_id") or kwargs.get("kokoro_voice")
                or _attr_from_self(args, ("voice", "voice_id", "kokoro_voice"))
                or _os.environ.get("JARVIS_KOKORO_VOICE") or "em_alex"
            )

        def _speed(args, kwargs):
            return str(
                kwargs.get("speed") or kwargs.get("rate") or kwargs.get("kokoro_speed")
                or _attr_from_self(args, ("speed", "rate", "kokoro_speed"))
                or _os.environ.get("JARVIS_KOKORO_SPEED") or "0.95"
            )

        def _lang(args, kwargs):
            return str(
                kwargs.get("lang") or kwargs.get("lang_code") or kwargs.get("kokoro_lang")
                or _attr_from_self(args, ("lang", "lang_code", "kokoro_lang"))
                or _os.environ.get("JARVIS_KOKORO_LANG") or "e"
            )

        def _save_cache(path, text, voice, speed):
            try:
                from jarvis.audio import tts_cache as _cache
                p = _Path(path).expanduser()
                if p.exists() and p.stat().st_size > 44:
                    _cache.save_from_file(p, text, voice, speed)
            except Exception:
                pass

        def _play_path(path):
            try:
                from jarvis.audio.wav_pad import play_wav_padded as _play
                return bool(_play(path, quiet=True))
            except Exception:
                try:
                    import subprocess as _subprocess
                    _subprocess.run(["aplay", "-q", str(path)], check=False)
                    return True
                except Exception:
                    return False

        def _wrap_callable(orig, fname):
            if getattr(orig, "_jarvis_v4053_hot_wrapped", False):
                return orig
            @_wraps(orig)
            def _wrapped(*args, **kwargs):
                text = _text_from(args, kwargs)
                if not text:
                    return orig(*args, **kwargs)
                voice = _voice(args, kwargs)
                speed = _speed(args, kwargs)
                lang = _lang(args, kwargs)
                lname = str(fname or "").lower()
                try:
                    # Para funciones que claramente hablan/reproducen: generar + reproducir.
                    if lname in _SPEAK_NAMES or "speak" in lname or "say" in lname or "play" in lname or lname == "tts":
                        ok = _hot.synthesize_play_cache(text, voice=voice, speed=speed, lang=lang)
                        if ok:
                            return True
                    # Para funciones que generan WAV: generar a la ruta esperada y regresar esa ruta.
                    if lname in _GEN_NAMES or "synth" in lname or "generate" in lname or "wav" in lname:
                        out = _output_from(args, kwargs)
                        if out is not None:
                            res = _hot.request_synthesis(text, out, voice=voice, speed=speed, lang=lang)
                            if res and out.exists() and out.stat().st_size > 44:
                                _save_cache(out, text, voice, speed)
                                # Si el nombre parecía hablar también, reproduce.
                                if "play" in lname or "speak" in lname or "say" in lname:
                                    _play_path(out)
                                    return True
                                return str(out)
                except Exception:
                    pass
                return orig(*args, **kwargs)
            _wrapped._jarvis_v4053_hot_wrapped = True
            return _wrapped

        # Envolver funciones de módulo.
        g = globals()
        for name in list(_ALL_NAMES):
            try:
                obj = g.get(name)
                if callable(obj):
                    g[name] = _wrap_callable(obj, name)
            except Exception:
                pass

        # Envolver métodos de clases con nombre Kokoro*/ *TTS* / *Bridge*.
        for cname, cls in list(g.items()):
            try:
                if not isinstance(cls, type):
                    continue
                low_cname = str(cname).lower()
                if "kokoro" not in low_cname and "tts" not in low_cname and "bridge" not in low_cname:
                    continue
                for name, member in list(vars(cls).items()):
                    if name.startswith("__"):
                        continue
                    low = name.lower()
                    if low not in _ALL_NAMES and not any(token in low for token in ("speak", "say", "play", "synth", "generate", "wav", "tts")):
                        continue
                    # staticmethod/classmethod necesitan unwrap especial.
                    if isinstance(member, staticmethod):
                        fn = member.__func__
                        setattr(cls, name, staticmethod(_wrap_callable(fn, low)))
                    elif isinstance(member, classmethod):
                        fn = member.__func__
                        setattr(cls, name, classmethod(_wrap_callable(fn, low)))
                    elif callable(member):
                        setattr(cls, name, _wrap_callable(member, low))
            except Exception:
                pass

    except Exception:
        pass

_jarvis_v4053_wire_hot_runtime()
# <<< JARVIS_V4053_WIRE_HOT_RUNTIME_BRIDGE

# === JARVIS_V4055_WRAP_KOKORO_BRIDGE_HOT_BEGIN ===
# Jarvis v4.0.5.5
# Envuelve kokoro_speak_if_enabled() para intentar Kokoro Hot Server antes
# de caer al Kokoro viejo por subprocess.

import os as _jarvis_v4055_os
import inspect as _jarvis_v4055_inspect
from pathlib import Path as _jarvis_v4055_Path

def _jarvis_v4055_get_cfg_value(cfg, key, default=None):
    try:
        if isinstance(cfg, dict):
            if key in cfg:
                return cfg.get(key, default)
            assistant = cfg.get("assistant") or {}
            if isinstance(assistant, dict) and key in assistant:
                return assistant.get(key, default)
    except Exception:
        pass

    try:
        if hasattr(cfg, key):
            return getattr(cfg, key)
    except Exception:
        pass

    try:
        assistant = getattr(cfg, "assistant", None)
        if assistant is not None:
            if isinstance(assistant, dict):
                return assistant.get(key, default)
            if hasattr(assistant, key):
                return getattr(assistant, key)
    except Exception:
        pass

    return default

def _jarvis_v4055_extract_text(args, kwargs):
    for k in ("text", "message", "response"):
        v = kwargs.get(k)
        if isinstance(v, str) and v.strip():
            return v
    for a in args:
        if isinstance(a, str) and a.strip():
            return a
    return ""

def _jarvis_v4055_extract_cfg(args, kwargs):
    for k in ("config", "cfg", "settings"):
        if k in kwargs and kwargs[k] is not None:
            return kwargs[k]
    for a in args:
        if not isinstance(a, str) and not (hasattr(a, "info") and hasattr(a, "warning")):
            return a
    return None

def _jarvis_v4055_extract_logger(args, kwargs):
    lg = kwargs.get("logger")
    if lg is not None:
        return lg
    for a in args:
        if hasattr(a, "info") and hasattr(a, "warning"):
            return a
    try:
        import logging
        return logging.getLogger("jarvis")
    except Exception:
        return None

def _jarvis_v4055_log(logger, level, msg, *vals):
    try:
        if logger is not None and hasattr(logger, level):
            getattr(logger, level)(msg, *vals)
    except Exception:
        pass

def _jarvis_v4055_publish(topic, summary, payload=None):
    try:
        from jarvis.bus.event_bus import EventBus
        EventBus().publish(
            topic,
            payload or {"summary": summary},
            source="kokoro_bridge_hot_wrapper",
        )
    except Exception:
        pass

def _jarvis_v4055_hot_speak(text, cfg=None, logger=None):
    if _jarvis_v4055_os.environ.get("JARVIS_KOKORO_HOT_DISABLE", "").strip() == "1":
        return False

    text = str(text or "").strip()
    if not text:
        return False

    voice = (
        _jarvis_v4055_get_cfg_value(cfg, "kokoro_voice", None)
        or _jarvis_v4055_get_cfg_value(cfg, "voice", None)
        or _jarvis_v4055_os.environ.get("JARVIS_KOKORO_VOICE")
        or "em_alex"
    )

    lang = (
        _jarvis_v4055_get_cfg_value(cfg, "kokoro_lang", None)
        or _jarvis_v4055_get_cfg_value(cfg, "lang", None)
        or _jarvis_v4055_os.environ.get("JARVIS_KOKORO_LANG")
        or "e"
    )

    speed_raw = (
        _jarvis_v4055_get_cfg_value(cfg, "kokoro_speed", None)
        or _jarvis_v4055_get_cfg_value(cfg, "speed", None)
        or _jarvis_v4055_os.environ.get("JARVIS_KOKORO_SPEED")
        or 0.95
    )
    try:
        speed = float(speed_raw)
    except Exception:
        speed = 0.95

    try:
        from jarvis.audio import kokoro_hot_client as _hot

        candidates = [
            "speak",
            "speak_hot",
            "hot_speak",
            "kokoro_hot_speak",
            "synthesize_and_play",
            "synthesize_play",
            "synth_and_play",
            "say",
        ]

        for name in candidates:
            fn = getattr(_hot, name, None)
            if not callable(fn):
                continue

            try:
                sig = _jarvis_v4055_inspect.signature(fn)
                params = sig.parameters
                call_kwargs = {}

                if "text" in params:
                    call_kwargs["text"] = text
                if "voice" in params:
                    call_kwargs["voice"] = voice
                if "lang" in params:
                    call_kwargs["lang"] = lang
                if "speed" in params:
                    call_kwargs["speed"] = speed
                if "logger" in params:
                    call_kwargs["logger"] = logger

                if call_kwargs:
                    result = fn(**call_kwargs)
                else:
                    try:
                        result = fn(text, voice, speed, lang)
                    except TypeError:
                        try:
                            result = fn(text, voice=voice, speed=speed, lang=lang)
                        except TypeError:
                            result = fn(text)

                if result:
                    _jarvis_v4055_log(logger, "info", "TTS provider usado: kokoro-hot | voice=%s", voice)
                    _jarvis_v4055_publish(
                        "tts.hot.generated",
                        text[:160],
                        {
                            "text": text,
                            "voice": voice,
                            "speed": speed,
                            "lang": lang,
                            "client_function": name,
                            "wrapper": "v4.0.5.5",
                        },
                    )
                    return True
            except Exception as e:
                _jarvis_v4055_log(logger, "warning", "Kokoro hot candidato falló: %s: %s", name, e)
                continue

        # Fallback especial: si el cliente ofrece synthesize_to_file, sintetizar y reproducir.
        synth = getattr(_hot, "synthesize_to_file", None)
        play = getattr(_hot, "play_wav", None)

        if callable(synth):
            out = _jarvis_v4055_Path.home() / ".local/share/jarvis/tmp/jarvis_kokoro.wav"
            out.parent.mkdir(parents=True, exist_ok=True)

            try:
                result = synth(text=text, out_path=str(out), voice=voice, speed=speed, lang=lang)
            except TypeError:
                try:
                    result = synth(text, str(out), voice, speed, lang)
                except TypeError:
                    result = synth(text)

            path = None
            if isinstance(result, (str, _jarvis_v4055_Path)):
                path = _jarvis_v4055_Path(result)
            elif isinstance(result, dict):
                p = result.get("path") or result.get("out") or result.get("file")
                if p:
                    path = _jarvis_v4055_Path(p)
            elif out.exists():
                path = out

            if path and path.exists():
                if callable(play):
                    try:
                        play(path)
                    except TypeError:
                        play(str(path))
                else:
                    import subprocess as _subprocess
                    _subprocess.run(["aplay", "-q", str(path)], check=False)

                _jarvis_v4055_log(logger, "info", "TTS provider usado: kokoro-hot | voice=%s", voice)
                _jarvis_v4055_publish(
                    "tts.hot.generated",
                    text[:160],
                    {
                        "text": text,
                        "voice": voice,
                        "speed": speed,
                        "lang": lang,
                        "client_function": "synthesize_to_file",
                        "wrapper": "v4.0.5.5",
                    },
                )
                return True

        _jarvis_v4055_publish(
            "tts.hot.failed",
            text[:160],
            {
                "reason": "no compatible callable found in kokoro_hot_client",
                "wrapper": "v4.0.5.5",
            },
        )
        return False

    except Exception as e:
        _jarvis_v4055_log(logger, "warning", "Kokoro hot wrapper falló: %s", e)
        _jarvis_v4055_publish(
            "tts.hot.failed",
            text[:160],
            {"reason": str(e), "wrapper": "v4.0.5.5"},
        )
        return False

try:
    _jarvis_v4055_original_kokoro_speak_if_enabled = kokoro_speak_if_enabled

    def kokoro_speak_if_enabled(*args, **kwargs):
        text = _jarvis_v4055_extract_text(args, kwargs)
        cfg = _jarvis_v4055_extract_cfg(args, kwargs)
        logger = _jarvis_v4055_extract_logger(args, kwargs)

        try:
            if _jarvis_v4055_hot_speak(text, cfg=cfg, logger=logger):
                return True
        except Exception as e:
            _jarvis_v4055_log(logger, "warning", "Kokoro hot no pudo responder, usando fallback: %s", e)

        return _jarvis_v4055_original_kokoro_speak_if_enabled(*args, **kwargs)

    kokoro_speak_if_enabled.__jarvis_hot_wrapper__ = "v4.0.5.5"
    kokoro_speak_if_enabled.__wrapped__ = _jarvis_v4055_original_kokoro_speak_if_enabled

except Exception:
    pass

# === JARVIS_V4055_WRAP_KOKORO_BRIDGE_HOT_END ===

# === JARVIS_V4062_LATENCY_TTS_BEGIN ===
# Jarvis v4.0.6.2 latency profiler: wrapper no destructivo para kokoro_speak_if_enabled.
try:
    import time as _jarvis_v4062_time
    import logging as _jarvis_v4062_logging

    def _jarvis_v4062_emit_latency(topic, summary, payload=None):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload or {}, source="latency_profiler")
        except Exception:
            pass

    if "kokoro_speak_if_enabled" in globals() and callable(kokoro_speak_if_enabled):
        if not getattr(kokoro_speak_if_enabled, "__jarvis_v4062_latency__", False):
            _jarvis_v4062_original_kokoro_speak_if_enabled = kokoro_speak_if_enabled

            def kokoro_speak_if_enabled(*args, **kwargs):
                logger = _jarvis_v4062_logging.getLogger("jarvis")
                text = ""
                try:
                    for k in ("text", "message", "response"):
                        if isinstance(kwargs.get(k), str):
                            text = kwargs[k]
                            break
                    if not text:
                        for a in args:
                            if isinstance(a, str):
                                text = a
                                break
                except Exception:
                    text = ""

                start = _jarvis_v4062_time.monotonic()
                logger.info("LATENCY tts.start provider=kokoro_or_hot text_len=%s", len(str(text or "")))

                ok = False
                err = None
                try:
                    result = _jarvis_v4062_original_kokoro_speak_if_enabled(*args, **kwargs)
                    ok = bool(result)
                    return result
                except Exception as exc:
                    err = str(exc)
                    raise
                finally:
                    elapsed_ms = int((_jarvis_v4062_time.monotonic() - start) * 1000)
                    logger.info(
                        "LATENCY tts.done elapsed_ms=%s ok=%s error=%s",
                        elapsed_ms,
                        ok,
                        err or "",
                    )
                    _jarvis_v4062_emit_latency(
                        "latency.tts",
                        f"{elapsed_ms} ms",
                        {
                            "elapsed_ms": elapsed_ms,
                            "ok": ok,
                            "error": err,
                            "text_len": len(str(text or "")),
                        },
                    )

            kokoro_speak_if_enabled.__jarvis_v4062_latency__ = True
            kokoro_speak_if_enabled.__wrapped__ = _jarvis_v4062_original_kokoro_speak_if_enabled

except Exception:
    pass
# === JARVIS_V4062_LATENCY_TTS_END ===

# === JARVIS_V4070_ALEX_MAX_BRIDGE_BEGIN ===
# Jarvis v4.0.7.0 — Alex/Kokoro Max bridge tuning.
# Fuerza speed configurable antes de que el wrapper Kokoro Hot lea config.
try:
    import os as _jarvis_v4070_os
    import logging as _jarvis_v4070_logging

    _jarvis_v4070_original_kokoro_speak_if_enabled = kokoro_speak_if_enabled

    def _jarvis_v4070_target_speed():
        raw = _jarvis_v4070_os.environ.get("JARVIS_KOKORO_SPEED", "1.15")
        try:
            return float(raw)
        except Exception:
            return 1.15

    def _jarvis_v4070_patch_cfg(cfg, speed):
        if cfg is None:
            return

        try:
            if isinstance(cfg, dict):
                cfg["kokoro_speed"] = speed
                assistant = cfg.setdefault("assistant", {})
                if isinstance(assistant, dict):
                    assistant["kokoro_speed"] = speed
                tts = cfg.setdefault("tts", {})
                if isinstance(tts, dict):
                    tts["kokoro_speed"] = speed
                return
        except Exception:
            pass

        for attr in ("kokoro_speed", "speed"):
            try:
                if hasattr(cfg, attr):
                    setattr(cfg, attr, speed)
            except Exception:
                pass

        try:
            assistant = getattr(cfg, "assistant", None)
            if isinstance(assistant, dict):
                assistant["kokoro_speed"] = speed
            elif assistant is not None and hasattr(assistant, "kokoro_speed"):
                setattr(assistant, "kokoro_speed", speed)
        except Exception:
            pass

    def _jarvis_v4070_find_cfg(args, kwargs):
        for key in ("config", "cfg", "settings"):
            if kwargs.get(key) is not None:
                return kwargs.get(key)
        for arg in args:
            if not isinstance(arg, str) and not (hasattr(arg, "info") and hasattr(arg, "warning")):
                return arg
        return None

    def kokoro_speak_if_enabled(*args, **kwargs):
        speed = _jarvis_v4070_target_speed()
        cfg = _jarvis_v4070_find_cfg(args, kwargs)
        _jarvis_v4070_patch_cfg(cfg, speed)
        try:
            _jarvis_v4070_logging.getLogger("jarvis").info("Alex/Kokoro speed objetivo: %.2f", speed)
        except Exception:
            pass
        return _jarvis_v4070_original_kokoro_speak_if_enabled(*args, **kwargs)

    kokoro_speak_if_enabled.__jarvis_v4070_alex_max__ = True
    kokoro_speak_if_enabled.__wrapped__ = _jarvis_v4070_original_kokoro_speak_if_enabled

except Exception:
    pass
# === JARVIS_V4070_ALEX_MAX_BRIDGE_END ===

# === JARVIS_V4086_SOFT_VOICE_COMPACT_BEGIN ===
# Jarvis v4.0.8.6
# Compresión de voz más suave:
# - solo compacta respuestas MUY largas
# - intenta conservar 1-2 oraciones completas
# - evita cortar agresivamente respuestas medianas
try:
    import os as _jarvis_v4086_os
    import re as _jarvis_v4086_re
    import logging as _jarvis_v4086_logging

    _jarvis_v4086_prev_kokoro_speak_if_enabled = kokoro_speak_if_enabled

    def _jarvis_v4086_int_env(name, default):
        raw = _jarvis_v4086_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _jarvis_v4086_extract_text(args, kwargs):
        for key in ("text", "message", "response"):
            val = kwargs.get(key)
            if isinstance(val, str):
                return key, val
        for i, val in enumerate(args):
            if isinstance(val, str):
                return i, val
        return None, ""

    def _jarvis_v4086_soft_compact(text):
        original = str(text or "").strip()
        if not original:
            return original

        t = original
        t = _jarvis_v4086_re.sub(r"^\s*Groq no respondió; uso el modelo local\.\s*", "", t, flags=_jarvis_v4086_re.IGNORECASE)
        t = _jarvis_v4086_re.sub(r"\s+", " ", t).strip()

        only_if_gt = _jarvis_v4086_int_env("JARVIS_VOICE_COMPACT_ONLY_IF_GT", 280)
        max_chars = _jarvis_v4086_int_env("JARVIS_VOICE_MAX_CHARS", 220)

        if len(t) <= only_if_gt:
            return t

        parts = [p.strip() for p in _jarvis_v4086_re.split(r"(?<=[.!?])\s+", t) if p.strip()]
        if not parts:
            return t

        # Tomar 1 o 2 oraciones completas si caben.
        acc = ""
        for p in parts[:3]:
            candidate = (acc + " " + p).strip() if acc else p
            if len(candidate) <= max_chars:
                acc = candidate
            else:
                break

        if acc and len(acc) >= 40:
            return acc

        # Fallback suave.
        cut = t[:max_chars].rsplit(" ", 1)[0].strip()
        if len(cut) < 40:
            cut = t[:max_chars].strip()
        if not cut.endswith((".", "?", "!", "…")):
            cut += "…"
        return cut

    def kokoro_speak_if_enabled(*args, **kwargs):
        logger = _jarvis_v4086_logging.getLogger("jarvis")
        target, original = _jarvis_v4086_extract_text(args, kwargs)
        compact = _jarvis_v4086_soft_compact(original)
        changed = compact != original and bool(original)

        if changed:
            try:
                logger.info(
                    "VOICE_COMPACT_SOFT original_len=%s compact_len=%s compact=%r",
                    len(original),
                    len(compact),
                    compact,
                )
            except Exception:
                pass
            try:
                from jarvis.bus.event_bus import EventBus
                EventBus().publish(
                    "tts.voice.compacted",
                    {
                        "original_len": len(original),
                        "compact_len": len(compact),
                        "compact": compact,
                        "mode": "soft_v4086",
                    },
                    source="voice_compact_v4086",
                )
            except Exception:
                pass

            if isinstance(target, str):
                kwargs[target] = compact
            elif isinstance(target, int):
                args = list(args)
                args[target] = compact
                args = tuple(args)

        return _jarvis_v4086_prev_kokoro_speak_if_enabled(*args, **kwargs)

    kokoro_speak_if_enabled.__jarvis_v4086_soft_voice__ = True
    kokoro_speak_if_enabled.__wrapped__ = _jarvis_v4086_prev_kokoro_speak_if_enabled

except Exception:
    pass
# === JARVIS_V4086_SOFT_VOICE_COMPACT_END ===
