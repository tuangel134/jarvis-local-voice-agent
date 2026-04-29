from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from jarvis.audio.echo_guard import EchoGuard

from jarvis.audio.echo_guard import should_discard_audio_frame, should_suppress_detection, reset_openwakeword_model

from jarvis.stt.base import STTProvider
import os
from jarvis.audio.post_question_listen import consume_direct_listen_if_pending
try:
    from jarvis.audio.conversation_state import should_accept_wake_score
except Exception:
    def should_accept_wake_score(score):
        return True
try:
    from jarvis.audio.conversation_state import should_accept_wake_score
except Exception:
    def should_accept_wake_score(score):
        return True

def _jarvis_echo_guard_should_suppress(local_vars) -> bool:
    score = None
    for name in ("score", "wakeword_score", "confidence", "prediction_score", "model_score"):
        if name in local_vars:
            try:
                score = float(local_vars[name])
                break
            except Exception:
                score = None
                break

    try:
        from jarvis.audio.followup_hint import should_bypass_echo_guard
    except Exception:
        should_bypass_echo_guard = None

    if should_bypass_echo_guard is not None:
        try:
            if should_bypass_echo_guard():
                try:
                    bypass_limit = float(os.getenv("JARVIS_FOLLOWUP_ECHO_BYPASS_MAX_SCORE", "0.32"))
                except Exception:
                    bypass_limit = 0.32
                if score is not None:
                    return score >= bypass_limit
                return True
        except Exception:
            pass

    try:
        threshold = float(os.getenv("JARVIS_TTS_ECHO_GUARD_MIN_SCORE", "0.34"))
    except Exception:
        threshold = 0.34

    if score is not None:
        return score >= threshold
    return True

    for name in ("score", "wakeword_score", "confidence", "prediction_score", "model_score"):
        if name in local_vars:
            try:
                return float(local_vars[name]) >= threshold
            except Exception:
                break
    return True


    for name in ("score", "wakeword_score", "confidence", "prediction_score", "model_score"):
        if name in local_vars:
            try:
                return float(local_vars[name]) >= threshold
            except Exception:
                break
    return True


@dataclass
class WakeResult:
    detected: bool
    text: str = ""
    command_after_wake: str = ""

