from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jarvis.audio.speaker import Speaker
from jarvis.tts.base import TTSProvider
from jarvis.utils.paths import ensure_dir


class PiperTTS(TTSProvider):
    name = 'piper'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts.piper')
        self.speaker = Speaker(config)
        self.piper_cfg = config.get('tts', {}).get('piper', {})
        self.binary = self.piper_cfg.get('binary', 'piper')
        self.model_path = Path(self.piper_cfg.get('model_path', '~/.local/share/jarvis/voices/piper/es_ES-davefx-medium.onnx')).expanduser()
        self.config_path = Path(self.piper_cfg.get('config_path', str(self.model_path) + '.json')).expanduser()
        self.volume = float(self.piper_cfg.get('volume', 1.0))

    def available(self) -> bool:
        return bool(shutil.which(self.binary)) and self.model_path.exists()

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        binary = shutil.which(self.binary)
        if not binary:
            raise RuntimeError('Piper no está instalado o no está en PATH.')
        if not self.model_path.exists():
            raise RuntimeError(f'No existe modelo Piper: {self.model_path}')
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        cmd = [binary, '--model', str(self.model_path), '--output_file', str(out)]
        if self.config_path.exists():
            cmd.extend(['--config', str(self.config_path)])
        speaker = self.piper_cfg.get('speaker')
        if speaker not in (None, '', 'null'):
            cmd.extend(['--speaker', str(speaker)])
        proc = subprocess.run(cmd, input=text, text=True, capture_output=True, timeout=90)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'Piper falló.')
        return out

    def speak(self, text: str) -> None:
        temp = ensure_dir(self.config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))
        out = temp / 'jarvis_piper.wav'
        wav = self.synthesize(text, out)
        self.speaker.play_wav(wav, volume=self.volume)

# ---------------------------------------------------------------------------
# v4.0.2.3 Kokoro TTS auto-hook: wraps this TTS module safely
# ---------------------------------------------------------------------------
try:
    import functools as _jv4023_functools
    from pathlib import Path as _Jv4023Path

    def _jv4023_load_config():
        try:
            import yaml
            cfg_path = _Jv4023Path.home() / ".config/jarvis/config.yaml"
            if cfg_path.exists():
                data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _jv4023_get_config(obj=None):
        for attr in ("config", "settings", "cfg"):
            try:
                value = getattr(obj, attr, None)
                if isinstance(value, dict):
                    return value
            except Exception:
                pass
        return _jv4023_load_config()

    def _jv4023_get_logger(obj=None):
        try:
            logger = getattr(obj, "logger", None)
            if logger:
                return logger
        except Exception:
            pass
        try:
            import logging
            return logging.getLogger("jarvis")
        except Exception:
            return None

    def _jv4023_extract_text(args, kwargs):
        for key in ("text", "message", "response", "content"):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                return value

        for value in args:
            if isinstance(value, str) and value.strip():
                return value

        return ""

    def _jv4023_wrap(original):
        if getattr(original, "_jv4023_kokoro_wrapped", False):
            return original

        @_jv4023_functools.wraps(original)
        def wrapped(*args, **kwargs):
            # Method: args[0] likely self. Function: first arg may be text.
            obj = args[0] if args and not isinstance(args[0], str) else None
            real_args = args[1:] if obj is not None else args
            text = _jv4023_extract_text(real_args, kwargs)

            if text:
                try:
                    from jarvis.audio.kokoro_bridge import kokoro_speak_if_enabled
                    if kokoro_speak_if_enabled(
                        _jv4023_get_config(obj),
                        text,
                        logger=_jv4023_get_logger(obj),
                    ):
                        return "kokoro"
                except Exception as exc:
                    try:
                        logger = _jv4023_get_logger(obj)
                        if logger:
                            logger.warning(f"Kokoro auto-hook falló; usando TTS original: {exc}")
                    except Exception:
                        pass

            return original(*args, **kwargs)

        wrapped._jv4023_kokoro_wrapped = True
        return wrapped

    def _jv4023_should_wrap_name(name):
        n = str(name or "").lower()
        if n.startswith("_"):
            return False
        tokens = ("speak", "say", "voice", "tts", "synth", "piper", "audio", "play")
        return any(t in n for t in tokens)

    def _jv4023_install():
        # Module-level functions.
        for _name, _fn in list(globals().items()):
            if callable(_fn) and _jv4023_should_wrap_name(_name):
                if not isinstance(_fn, type) and not getattr(_fn, "_jv4023_kokoro_wrapped", False):
                    try:
                        globals()[_name] = _jv4023_wrap(_fn)
                    except Exception:
                        pass

        # Class methods.
        for _class_name, _cls in list(globals().items()):
            if not isinstance(_cls, type):
                continue

            for _method_name, _method in list(_cls.__dict__.items()):
                if not _jv4023_should_wrap_name(_method_name):
                    continue

                # Skip properties/static data.
                target = _method
                is_static = isinstance(_method, staticmethod)
                is_class = isinstance(_method, classmethod)

                if is_static or is_class:
                    target = _method.__func__

                if not callable(target) or getattr(target, "_jv4023_kokoro_wrapped", False):
                    continue

                try:
                    wrapped = _jv4023_wrap(target)
                    if is_static:
                        wrapped = staticmethod(wrapped)
                    elif is_class:
                        wrapped = classmethod(wrapped)
                    setattr(_cls, _method_name, wrapped)
                except Exception:
                    pass

    _jv4023_install()

