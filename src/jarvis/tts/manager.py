from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis.tts.coqui_tts import CoquiTTS
from jarvis.tts.elevenlabs_tts import ElevenLabsTTS
from jarvis.tts.openai_tts import OpenAITTS
from jarvis.tts.piper_tts import PiperTTS
from jarvis.tts.system_tts import SystemTTS
from jarvis.utils.paths import ensure_dir
from jarvis.utils.text import split_for_tts


class TTSManager:
    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.tts')
        self.providers = {
            'piper': PiperTTS(config, self.logger),
            'coqui': CoquiTTS(config, self.logger),
            'elevenlabs': ElevenLabsTTS(config, self.logger),
            'openai': OpenAITTS(config, self.logger),
            'system': SystemTTS(config, self.logger),
            'espeak': SystemTTS(config, self.logger),
        }
        self.debug = bool(config.get('assistant', {}).get('debug', False))

    def _provider_order(self) -> list[str]:
        tts = self.config.get('tts', {})
        primary = tts.get('provider', 'piper')
        order = [primary]
        for candidate in ('piper', tts.get('fallback', 'espeak'), 'system'):
            if candidate and candidate not in order:
                order.append(candidate)
        return order

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        chunks = split_for_tts(text)
        for chunk in chunks:
            self._speak_chunk(chunk)
        if not self.debug:
            self._cleanup_temp_audio()

    def _speak_chunk(self, text: str) -> None:
        errors: list[str] = []
        for name in self._provider_order():
            provider = self.providers.get(name)
            if provider is None:
                continue
            try:
                self.logger.info('TTS provider usado: %s', provider.name)
                provider.speak(text)
                return
            except Exception as exc:
                msg = f'{name}: {exc}'
                errors.append(msg)
                self.logger.warning('Falló TTS %s: %s', name, exc)
        raise RuntimeError('Fallaron todos los TTS: ' + '; '.join(errors))

    def test(self) -> None:
        self.speak('Hola, soy Jarvis. La voz funciona correctamente.')

    def _cleanup_temp_audio(self) -> None:
        temp = ensure_dir(self.config.get('paths', {}).get('temp_dir', '~/.local/share/jarvis/tmp'))
        for pattern in ('jarvis_*.wav', 'jarvis_*.mp3'):
            for file in Path(temp).glob(pattern):
                try:
                    file.unlink(missing_ok=True)
                except Exception:
                    pass

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