class WakeWordDetector:
    """
    Wake word real con openWakeWord.

    Compatible con openWakeWord 0.4.x:
      Model(wakeword_model_paths=[...])

    No usa Whisper para detectar "hey jarvis".
    """

    def __init__(self, config: dict[str, Any], stt: STTProvider, logger: logging.Logger | None = None):
        self.config = config
        self.stt = stt
        self.logger = logger or logging.getLogger("jarvis.wakeword")

        audio_cfg = config.get("audio", {})
        assistant_cfg = config.get("assistant", {})

        self.input_device = audio_cfg.get("input_device", "default")
        self.capture_sample_rate = int(audio_cfg.get("sample_rate", 16000))
        self.channels = 1

        self.oww_sample_rate = 16000
        self.frame_seconds = 0.08
        self.capture_block_size = int(self.capture_sample_rate * self.frame_seconds)

        self.threshold = float(assistant_cfg.get("openwakeword_threshold", 0.14))
        self.debug = bool(assistant_cfg.get("debug", False))

        self.model = None
        self.model_path = self._find_model_path()
        self._load_model()

    def _find_model_path(self) -> Path:
        import openwakeword

        base = Path(openwakeword.__file__).parent
        model_path = base / "resources" / "models" / "hey_jarvis_v0.1.onnx"

        if not model_path.exists():
            raise FileNotFoundError(f"No encontré el modelo: {model_path}")

        return model_path

    def _load_model(self) -> None:
        from openwakeword.model import Model

        self.logger.info("Cargando openWakeWord desde: %s", self.model_path)

        # API correcta para openWakeWord 0.4.x.
        self.model = Model(
            wakeword_model_paths=[str(self.model_path)],
        )

        self.logger.info(
            "openWakeWord listo | modelo=%s | threshold=%.2f | input_device=%r | sample_rate=%s",
            self.model_path.name,
            self.threshold,
            self.input_device,
            self.capture_sample_rate,
        )

    def wait(self, should_continue) -> WakeResult:
        if self.model is None:
            self._load_model()

        self.logger.info("Escuchando wake word con openWakeWord: hey jarvis")

        try:
            stream_device = None if self.input_device in (None, "", "default") else self.input_device
            with sd.InputStream(
                samplerate=self.capture_sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.capture_block_size,
                device=stream_device,
            ) as stream:
                while should_continue():
                    try:
                        audio, overflowed = stream.read(self.capture_block_size)

                        if overflowed:
                            self.logger.warning("Audio overflow en wake word")

                        # TTS Echo Guard: durante el cooldown fuerte leemos y descartamos frames
                        # para evitar que el eco de Piper/aplay llegue a openWakeWord.
                        if should_discard_audio_frame():
                            if self.debug:
                                self.logger.debug("TTS Echo Guard: descartando frame de micrófono por cooldown")
                            continue

                        frame = self._prepare_frame(audio)
                        prediction = self.model.predict(frame)

                        detected, best_name, best_score = self._is_detected(prediction)

                        if self.debug and best_score >= 0.05:
                            self.logger.info(
                                "openWakeWord score: modelo=%s score=%.3f",
                                best_name,
                                best_score,
                            )

                        if _jarvis_echo_guard_should_suppress(locals()) and (detected and should_suppress_detection(best_score, self.threshold)):
                            self.logger.info(
                                "Wake word suprimida por TTS Echo Guard: modelo=%s score=%.3f",
                                best_name,
                                best_score,
                            )
                            reset_openwakeword_model(self.model, self.logger)
                            continue


                        if detected and not should_accept_wake_score(best_score):
                            self.logger.info(
                                "Wake word suprimida por MEDIA_GUARD: modelo=%s score=%.3f",
                                best_name,
                                best_score,
                            )
                            reset_openwakeword_model(self.model, self.logger)
                            continue

                        if detected:
                            self.logger.info(
                                "Wake word detectada por openWakeWord: modelo=%s score=%.3f",
                                best_name,
                                best_score,
                            )

                            return WakeResult(
                                detected=True,
                                text=f"openWakeWord:{best_name}:{best_score:.3f}",
                                command_after_wake="",
                            )

                    except Exception as exc:
                        self.logger.error("Error en loop openWakeWord: %s", exc, exc_info=True)
                        time.sleep(1.0)

        except Exception as exc:
            self.logger.error("Error abriendo micrófono para openWakeWord: %s", exc, exc_info=True)
            time.sleep(1.0)

        return WakeResult(False)

    def listen_once(self) -> WakeResult:
        return self.wait(lambda: True)

    def _prepare_frame(self, audio: np.ndarray) -> np.ndarray:
        audio = np.asarray(audio)

        if audio.ndim > 1:
            audio = audio[:, 0]

        audio = audio.astype(np.int16)

        if self.capture_sample_rate != self.oww_sample_rate:
            if self.capture_sample_rate == 16000:
                audio = resample_poly(audio, 1, 3)
            elif self.capture_sample_rate == 16000:
                audio = resample_poly(audio, 160, 441)
            else:
                audio = resample_poly(audio, self.oww_sample_rate, self.capture_sample_rate)

        return np.asarray(audio, dtype=np.int16)

    def _is_detected(self, prediction: Any) -> tuple[bool, str, float]:
        if not isinstance(prediction, dict) or not prediction:
            return False, "", 0.0

        best_name = ""
        best_score = 0.0

        for name, score in prediction.items():
            try:
                s = float(score)
            except Exception:
                continue

            if s > best_score:
                best_name = str(name)
                best_score = s

        return best_score >= self.threshold, best_name, best_score

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

# === JARVIS_V4075_ECHO_GUARD_SOFT_RELEASE_BEGIN ===
# Jarvis v4.0.7.5
# TTS Echo Guard soft release.
# Objetivo: no dejar que Echo Guard bloquee llamadas reales varios segundos después de terminar TTS.
try:
    import os as _jarvis_v4075_os
    import time as _jarvis_v4075_time
    import logging as _jarvis_v4075_logging

    _JARVIS_V4075_FIRST_SUPPRESS_AT = None

    def _jarvis_v4075_guard_seconds():
        try:
            return float(_jarvis_v4075_os.environ.get("JARVIS_TTS_ECHO_GUARD_SECONDS", "0.85"))
        except Exception:
            return 0.85

    def _jarvis_v4075_guard_max_seconds():
        try:
            return float(_jarvis_v4075_os.environ.get("JARVIS_TTS_ECHO_GUARD_MAX_SECONDS", "1.15"))
        except Exception:
            return 1.15

    def _jarvis_v4075_should_allow_after_soft_release():
        global _JARVIS_V4075_FIRST_SUPPRESS_AT

        now = _jarvis_v4075_time.monotonic()
        if _JARVIS_V4075_FIRST_SUPPRESS_AT is None:
            _JARVIS_V4075_FIRST_SUPPRESS_AT = now
            return False

        elapsed = now - _JARVIS_V4075_FIRST_SUPPRESS_AT
        if elapsed >= _jarvis_v4075_guard_max_seconds():
            try:
                _jarvis_v4075_logging.getLogger("jarvis").info(
                    "TTS Echo Guard soft release: elapsed=%.2fs max=%.2fs",
                    elapsed,
                    _jarvis_v4075_guard_max_seconds(),
                )
            except Exception:
                pass
            _JARVIS_V4075_FIRST_SUPPRESS_AT = None
            return True

        return False

    def _jarvis_v4075_reset_soft_release_timer():
        global _JARVIS_V4075_FIRST_SUPPRESS_AT
        _JARVIS_V4075_FIRST_SUPPRESS_AT = None

    # Si existen funciones de echo guard, envolverlas de forma segura.
    for _name, _fn in list(globals().items()):
        _lname = str(_name).lower()
        if callable(_fn) and ("echo" in _lname and "guard" in _lname) and not getattr(_fn, "__jarvis_v4075_echo_guard__", False):
            def _make_wrapper(orig, fname):
                def _wrapped(*args, **kwargs):
                    result = orig(*args, **kwargs)
                    # Si la función dice "bloquear/suprimir", liberamos después del máximo corto.
                    if bool(result):
                        if _jarvis_v4075_should_allow_after_soft_release():
                            try:
                                _jarvis_v4075_logging.getLogger("jarvis").info(
                                    "TTS Echo Guard liberado por soft release en %s",
                                    fname,
                                )
                            except Exception:
                                pass
                            return False
                    else:
                        _jarvis_v4075_reset_soft_release_timer()
                    return result
                _wrapped.__jarvis_v4075_echo_guard__ = True
                _wrapped.__wrapped__ = orig
                return _wrapped
            globals()[_name] = _make_wrapper(_fn, _name)