except Exception:
    # Nunca romper Jarvis por el hook.
    pass

# === JARVIS_V4067_PIPER_WAV_APLAY_BEGIN ===
# Jarvis v4.0.6.7
# Fuerza Piper por ruta CLI -> WAV -> aplay para evitar PortAudio/ALSA paInvalidSampleRate.
# Si falla, cae al método Piper original.
try:
    import os as _jarvis_v4067_os
    import re as _jarvis_v4067_re
    import shlex as _jarvis_v4067_shlex
    import shutil as _jarvis_v4067_shutil
    import subprocess as _jarvis_v4067_subprocess
    import tempfile as _jarvis_v4067_tempfile
    import time as _jarvis_v4067_time
    import logging as _jarvis_v4067_logging
    from pathlib import Path as _jarvis_v4067_Path

    def _jarvis_v4067_get_cfg_value(cfg, key, default=None):
        try:
            if isinstance(cfg, dict):
                if key in cfg:
                    return cfg.get(key, default)
                for section_name in ("assistant", "tts", "audio", "piper"):
                    section = cfg.get(section_name)
                    if isinstance(section, dict) and key in section:
                        return section.get(key, default)
        except Exception:
            pass

        try:
            if hasattr(cfg, key):
                return getattr(cfg, key)
        except Exception:
            pass

        try:
            for section_name in ("assistant", "tts", "audio", "piper"):
                section = getattr(cfg, section_name, None)
                if isinstance(section, dict) and key in section:
                    return section.get(key, default)
                if section is not None and hasattr(section, key):
                    return getattr(section, key)
        except Exception:
            pass

        return default

    def _jarvis_v4067_extract_text(args, kwargs):
        for key in ("text", "message", "response", "sentence"):
            val = kwargs.get(key)
            if isinstance(val, str) and val.strip():
                return val
        for arg in args:
            if isinstance(arg, str) and arg.strip():
                return arg
        return ""

    def _jarvis_v4067_extract_cfg(self_obj, args, kwargs):
        for key in ("config", "cfg", "settings"):
            if kwargs.get(key) is not None:
                return kwargs.get(key)
        for arg in args:
            if not isinstance(arg, str) and not hasattr(arg, "info"):
                return arg
        try:
            for attr in ("config", "cfg", "settings"):
                if hasattr(self_obj, attr):
                    val = getattr(self_obj, attr)
                    if val is not None:
                        return val
        except Exception:
            pass
        return None

    def _jarvis_v4067_logger(kwargs=None):
        try:
            if kwargs and kwargs.get("logger") is not None:
                return kwargs.get("logger")
        except Exception:
            pass
        return _jarvis_v4067_logging.getLogger("jarvis")

    def _jarvis_v4067_find_piper_bin(cfg=None, self_obj=None):
        env = _jarvis_v4067_os.environ.get("JARVIS_PIPER_BIN")
        if env:
            return env

        for key in ("piper_bin", "piper_binary", "piper_path", "tts_piper_bin", "binary"):
            val = _jarvis_v4067_get_cfg_value(cfg, key)
            if val:
                return str(val)
            try:
                if self_obj is not None and hasattr(self_obj, key):
                    val = getattr(self_obj, key)
                    if val:
                        return str(val)
            except Exception:
                pass

        found = _jarvis_v4067_shutil.which("piper")
        if found:
            return found

        candidates = [
            _jarvis_v4067_Path.home() / ".local/bin/piper",
            _jarvis_v4067_Path.home() / ".local/share/jarvis/piper/piper",
            _jarvis_v4067_Path.home() / ".local/share/jarvis/venv/bin/piper",
            _jarvis_v4067_Path("/usr/bin/piper"),
            _jarvis_v4067_Path("/usr/local/bin/piper"),
        ]
        for p in candidates:
            if p.exists() and _jarvis_v4067_os.access(str(p), _jarvis_v4067_os.X_OK):
                return str(p)
        return None

    def _jarvis_v4067_find_model(cfg=None, self_obj=None):
        env = _jarvis_v4067_os.environ.get("JARVIS_PIPER_MODEL")
        if env:
            return env

        keys = (
            "piper_model",
            "piper_voice",
            "piper_voice_path",
            "voice_model",
            "model_path",
            "model",
            "voice",
        )

        for key in keys:
            val = _jarvis_v4067_get_cfg_value(cfg, key)
            if val and str(val).endswith(".onnx"):
                return str(_jarvis_v4067_Path(str(val)).expanduser())
            try:
                if self_obj is not None and hasattr(self_obj, key):
                    val = getattr(self_obj, key)
                    if val and str(val).endswith(".onnx"):
                        return str(_jarvis_v4067_Path(str(val)).expanduser())
            except Exception:
                pass

        # Intento por configuración textual.
        try:
            cfg_path = _jarvis_v4067_Path.home() / ".config/jarvis/config.yaml"
            if cfg_path.exists():
                text = cfg_path.read_text(encoding="utf-8", errors="replace")
                for m in _jarvis_v4067_re.finditer(r"(?im)^\s*(?:piper_model|piper_voice|piper_voice_path|model_path)\s*:\s*(.+?)\s*$", text):
                    candidate = m.group(1).strip().strip("'\"")
                    if candidate.endswith(".onnx"):
                        return str(_jarvis_v4067_Path(candidate).expanduser())
        except Exception:
            pass

        roots = [
            _jarvis_v4067_Path.home() / ".local/share/jarvis",
            _jarvis_v4067_Path.home() / ".local/share/piper",
            _jarvis_v4067_Path.home() / ".config/jarvis",
        ]

        found = []
        for root in roots:
            try:
                if root.exists():
                    found.extend(root.rglob("*.onnx"))
            except Exception:
                pass

        # Excluir modelo de wake word y preferir voces Piper.
        filtered = []
        for p in found:
            name = str(p).lower()
            if "openwakeword" in name or "hey_jarvis" in name or "wake" in name:
                continue
            if "piper" in name or "voice" in name or "es_" in name or "spanish" in name:
                filtered.append(p)

        if filtered:
            return str(filtered[0])
        if found:
            return str(found[0])

        return None

    def _jarvis_v4067_aplay(path, logger=None):
        logger = logger or _jarvis_v4067_logging.getLogger("jarvis")
        wav = str(path)

        # Reusar wav_pad si existe para no comerse letras.
        try:
            from jarvis.audio.wav_pad import play_wav_padded
            ok = bool(play_wav_padded(wav, quiet=True))
            if ok:
                return True
        except Exception:
            pass

        cmds = [
            ["aplay", "-q", wav],
            ["paplay", wav],
            ["pw-play", wav],
        ]
        for cmd in cmds:
            if _jarvis_v4067_shutil.which(cmd[0]):
                try:
                    proc = _jarvis_v4067_subprocess.run(cmd, text=True, capture_output=True, timeout=30)
                    if proc.returncode == 0:
                        return True
                    try:
                        logger.warning("Piper WAV playback falló cmd=%s stderr=%s", cmd, (proc.stderr or "").strip()[:300])
                    except Exception:
                        pass
                except Exception as exc:
                    try:
                        logger.warning("Piper WAV playback excepción cmd=%s exc=%s", cmd, exc)
                    except Exception:
                        pass
        return False

    def _jarvis_v4067_piper_cli_speak(text, cfg=None, self_obj=None, logger=None):
        logger = logger or _jarvis_v4067_logging.getLogger("jarvis")

        if _jarvis_v4067_os.environ.get("JARVIS_PIPER_WAV_DISABLE", "").strip() == "1":
            return False

        text = str(text or "").strip()
        if not text:
            return False

        piper_bin = _jarvis_v4067_find_piper_bin(cfg, self_obj)
        model = _jarvis_v4067_find_model(cfg, self_obj)

        if not piper_bin or not model:
            try:
                logger.warning("Piper WAV/aplay: no encontré bin/model piper_bin=%s model=%s", piper_bin, model)
            except Exception:
                pass
            return False

        model_path = _jarvis_v4067_Path(model).expanduser()
        if not model_path.exists():
            try:
                logger.warning("Piper WAV/aplay: modelo no existe: %s", model_path)
            except Exception:
                pass
            return False

        tmp_dir = _jarvis_v4067_Path.home() / ".local/share/jarvis/tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out = tmp_dir / f"jarvis_piper_{int(_jarvis_v4067_time.time()*1000)}.wav"

        cmd = [str(piper_bin), "--model", str(model_path), "--output_file", str(out)]

        config_json = _jarvis_v4067_os.environ.get("JARVIS_PIPER_CONFIG")
        if not config_json:
            possible = str(model_path) + ".json"
            if _jarvis_v4067_Path(possible).exists():
                config_json = possible

        if config_json:
            # Algunas versiones de piper no aceptan --config; si falla, se reintenta sin config.
            cmd_with_config = cmd + ["--config", str(config_json)]
        else:
            cmd_with_config = cmd

        timeout = float(_jarvis_v4067_os.environ.get("JARVIS_PIPER_SYNTH_TIMEOUT", "20"))

        for attempt_cmd in (cmd_with_config, cmd):
            try:
                proc = _jarvis_v4067_subprocess.run(
                    attempt_cmd,
                    input=text + "\n",
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                )

                if proc.returncode != 0:
                    try:
                        logger.warning(
                            "Piper CLI falló rc=%s cmd=%s stderr=%s",
                            proc.returncode,
                            _jarvis_v4067_shlex.join(attempt_cmd),
                            (proc.stderr or "").strip()[:500],
                        )
                    except Exception:
                        pass
                    continue

                if not out.exists() or out.stat().st_size <= 44:
                    try:
                        logger.warning("Piper CLI no generó WAV válido: %s", out)
                    except Exception:
                        pass
                    continue

                if _jarvis_v4067_aplay(out, logger=logger):
                    try:
                        logger.info("TTS provider usado: piper-wav-aplay")
                    except Exception:
                        pass

                    try:
                        from jarvis.bus.event_bus import EventBus
                        EventBus().publish(
                            "tts.piper.wav",
                            {
                                "text": text,
                                "model": str(model_path),
                                "path": str(out),
                                "bytes": out.stat().st_size,
                            },
                            source="piper_wav_aplay",
                        )
                    except Exception:
                        pass

                    return True

            except Exception as exc:
                try:
                    logger.warning("Piper CLI excepción cmd=%s exc=%s", _jarvis_v4067_shlex.join(attempt_cmd), exc)
                except Exception:
                    pass

        return False

    def _jarvis_v4067_patch_piper_class():
        cls = globals().get("PiperTTS")
        if cls is None:
            return False

        patched = False
        for method_name in ("speak", "say", "tts"):
            if hasattr(cls, method_name):
                orig = getattr(cls, method_name)
                if callable(orig) and not getattr(orig, "__jarvis_v4067_piper_wav__", False):
                    def _make_wrapper(_orig, _method_name):
                        def _wrapped(self, *args, **kwargs):
                            logger = _jarvis_v4067_logger(kwargs)
                            text = _jarvis_v4067_extract_text(args, kwargs)
                            cfg = _jarvis_v4067_extract_cfg(self, args, kwargs)
                            if _jarvis_v4067_piper_cli_speak(text, cfg=cfg, self_obj=self, logger=logger):
                                return True
                            return _orig(self, *args, **kwargs)
                        _wrapped.__jarvis_v4067_piper_wav__ = True
                        _wrapped.__wrapped__ = _orig
                        return _wrapped

                    setattr(cls, method_name, _make_wrapper(orig, method_name))
                    patched = True
        return patched

    _jarvis_v4067_patch_piper_class()

    # Parchear funciones de módulo si existen.
    for _fn_name in ("speak", "say", "tts", "piper_speak"):
        _fn = globals().get(_fn_name)
        if callable(_fn) and not getattr(_fn, "__jarvis_v4067_piper_wav__", False):
            def _make_module_wrapper(_orig):
                def _wrapped(*args, **kwargs):
                    logger = _jarvis_v4067_logger(kwargs)
                    text = _jarvis_v4067_extract_text(args, kwargs)
                    cfg = _jarvis_v4067_extract_cfg(None, args, kwargs)
                    if _jarvis_v4067_piper_cli_speak(text, cfg=cfg, self_obj=None, logger=logger):
                        return True
                    return _orig(*args, **kwargs)
                _wrapped.__jarvis_v4067_piper_wav__ = True
                _wrapped.__wrapped__ = _orig
                return _wrapped
            globals()[_fn_name] = _make_module_wrapper(_fn)