except Exception:
    pass
# === JARVIS_V4075_ECHO_GUARD_SOFT_RELEASE_END ===

# === JARVIS_V4094_WAKEWORD_XRUN_GUARD_BEGIN ===
# Jarvis v4.0.9.4
# Mitiga xrun / broken pipe en wait():
# - si PortAudio/ALSA revienta, no deja al daemon en crash loop
# - duerme un poco y devuelve False para que el loop vuelva a abrir el stream
try:
    import time as _jarvis_v4094_time
    import logging as _jarvis_v4094_logging

    def _jarvis_v4094_is_xrun_error(exc: Exception) -> bool:
        text = str(exc or "")
        low = text.lower()
        return (
            "broken pipe" in low
            or "unanticipated host error" in low
            or "xrun" in low
            or "portaudioerror" in low
            or "alsa error -32" in low
        )

    def _jarvis_v4094_wrap_wait(orig):
        def _wrapped(self, *args, **kwargs):
            logger = _jarvis_v4094_logging.getLogger("jarvis")
            try:
                return orig(self, *args, **kwargs)
            except Exception as exc:
                if _jarvis_v4094_is_xrun_error(exc):
                    try:
                        logger.warning("WAKEWORD_XRUN_GUARD recuperando de error ALSA/PortAudio: %s", exc)
                    except Exception:
                        pass
                    try:
                        from jarvis.bus.event_bus import EventBus
                        EventBus().publish(
                            "audio.capture.xrun",
                            {"error": str(exc)},
                            source="wakeword_xrun_guard_v4094",
                        )
                    except Exception:
                        pass
                    _jarvis_v4094_time.sleep(0.25)
                    return False
                raise
        _wrapped.__jarvis_v4094_xrun__ = True
        _wrapped.__wrapped__ = orig
        return _wrapped

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "wait"):
            _meth = getattr(_obj, "wait", None)
            if callable(_meth) and not getattr(_meth, "__jarvis_v4094_xrun__", False):
                setattr(_obj, "wait", _jarvis_v4094_wrap_wait(_meth))

except Exception:
    pass
# === JARVIS_V4094_WAKEWORD_XRUN_GUARD_END ===

# === JARVIS_V4095_WAKEWORD_SAMPLE_RATE_RETRY_BEGIN ===
# Jarvis v4.0.9.5
# openWakeWord: usar sample rate propio y reintentar con rates válidos si el dispositivo rechaza uno.
try:
    import os as _jarvis_v4095_os
    import logging as _jarvis_v4095_logging

    def _jarvis_v4095_int_env(name: str, default: int) -> int:
        raw = _jarvis_v4095_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _jarvis_v4095_is_invalid_rate_error(exc: Exception) -> bool:
        low = str(exc or "").lower()
        return "invalid sample rate" in low or "paerrorcode -9997" in low or "painvalidsamplerate" in low

    def _jarvis_v4095_build_rate_candidates(instance):
        vals = []
        for v in [
            _jarvis_v4095_int_env("JARVIS_WAKEWORD_SAMPLE_RATE", 48000),
            getattr(instance, "capture_sample_rate", None),
            48000,
            44100,
            32000,
            16000,
        ]:
            try:
                iv = int(v)
            except Exception:
                continue
            if iv > 0 and iv not in vals:
                vals.append(iv)
        return vals

    def _jarvis_v4095_patch_class(_cls):
        # __init__ hook
        _orig_init = getattr(_cls, "__init__", None)
        if callable(_orig_init) and not getattr(_orig_init, "__jarvis_v4095_sr__", False):
            def __init__(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                logger = _jarvis_v4095_logging.getLogger("jarvis")
                try:
                    # Wake word usa su propio SR, separado del recorder/STT
                    forced_sr = _jarvis_v4095_int_env("JARVIS_WAKEWORD_SAMPLE_RATE", 48000)
                    forced_block = _jarvis_v4095_int_env("JARVIS_WAKEWORD_BLOCKSIZE", 2048)
                    if hasattr(self, "capture_sample_rate"):
                        self.capture_sample_rate = forced_sr
                    if hasattr(self, "sample_rate"):
                        # Solo tocar sample_rate si parece ser del wakeword; no dependemos de esto.
                        pass
                    if hasattr(self, "blocksize"):
                        self.blocksize = forced_block
                    logger.info(
                        "WAKEWORD_FORCE capture_sample_rate=%s blocksize=%s input_device=%s",
                        getattr(self, "capture_sample_rate", None),
                        getattr(self, "blocksize", None),
                        getattr(self, "input_device", None),
                    )
                except Exception as exc:
                    try:
                        logger.warning("WAKEWORD_FORCE no pudo ajustar SR/blocksize: %s", exc)
                    except Exception:
                        pass
            __init__.__jarvis_v4095_sr__ = True
            __init__.__wrapped__ = _orig_init
            _cls.__init__ = __init__

        # wait hook with retry
        _orig_wait = getattr(_cls, "wait", None)
        if callable(_orig_wait) and not getattr(_orig_wait, "__jarvis_v4095_retry__", False):
            def wait(self, *args, **kwargs):
                if consume_direct_listen_if_pending():
                    try:
                        logging.getLogger('jarvis').info('POST_QUESTION_LISTEN bypass activo; escucha directa sin wake word')
                    except Exception:
                        pass
                    return True
                logger = _jarvis_v4095_logging.getLogger("jarvis")
                rates = _jarvis_v4095_build_rate_candidates(self)
                last_exc = None
                for idx, rate in enumerate(rates, start=1):
                    try:
                        self.capture_sample_rate = rate
                    except Exception:
                        pass
                    try:
                        logger.info("WAKEWORD_SR_RETRY intento=%s/%s rate=%s", idx, len(rates), rate)
                    except Exception:
                        pass
                    try:
                        return _orig_wait(self, *args, **kwargs)
                    except Exception as exc:
                        last_exc = exc
                        if _jarvis_v4095_is_invalid_rate_error(exc):
                            try:
                                logger.warning("WAKEWORD_SR_RETRY rate=%s rechazado: %s", rate, exc)
                            except Exception:
                                pass
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc
                return False
            wait.__jarvis_v4095_retry__ = True
            wait.__wrapped__ = _orig_wait
            _cls.wait = wait

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "wait"):
            _jarvis_v4095_patch_class(_obj)

except Exception:
    pass
# === JARVIS_V4095_WAKEWORD_SAMPLE_RATE_RETRY_END ===

# === JARVIS_V4096_FORCE_WAKE_RUNTIME_BEGIN ===
# Jarvis v4.0.9.6
# Fuerza threshold/sample_rate del wakeword en runtime, independientemente de config vieja.
try:
    import os as _jarvis_v4096_os
    import logging as _jarvis_v4096_logging

    def _jarvis_v4096_float_env(name: str, default: float) -> float:
        raw = _jarvis_v4096_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return float(default)
        try:
            return float(raw)
        except Exception:
            return float(default)

    def _jarvis_v4096_int_env(name: str, default: int) -> int:
        raw = _jarvis_v4096_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _jarvis_v4096_patch_class(_cls):
        _orig_init = getattr(_cls, "__init__", None)
        if callable(_orig_init) and not getattr(_orig_init, "__jarvis_v4096_force__", False):
            def __init__(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                logger = _jarvis_v4096_logging.getLogger("jarvis")
                try:
                    forced_thr = _jarvis_v4096_float_env("JARVIS_WAKE_THRESHOLD", 0.14)
                    forced_sr = _jarvis_v4096_int_env("JARVIS_WAKEWORD_SAMPLE_RATE", 48000)
                    forced_block = _jarvis_v4096_int_env("JARVIS_WAKEWORD_BLOCKSIZE", 2048)

                    if hasattr(self, "threshold"):
                        self.threshold = forced_thr
                    if hasattr(self, "wake_threshold"):
                        self.wake_threshold = forced_thr
                    if hasattr(self, "capture_sample_rate"):
                        self.capture_sample_rate = forced_sr
                    if hasattr(self, "sample_rate"):
                        # no sobreescribimos sample_rate del modelo si no existe; solo si ya está.
                        try:
                            self.sample_rate = forced_sr
                        except Exception:
                            pass
                    if hasattr(self, "blocksize"):
                        self.blocksize = forced_block

                    logger.info(
                        "WAKE_RUNTIME_FORCE threshold=%s capture_sample_rate=%s blocksize=%s",
                        getattr(self, "threshold", None),
                        getattr(self, "capture_sample_rate", None),
                        getattr(self, "blocksize", None),
                    )
                except Exception as exc:
                    try:
                        logger.warning("WAKE_RUNTIME_FORCE no pudo forzar runtime: %s", exc)
                    except Exception:
                        pass

            __init__.__jarvis_v4096_force__ = True
            __init__.__wrapped__ = _orig_init
            _cls.__init__ = __init__

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "wait"):
            _jarvis_v4096_patch_class(_obj)