except Exception:
    pass
# === JARVIS_V4067_PIPER_WAV_APLAY_END ===

# === JARVIS_V4068_PIPER_FAST_CACHE_BEGIN ===
# Jarvis v4.0.6.8
# Piper fast cache path:
# - cachea WAV por texto/modelo/length_scale
# - usa length_scale default 0.82 para hablar más rápido
# - reproduce directo con aplay/paplay/pw-play
# - salta el fallback viejo si puede resolver bin/model
try:
    import os as _jarvis_v4068_os
    import re as _jarvis_v4068_re
    import hashlib as _jarvis_v4068_hashlib
    import shutil as _jarvis_v4068_shutil
    import subprocess as _jarvis_v4068_subprocess
    import time as _jarvis_v4068_time
    import logging as _jarvis_v4068_logging
    from pathlib import Path as _jarvis_v4068_Path

    def _jarvis_v4068_log(logger, level, msg, *args):
        try:
            getattr(logger, level)(msg, *args)
        except Exception:
            pass

    def _jarvis_v4068_publish(topic, payload):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload, source="piper_fast_cache")
        except Exception:
            pass

    def _jarvis_v4068_extract_text(args, kwargs):
        for key in ("text", "message", "response", "sentence"):
            val = kwargs.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        for arg in args:
            if isinstance(arg, str) and arg.strip():
                return arg.strip()
        return ""

    def _jarvis_v4068_extract_cfg(self_obj, args, kwargs):
        for key in ("config", "cfg", "settings"):
            if kwargs.get(key) is not None:
                return kwargs.get(key)
        try:
            for attr in ("config", "cfg", "settings"):
                if hasattr(self_obj, attr):
                    val = getattr(self_obj, attr)
                    if val is not None:
                        return val
        except Exception:
            pass
        for arg in args:
            if not isinstance(arg, str) and not hasattr(arg, "info"):
                return arg
        return None

    def _jarvis_v4068_get_cfg(cfg, key, default=None):
        try:
            if isinstance(cfg, dict):
                if key in cfg:
                    return cfg.get(key, default)
                for section in ("assistant", "tts", "audio", "piper"):
                    val = cfg.get(section)
                    if isinstance(val, dict) and key in val:
                        return val.get(key, default)
        except Exception:
            pass
        try:
            if hasattr(cfg, key):
                return getattr(cfg, key)
        except Exception:
            pass
        return default

    def _jarvis_v4068_find_bin(cfg=None, self_obj=None):
        env = _jarvis_v4068_os.environ.get("JARVIS_PIPER_BIN")
        if env:
            return env

        # Reusar helper v4.0.6.7 si existe.
        fn = globals().get("_jarvis_v4067_find_piper_bin")
        if callable(fn):
            try:
                val = fn(cfg, self_obj)
                if val:
                    return val
            except Exception:
                pass

        for key in ("piper_bin", "piper_binary", "piper_path", "tts_piper_bin"):
            val = _jarvis_v4068_get_cfg(cfg, key)
            if val:
                return str(val)
            try:
                if self_obj is not None and hasattr(self_obj, key):
                    val = getattr(self_obj, key)
                    if val:
                        return str(val)
            except Exception:
                pass

        val = _jarvis_v4068_shutil.which("piper")
        if val:
            return val

        for p in (
            _jarvis_v4068_Path.home() / ".local/bin/piper",
            _jarvis_v4068_Path.home() / ".local/share/jarvis/piper/piper",
            _jarvis_v4068_Path.home() / ".local/share/jarvis/venv/bin/piper",
            _jarvis_v4068_Path("/usr/bin/piper"),
            _jarvis_v4068_Path("/usr/local/bin/piper"),
        ):
            if p.exists():
                return str(p)
        return None

    def _jarvis_v4068_find_model(cfg=None, self_obj=None):
        env = _jarvis_v4068_os.environ.get("JARVIS_PIPER_MODEL")
        if env:
            return env

        fn = globals().get("_jarvis_v4067_find_model")
        if callable(fn):
            try:
                val = fn(cfg, self_obj)
                if val:
                    return val
            except Exception:
                pass

        for key in ("piper_model", "piper_voice_path", "piper_voice", "voice_model", "model_path"):
            val = _jarvis_v4068_get_cfg(cfg, key)
            if val and str(val).endswith(".onnx"):
                return str(_jarvis_v4068_Path(str(val)).expanduser())
            try:
                if self_obj is not None and hasattr(self_obj, key):
                    val = getattr(self_obj, key)
                    if val and str(val).endswith(".onnx"):
                        return str(_jarvis_v4068_Path(str(val)).expanduser())
            except Exception:
                pass

        roots = [
            _jarvis_v4068_Path.home() / ".local/share/jarvis",
            _jarvis_v4068_Path.home() / ".local/share/piper",
            _jarvis_v4068_Path.home() / ".config/jarvis",
        ]
        found = []
        for root in roots:
            try:
                if root.exists():
                    found.extend(root.rglob("*.onnx"))
            except Exception:
                pass

        filtered = []
        for p in found:
            low = str(p).lower()
            if "wake" in low or "hey_jarvis" in low or "openwakeword" in low:
                continue
            filtered.append(p)

        if filtered:
            return str(filtered[0])
        return None

    def _jarvis_v4068_cache_path(text, model, length_scale):
        cache_root = _jarvis_v4068_Path.home() / ".local/share/jarvis/tts_cache/piper_fast"
        cache_root.mkdir(parents=True, exist_ok=True)
        key = _jarvis_v4068_hashlib.sha256(
            (str(model) + "\n" + str(length_scale) + "\n" + str(text)).encode("utf-8")
        ).hexdigest()[:32]
        return cache_root / f"{key}.wav"

    def _jarvis_v4068_play(path, logger):
        start = _jarvis_v4068_time.monotonic()
        for cmd in (["aplay", "-q", str(path)], ["paplay", str(path)], ["pw-play", str(path)]):
            if not _jarvis_v4068_shutil.which(cmd[0]):
                continue
            try:
                proc = _jarvis_v4068_subprocess.run(cmd, text=True, capture_output=True, timeout=30)
                play_ms = int((_jarvis_v4068_time.monotonic() - start) * 1000)
                if proc.returncode == 0:
                    return True, play_ms, cmd[0]
                _jarvis_v4068_log(logger, "warning", "Piper fast playback falló cmd=%s stderr=%s", cmd, (proc.stderr or "")[:300])
            except Exception as exc:
                _jarvis_v4068_log(logger, "warning", "Piper fast playback excepción cmd=%s exc=%s", cmd, exc)
        return False, int((_jarvis_v4068_time.monotonic() - start) * 1000), "none"

    def _jarvis_v4068_synth(text, model, out, piper_bin, length_scale, logger):
        start = _jarvis_v4068_time.monotonic()
        base = [str(piper_bin), "--model", str(model), "--output_file", str(out)]

        # Piper normalmente acepta --length_scale. Si tu binario no lo acepta, reintenta sin él.
        cmd_variants = [
            base + ["--length_scale", str(length_scale)],
            base,
        ]

        # Evitar repetir exactamente el mismo comando si length_scale vacío.
        seen = set()
        for cmd in cmd_variants:
            sig = tuple(cmd)
            if sig in seen:
                continue
            seen.add(sig)
            try:
                proc = _jarvis_v4068_subprocess.run(
                    cmd,
                    input=text + "\n",
                    text=True,
                    capture_output=True,
                    timeout=float(_jarvis_v4068_os.environ.get("JARVIS_PIPER_FAST_SYNTH_TIMEOUT", "15")),
                )
                synth_ms = int((_jarvis_v4068_time.monotonic() - start) * 1000)
                if proc.returncode == 0 and out.exists() and out.stat().st_size > 44:
                    return True, synth_ms, cmd
                _jarvis_v4068_log(logger, "warning", "Piper fast synth falló rc=%s stderr=%s", proc.returncode, (proc.stderr or "")[:300])
            except Exception as exc:
                _jarvis_v4068_log(logger, "warning", "Piper fast synth excepción exc=%s", exc)
        return False, int((_jarvis_v4068_time.monotonic() - start) * 1000), []

    def _jarvis_v4068_piper_fast_speak(text, cfg=None, self_obj=None, logger=None):
        logger = logger or _jarvis_v4068_logging.getLogger("jarvis")

        if _jarvis_v4068_os.environ.get("JARVIS_PIPER_FAST_DISABLE", "").strip() == "1":
            return False

        text = str(text or "").strip()
        if not text:
            return False

        piper_bin = _jarvis_v4068_find_bin(cfg, self_obj)
        model = _jarvis_v4068_find_model(cfg, self_obj)
        if not piper_bin or not model:
            _jarvis_v4068_log(logger, "warning", "Piper fast: no pude resolver bin/model piper_bin=%s model=%s", piper_bin, model)
            return False

        try:
            length_scale = float(_jarvis_v4068_os.environ.get("JARVIS_PIPER_LENGTH_SCALE", "0.82"))
        except Exception:
            length_scale = 0.82

        model_path = _jarvis_v4068_Path(model).expanduser()
        if not model_path.exists():
            _jarvis_v4068_log(logger, "warning", "Piper fast: modelo no existe: %s", model_path)
            return False

        wav = _jarvis_v4068_cache_path(text, model_path, length_scale)
        total_start = _jarvis_v4068_time.monotonic()

        if wav.exists() and wav.stat().st_size > 44:
            ok, play_ms, player = _jarvis_v4068_play(wav, logger)
            total_ms = int((_jarvis_v4068_time.monotonic() - total_start) * 1000)
            if ok:
                _jarvis_v4068_log(logger, "info", "TTS provider usado: piper-fast-cache | total_ms=%s play_ms=%s player=%s", total_ms, play_ms, player)
                _jarvis_v4068_publish("tts.piper.fast.cache_hit", {"text": text, "path": str(wav), "total_ms": total_ms, "play_ms": play_ms})
                return True
            return False

        _jarvis_v4068_publish("tts.piper.fast.cache_miss", {"text": text})
        ok, synth_ms, used_cmd = _jarvis_v4068_synth(text, model_path, wav, piper_bin, length_scale, logger)
        if not ok:
            try:
                if wav.exists():
                    wav.unlink()
            except Exception:
                pass
            return False

        ok, play_ms, player = _jarvis_v4068_play(wav, logger)
        total_ms = int((_jarvis_v4068_time.monotonic() - total_start) * 1000)
        if ok:
            _jarvis_v4068_log(
                logger,
                "info",
                "TTS provider usado: piper-fast | total_ms=%s synth_ms=%s play_ms=%s length_scale=%s player=%s",
                total_ms,
                synth_ms,
                play_ms,
                length_scale,
                player,
            )
            _jarvis_v4068_publish(
                "tts.piper.fast.generated",
                {
                    "text": text,
                    "path": str(wav),
                    "bytes": wav.stat().st_size if wav.exists() else None,
                    "total_ms": total_ms,
                    "synth_ms": synth_ms,
                    "play_ms": play_ms,
                    "length_scale": length_scale,
                    "player": player,
                },
            )
            return True

        return False

    def _jarvis_v4068_patch_class():
        cls = globals().get("PiperTTS")
        if cls is None:
            return False

        patched = False
        for name in ("speak", "say", "tts"):
            orig = getattr(cls, name, None)
            if callable(orig) and not getattr(orig, "__jarvis_v4068_piper_fast__", False):
                def _make_wrapper(_orig):
                    def _wrapped(self, *args, **kwargs):
                        logger = _jarvis_v4068_logging.getLogger("jarvis")
                        text = _jarvis_v4068_extract_text(args, kwargs)
                        cfg = _jarvis_v4068_extract_cfg(self, args, kwargs)
                        if _jarvis_v4068_piper_fast_speak(text, cfg=cfg, self_obj=self, logger=logger):
                            return True
                        return _orig(self, *args, **kwargs)
                    _wrapped.__jarvis_v4068_piper_fast__ = True
                    _wrapped.__wrapped__ = _orig
                    return _wrapped

                setattr(cls, name, _make_wrapper(orig))
                patched = True

        return patched

    _jarvis_v4068_patch_class()

    for _name in ("speak", "say", "tts", "piper_speak"):
        _orig = globals().get(_name)
        if callable(_orig) and not getattr(_orig, "__jarvis_v4068_piper_fast__", False):
            def _make_fn_wrapper(_orig):
                def _wrapped(*args, **kwargs):
                    logger = _jarvis_v4068_logging.getLogger("jarvis")
                    text = _jarvis_v4068_extract_text(args, kwargs)
                    cfg = _jarvis_v4068_extract_cfg(None, args, kwargs)
                    if _jarvis_v4068_piper_fast_speak(text, cfg=cfg, self_obj=None, logger=logger):
                        return True
                    return _orig(*args, **kwargs)
                _wrapped.__jarvis_v4068_piper_fast__ = True
                _wrapped.__wrapped__ = _orig
                return _wrapped
            globals()[_name] = _make_fn_wrapper(_orig)

except Exception:
    pass
# === JARVIS_V4068_PIPER_FAST_CACHE_END ===