except Exception:
    pass
# === JARVIS_V4096_FORCE_WAKE_RUNTIME_END ===

# === JARVIS_V4097_DISABLE_ECHO_GUARD_RUNTIME_BEGIN ===
# Jarvis v4.0.9.7
# Desactiva por completo el TTS Echo Guard en runtime.
try:
    import logging as _jarvis_v4097_logging

    def _jarvis_v4097_false_guard(*args, **kwargs):
        return False

    _jarvis_v4097_logger = _jarvis_v4097_logging.getLogger("jarvis")

    for _name, _obj in list(globals().items()):
        low = str(_name).lower()
        if callable(_obj):
            if "echo" in low and "guard" in low:
                globals()[_name] = _jarvis_v4097_false_guard
                try:
                    _jarvis_v4097_logger.info("ECHO_GUARD runtime desactivado hook=%s", _name)
                except Exception:
                    pass

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type):
            for _meth_name in dir(_obj):
                low = _meth_name.lower()
                if "echo" in low and "guard" in low:
                    _meth = getattr(_obj, _meth_name, None)
                    if callable(_meth):
                        try:
                            setattr(_obj, _meth_name, staticmethod(_jarvis_v4097_false_guard))
                            _jarvis_v4097_logger.info("ECHO_GUARD runtime desactivado metodo=%s.%s", _name, _meth_name)
                        except Exception:
                            pass

except Exception:
    pass
# === JARVIS_V4097_DISABLE_ECHO_GUARD_RUNTIME_END ===

# === JARVIS_V4097D_RESTORE_ECHO_GUARD_RUNTIME_BEGIN ===
# Restaura las funciones reales de echo_guard después de un parche previo
# que las deshabilitó globalmente en runtime.
try:
    import importlib as _jarvis_v4097d_importlib

    _jarvis_v4097d_eg = _jarvis_v4097d_importlib.import_module("jarvis.audio.echo_guard")
    should_discard_audio_frame = _jarvis_v4097d_eg.should_discard_audio_frame
    should_suppress_detection = _jarvis_v4097d_eg.should_suppress_detection
    reset_openwakeword_model = _jarvis_v4097d_eg.reset_openwakeword_model
    EchoGuard = getattr(_jarvis_v4097d_eg, "EchoGuard", EchoGuard)
except Exception:
    pass
# === JARVIS_V4097D_RESTORE_ECHO_GUARD_RUNTIME_END ===

# === JARVIS_V4125_WAKEWORD_DEVICE_RESOLVER_V2_BEGIN ===
# Jarvis v4.1.2.5
# Corrige el resolver de input_device para wake word.
# Orden: preferred válido -> default input válido -> primer input válido.
# Soporta índice, string numérico y búsqueda por nombre.
try:
    import logging as _jarvis_v4125_logging
    import os as _jarvis_v4125_os
    import sounddevice as _jarvis_v4125_sd

    def _jarvis_v4125_norm_device(value):
        if value in (None, '', 'default'):
            return None
        if isinstance(value, str):
            raw = value.strip()
            if raw == '' or raw.lower() == 'default':
                return None
            if raw.lstrip('-').isdigit():
                try:
                    return int(raw)
                except Exception:
                    return raw
            return raw
        return value

    def _jarvis_v4125_all_devices():
        try:
            return list(_jarvis_v4125_sd.query_devices())
        except Exception:
            return []

    def _jarvis_v4125_valid_inputs():
        out = []
        for idx, info in enumerate(_jarvis_v4125_all_devices()):
            try:
                if int(info.get('max_input_channels', 0)) > 0:
                    out.append((idx, info))
            except Exception:
                continue
        return out

    def _jarvis_v4125_default_input_index():
        try:
            maybe = getattr(getattr(_jarvis_v4125_sd, 'default', None), 'device', None)
            if isinstance(maybe, (list, tuple)) and len(maybe) >= 1:
                first = maybe[0]
            else:
                first = maybe
            first = _jarvis_v4125_norm_device(first)
            return first if isinstance(first, int) else None
        except Exception:
            return None

    def _jarvis_v4125_choose_by_name(name):
        needle = str(name or '').strip().lower()
        if not needle:
            return None, None
        for idx, info in _jarvis_v4125_valid_inputs():
            try:
                dev_name = str(info.get('name', '')).lower()
                if needle in dev_name:
                    return idx, f'name_match:{needle}'
            except Exception:
                continue
        return None, None

    def _jarvis_v4125_pick_input_device(preferred=None):
        preferred = _jarvis_v4125_norm_device(preferred)
        explicit_name = (
            _jarvis_v4125_os.environ.get('JARVIS_WAKEWORD_INPUT_DEVICE_NAME')
            or _jarvis_v4125_os.environ.get('JARVIS_INPUT_DEVICE_NAME')
        )

        valid_inputs = _jarvis_v4125_valid_inputs()
        valid_indexes = {idx for idx, _info in valid_inputs}

        if explicit_name:
            idx, reason = _jarvis_v4125_choose_by_name(explicit_name)
            if idx is not None:
                return idx, reason

        if isinstance(preferred, int):
            if preferred in valid_indexes:
                return preferred, 'preferred_index_valid'
        elif isinstance(preferred, str) and preferred not in (None, ''):
            idx, reason = _jarvis_v4125_choose_by_name(preferred)
            if idx is not None:
                return idx, reason

        default_in = _jarvis_v4125_default_input_index()
        if isinstance(default_in, int) and default_in in valid_indexes:
            return default_in, 'default_input_index'

        if valid_inputs:
            return valid_inputs[0][0], 'first_valid_input'

        return None, 'portaudio_default'

    def _jarvis_v4125_patch_class(_cls):
        _orig_init = getattr(_cls, '__init__', None)
        if callable(_orig_init) and not getattr(_orig_init, '__jarvis_v4125_device__', False):
            def __init__(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                logger = _jarvis_v4125_logging.getLogger('jarvis')
                requested = getattr(self, 'input_device', None)
                chosen, reason = _jarvis_v4125_pick_input_device(requested)
                try:
                    self.input_device = 'default' if chosen is None else chosen
                except Exception:
                    pass
                logger.info(
                    'WAKEWORD_DEVICE_RESOLVE requested=%r chosen=%r reason=%s valid_inputs=%s',
                    requested,
                    getattr(self, 'input_device', None),
                    reason,
                    [idx for idx, _ in _jarvis_v4125_valid_inputs()],
                )
            __init__.__jarvis_v4125_device__ = True
            __init__.__wrapped__ = _orig_init
            _cls.__init__ = __init__

        _orig_wait = getattr(_cls, 'wait', None)
        if callable(_orig_wait) and not getattr(_orig_wait, '__jarvis_v4125_wait__', False):
            def wait(self, *args, **kwargs):
                logger = _jarvis_v4125_logging.getLogger('jarvis')
                requested = getattr(self, 'input_device', None)
                chosen, reason = _jarvis_v4125_pick_input_device(requested)
                desired = 'default' if chosen is None else chosen
                if desired != requested:
                    try:
                        self.input_device = desired
                    except Exception:
                        pass
                    logger.warning(
                        'WAKEWORD_DEVICE_FALLBACK requested=%r chosen=%r reason=%s',
                        requested,
                        getattr(self, 'input_device', None),
                        reason,
                    )
                return _orig_wait(self, *args, **kwargs)
            wait.__jarvis_v4125_wait__ = True
            wait.__wrapped__ = _orig_wait
            _cls.wait = wait

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, 'wait'):
            _jarvis_v4125_patch_class(_obj)
except Exception:
    pass
# === JARVIS_V4125_WAKEWORD_DEVICE_RESOLVER_V2_END ===

# === JARVIS_V4126_AUDIO_PREF_WAKEWORD_BEGIN ===
# Jarvis v4.1.2.6
# Usa preferencias persistentes de audio para resolver el micrófono de wake word.
try:
    import logging as _jarvis_v4126w_logging
    from jarvis.audio.device_selector import resolve_input_device as _jarvis_v4126w_resolve_input

    if 'WakeWordDetector' in globals() and hasattr(WakeWordDetector, '__init__'):
        _jarvis_v4126w_orig_init = WakeWordDetector.__init__
        if not getattr(_jarvis_v4126w_orig_init, '__jarvis_v4126_audio_pref__', False):
            def __init__(self, *args, **kwargs):
                _jarvis_v4126w_orig_init(self, *args, **kwargs)
                logger = _jarvis_v4126w_logging.getLogger('jarvis')
                result = _jarvis_v4126w_resolve_input(getattr(self, 'config', {}) or {}, role='wake', current=getattr(self, 'input_device', None))
                chosen = result.get('device', 'default')
                try:
                    self.input_device = chosen
                except Exception:
                    pass
                logger.info(
                    'AUDIO_DEVICE_SELECT role=wake requested=%r requested_name=%r chosen=%r chosen_name=%s reason=%s',
                    result.get('requested'),
                    result.get('requested_name'),
                    getattr(self, 'input_device', None),
                    result.get('name'),
                    result.get('reason'),
                )
            __init__.__jarvis_v4126_audio_pref__ = True
            __init__.__wrapped__ = _jarvis_v4126w_orig_init
            WakeWordDetector.__init__ = __init__
except Exception:
    pass
# === JARVIS_V4126_AUDIO_PREF_WAKEWORD_END ===


# === JARVIS_V4135_WAKEWORD_USB_HOTPLUG_RECOVERY_BEGIN ===
# Jarvis v4.1.3.5
# SAFE FIX: reabre el stream de wake word y re-resuelve el dispositivo preferido
# cuando el hub USB / ALSA / PortAudio pierde momentáneamente el micrófono.
try:
    import logging as _jarvis_v4135w_logging
    import os as _jarvis_v4135w_os
    import time as _jarvis_v4135w_time
    import sounddevice as _jarvis_v4135w_sd
    from jarvis.audio.device_selector import resolve_input_device as _jarvis_v4135w_resolve_input

    def _jarvis_v4135w_bool_env(name: str, default: bool) -> bool:
        raw = _jarvis_v4135w_os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() not in ('0', 'false', 'no', 'off', '')

    def _jarvis_v4135w_float_env(name: str, default: float) -> float:
        raw = _jarvis_v4135w_os.getenv(name)
        if raw is None or str(raw).strip() == '':
            return default
        try:
            return float(raw)
        except Exception:
            return default

    def _jarvis_v4135w_int_env(name: str, default: int) -> int:
        raw = _jarvis_v4135w_os.getenv(name)
        if raw is None or str(raw).strip() == '':
            return default
        try:
            return int(raw)
        except Exception:
            return default

    def _jarvis_v4135w_error_text(exc: Exception) -> str:
        try:
            return f"{type(exc).__name__}: {exc}".lower()
        except Exception:
            return str(exc).lower()

    def _jarvis_v4135w_is_recoverable(exc: Exception) -> bool:
        text = _jarvis_v4135w_error_text(exc)
        needles = (
            'broken pipe',
            'xrun',
            'paalsastream_handlexrun',
            'unanticipated host error',
            'stream closed',
            'stream is stopped',
            'stream not open',
            'device unavailable',
            'device disconnected',
            'device not available',
            'invalid device',
            'error opening inputstream',
            'portaudioerror',
            'paerrorcode -9999',
            'paerrorcode -9985',
            'paerrorcode -9988',
            'paerrorcode -9986',
            'input overflow',
            'audio hardware disappeared',
            'host error',
            'alsa',
            'usb',
        )
        return any(needle in text for needle in needles)

    def _jarvis_v4135w_refresh_input_device(self, logger):
        result = _jarvis_v4135w_resolve_input(getattr(self, 'config', {}) or {}, role='wake', current=getattr(self, 'input_device', None))
        chosen = result.get('device', 'default')
        previous = getattr(self, 'input_device', None)
        try:
            self.input_device = chosen
        except Exception:
            pass
        logger.info(
            'WAKEWORD_DEVICE_RESELECT previous=%r chosen=%r chosen_name=%s reason=%s requested=%r requested_name=%r',
            previous,
            getattr(self, 'input_device', None),
            result.get('name'),
            result.get('reason'),
            result.get('requested'),
            result.get('requested_name'),
        )
        return result

    if 'WakeWordDetector' in globals() and hasattr(WakeWordDetector, 'wait'):
        _jarvis_v4135w_orig_wait = WakeWordDetector.wait
        if not getattr(_jarvis_v4135w_orig_wait, '__jarvis_v4135_usb_hotplug__', False):
            def wait(self, should_continue):
                logger = getattr(self, 'logger', None) or _jarvis_v4135w_logging.getLogger('jarvis')
                if getattr(self, 'model', None) is None:
                    self._load_model()

                logger.info('Escuchando wake word con openWakeWord: hey jarvis')

                max_retries = _jarvis_v4135w_int_env('JARVIS_WAKEWORD_HOTPLUG_MAX_RETRIES', 12)
                base_backoff = _jarvis_v4135w_float_env('JARVIS_WAKEWORD_HOTPLUG_BACKOFF_SECONDS', 0.35)
                enabled = _jarvis_v4135w_bool_env('JARVIS_WAKEWORD_HOTPLUG_RECOVERY', True)
                consecutive_failures = 0

                while should_continue():
                    if enabled:
                        _jarvis_v4135w_refresh_input_device(self, logger)
                    stream_device = None if getattr(self, 'input_device', None) in (None, '', 'default') else getattr(self, 'input_device', None)
                    try:
                        with _jarvis_v4135w_sd.InputStream(
                            samplerate=getattr(self, 'capture_sample_rate', 16000),
                            channels=getattr(self, 'channels', 1),
                            dtype='int16',
                            blocksize=getattr(self, 'capture_block_size', 1280),
                            device=stream_device,
                        ) as stream:
                            consecutive_failures = 0
                            logger.info(
                                'WAKEWORD_STREAM_READY input_device=%r sample_rate=%s blocksize=%s',
                                getattr(self, 'input_device', None),
                                getattr(self, 'capture_sample_rate', None),
                                getattr(self, 'capture_block_size', None),
                            )
                            while should_continue():
                                try:
                                    audio, overflowed = stream.read(getattr(self, 'capture_block_size', 1280))
                                    if overflowed:
                                        logger.warning('Audio overflow en wake word')

                                    if should_discard_audio_frame():
                                        if getattr(self, 'debug', False):
                                            logger.debug('TTS Echo Guard: descartando frame de micrófono por cooldown')
                                        continue

                                    frame = self._prepare_frame(audio)
                                    prediction = self.model.predict(frame)
                                    detected, best_name, best_score = self._is_detected(prediction)

                                    if getattr(self, 'debug', False) and best_score >= 0.05:
                                        logger.info(
                                            'openWakeWord score: modelo=%s score=%.3f',
                                            best_name,
                                            best_score,
                                        )

                                    if _jarvis_echo_guard_should_suppress(locals()) and (detected and should_suppress_detection(best_score, self.threshold)):
                                        logger.info(
                                            'Wake word suprimida por TTS Echo Guard: modelo=%s score=%.3f',
                                            best_name,
                                            best_score,
                                        )
                                        reset_openwakeword_model(self.model, logger)
                                        continue

                                    if detected and not should_accept_wake_score(best_score):
                                        logger.info(
                                            'Wake word suprimida por MEDIA_GUARD: modelo=%s score=%.3f',
                                            best_name,
                                            best_score,
                                        )
                                        reset_openwakeword_model(self.model, logger)
                                        continue

                                    if detected:
                                        logger.info(
                                            'Wake word detectada por openWakeWord: modelo=%s score=%.3f',
                                            best_name,
                                            best_score,
                                        )
                                        return WakeResult(
                                            detected=True,
                                            text=f'openWakeWord:{best_name}:{best_score:.3f}',
                                            command_after_wake='',
                                        )
                                except Exception as exc:
                                    if enabled and _jarvis_v4135w_is_recoverable(exc):
                                        consecutive_failures += 1
                                        wait_s = min(base_backoff * max(consecutive_failures, 1), 2.0)
                                        logger.warning(
                                            'WAKEWORD_STREAM_RECOVERY attempt=%s/%s device=%r error=%s backoff=%.2fs',
                                            consecutive_failures,
                                            max_retries,
                                            getattr(self, 'input_device', None),
                                            exc,
                                            wait_s,
                                        )
                                        reset_openwakeword_model(self.model, logger)
                                        if consecutive_failures > max_retries:
                                            logger.error(
                                                'WAKEWORD_STREAM_RECOVERY_GIVEUP attempts=%s device=%r last_error=%s',
                                                consecutive_failures,
                                                getattr(self, 'input_device', None),
                                                exc,
                                            )
                                            _jarvis_v4135w_time.sleep(wait_s)
                                            return WakeResult(False)
                                        _jarvis_v4135w_time.sleep(wait_s)
                                        break
                                    logger.error('Error en loop openWakeWord: %s', exc, exc_info=True)
                                    _jarvis_v4135w_time.sleep(1.0)
                    except Exception as exc:
                        if enabled and _jarvis_v4135w_is_recoverable(exc):
                            consecutive_failures += 1
                            wait_s = min(base_backoff * max(consecutive_failures, 1), 2.5)
                            logger.warning(
                                'WAKEWORD_STREAM_REOPEN attempt=%s/%s device=%r error=%s backoff=%.2fs',
                                consecutive_failures,
                                max_retries,
                                getattr(self, 'input_device', None),
                                exc,
                                wait_s,
                            )
                            reset_openwakeword_model(self.model, logger)
                            if consecutive_failures > max_retries:
                                logger.error(
                                    'WAKEWORD_STREAM_REOPEN_GIVEUP attempts=%s device=%r last_error=%s',
                                    consecutive_failures,
                                    getattr(self, 'input_device', None),
                                    exc,
                                )
                                _jarvis_v4135w_time.sleep(wait_s)
                                return WakeResult(False)
                            _jarvis_v4135w_time.sleep(wait_s)
                            continue
                        logger.error('Error abriendo micrófono para openWakeWord: %s', exc, exc_info=True)
                        _jarvis_v4135w_time.sleep(1.0)
                        return WakeResult(False)

                return WakeResult(False)

            wait.__jarvis_v4135_usb_hotplug__ = True
            wait.__wrapped__ = _jarvis_v4135w_orig_wait
            WakeWordDetector.wait = wait
except Exception:
    pass
# === JARVIS_V4135_WAKEWORD_USB_HOTPLUG_RECOVERY_END ===
