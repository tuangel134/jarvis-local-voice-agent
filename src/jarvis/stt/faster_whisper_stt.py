from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis.stt.base import STTProvider


class FasterWhisperSTT(STTProvider):
    name = 'faster-whisper'

    def __init__(self, config: dict[str, Any], logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger('jarvis.stt')
        stt = config.get('stt', {})
        self.model_name = stt.get('model', 'base')
        self.device = stt.get('device', 'cpu')
        self.compute_type = stt.get('compute_type', 'int8')
        self.language = stt.get('language', 'es')
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            raise RuntimeError('faster-whisper no está instalado. Ejecuta install.sh o pip install faster-whisper') from exc
        self.logger.info('Cargando modelo STT faster-whisper: %s', self.model_name)
        self._model = WhisperModel(self.model_name, device=self.device, compute_type=self.compute_type)
        return self._model

    def transcribe(self, wav_path: str | Path) -> str:
        model = self._load()
        segments, info = model.transcribe(
            str(wav_path),
            language=self.language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
            beam_size=1,
            condition_on_previous_text=False,
        )
        text = ' '.join(seg.text.strip() for seg in segments).strip()
        self.logger.debug('STT language=%s prob=%.3f text=%r', getattr(info, 'language', None), getattr(info, 'language_probability', 0.0), text)
        return text

# === JARVIS_V4062_LATENCY_STT_BEGIN ===
# Jarvis v4.0.6.2 latency profiler: wrapper no destructivo para clases STT.
try:
    import time as _jarvis_v4062_time
    import logging as _jarvis_v4062_logging
    from pathlib import Path as _jarvis_v4062_Path

    def _jarvis_v4062_emit_latency(topic, summary, payload=None):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload or {}, source="latency_profiler")
        except Exception:
            pass

    def _jarvis_v4062_wrap_stt_class(_cls):
        if not _cls or not hasattr(_cls, "transcribe"):
            return
        if getattr(_cls.transcribe, "__jarvis_v4062_latency__", False):
            return

        _orig = _cls.transcribe

        def _wrapped_transcribe(self, wav_path, *args, **kwargs):
            logger = _jarvis_v4062_logging.getLogger("jarvis")
            start = _jarvis_v4062_time.monotonic()
            size = None
            try:
                p = _jarvis_v4062_Path(wav_path)
                if p.exists():
                    size = p.stat().st_size
            except Exception:
                pass

            logger.info(
                "LATENCY stt.start class=%s path=%s bytes=%s",
                _cls.__name__,
                wav_path,
                size,
            )

            ok = False
            err = None
            text_len = None
            try:
                result = _orig(self, wav_path, *args, **kwargs)
                ok = True
                try:
                    text_len = len(str(result or ""))
                except Exception:
                    text_len = None
                return result
            except Exception as exc:
                err = str(exc)
                raise
            finally:
                elapsed_ms = int((_jarvis_v4062_time.monotonic() - start) * 1000)
                logger.info(
                    "LATENCY stt.done elapsed_ms=%s ok=%s text_len=%s error=%s",
                    elapsed_ms,
                    ok,
                    text_len,
                    err or "",
                )
                _jarvis_v4062_emit_latency(
                    "latency.stt",
                    f"{elapsed_ms} ms",
                    {
                        "elapsed_ms": elapsed_ms,
                        "ok": ok,
                        "text_len": text_len,
                        "bytes": size,
                        "error": err,
                        "class": _cls.__name__,
                    },
                )

        _wrapped_transcribe.__jarvis_v4062_latency__ = True
        _wrapped_transcribe.__wrapped__ = _orig
        _cls.transcribe = _wrapped_transcribe

    for _name, _obj in list(globals().items()):
        if isinstance(_obj, type) and hasattr(_obj, "transcribe"):
            _jarvis_v4062_wrap_stt_class(_obj)

except Exception:
    pass
# === JARVIS_V4062_LATENCY_STT_END ===

# === JARVIS_V4063_STT_PRELOAD_CACHE_BEGIN ===
# Jarvis v4.0.6.3: cache/preload global para FasterWhisperSTT.
# Objetivo: evitar "Cargando modelo STT faster-whisper" después del wake word.

try:
    import logging as _jarvis_v4063_logging
    import inspect as _jarvis_v4063_inspect
    import tempfile as _jarvis_v4063_tempfile
    import wave as _jarvis_v4063_wave
    from pathlib import Path as _jarvis_v4063_Path

    _JARVIS_V4063_STT_MODEL_CACHE = {}

    def _jarvis_v4063_stt_key(self):
        return (
            getattr(self, "model_size", None) or getattr(self, "model", None) or getattr(self, "model_name", None) or "small",
            getattr(self, "device", None) or "auto",
            getattr(self, "compute_type", None) or "default",
            getattr(self, "language", None) or "auto",
        )

    def _jarvis_v4063_wrap_model_loader(_cls, _method_name):
        if not hasattr(_cls, _method_name):
            return False
        _orig = getattr(_cls, _method_name)
        if getattr(_orig, "__jarvis_v4063_cache__", False):
            return True

        def _wrapped(self, *args, **kwargs):
            key = _jarvis_v4063_stt_key(self)
            if key in _JARVIS_V4063_STT_MODEL_CACHE:
                model = _JARVIS_V4063_STT_MODEL_CACHE[key]
                try:
                    setattr(self, "_model", model)
                except Exception:
                    pass
                try:
                    setattr(self, "model", model)
                except Exception:
                    pass
                return model

            model = _orig(self, *args, **kwargs)
            if model is not None:
                _JARVIS_V4063_STT_MODEL_CACHE[key] = model
                try:
                    setattr(self, "_model", model)
                except Exception:
                    pass
                try:
                    setattr(self, "model", model)
                except Exception:
                    pass
            return model

        _wrapped.__jarvis_v4063_cache__ = True
        _wrapped.__wrapped__ = _orig
        setattr(_cls, _method_name, _wrapped)
        return True

    def _jarvis_v4063_instantiate_stt(config=None, logger=None):
        cls = globals().get("FasterWhisperSTT")
        if cls is None:
            return None

        tries = []
        if config is not None and logger is not None:
            tries.append((config, logger))
        if config is not None:
            tries.append((config,))
        if logger is not None:
            tries.append((logger,))
        tries.append(tuple())

        for args in tries:
            try:
                return cls(*args)
            except Exception:
                pass

        try:
            sig = _jarvis_v4063_inspect.signature(cls)
            kwargs = {}
            for name in sig.parameters:
                if name in ("config", "cfg", "settings") and config is not None:
                    kwargs[name] = config
                elif name in ("logger", "log") and logger is not None:
                    kwargs[name] = logger
            if kwargs:
                return cls(**kwargs)
        except Exception:
            pass

        return None

    def _jarvis_v4063_make_silence_wav():
        path = _jarvis_v4063_Path(_jarvis_v4063_tempfile.gettempdir()) / "jarvis_stt_warmup_silence.wav"
        try:
            with _jarvis_v4063_wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * int(16000 * 0.25))
        except Exception:
            pass
        return path

    def jarvis_preload_stt_model(config=None, logger=None):
        logger = logger or _jarvis_v4063_logging.getLogger("jarvis")
        cls = globals().get("FasterWhisperSTT")
        if cls is None:
            try:
                logger.warning("STT preload: FasterWhisperSTT no encontrado")
            except Exception:
                pass
            return False

        # Envolver cualquier método típico de carga.
        wrapped_any = False
        for method in ("_load_model", "load_model", "_get_model", "get_model", "_model", "model"):
            try:
                wrapped_any = _jarvis_v4063_wrap_model_loader(cls, method) or wrapped_any
            except Exception:
                pass

        inst = _jarvis_v4063_instantiate_stt(config=config, logger=logger)
        if inst is None:
            try:
                logger.warning("STT preload: no pude instanciar FasterWhisperSTT")
            except Exception:
                pass
            return False

        # Intentar cargar por método explícito.
        for method in ("_load_model", "load_model", "_get_model", "get_model"):
            fn = getattr(inst, method, None)
            if callable(fn):
                try:
                    model = fn()
                    if model is not None:
                        key = _jarvis_v4063_stt_key(inst)
                        _JARVIS_V4063_STT_MODEL_CACHE[key] = model
                        try:
                            logger.info("STT preload listo via %s key=%s", method, key)
                        except Exception:
                            pass
                        return True
                except Exception as exc:
                    try:
                        logger.warning("STT preload método %s falló: %s", method, exc)
                    except Exception:
                        pass

        # Fallback: transcribir silencio corto para forzar carga.
        try:
            wav = _jarvis_v4063_make_silence_wav()
            if hasattr(inst, "transcribe"):
                try:
                    inst.transcribe(wav)
                except Exception:
                    # Puede fallar por silencio vacío, pero aun así pudo cargar modelo.
                    pass

                for attr in ("_model", "model"):
                    model = getattr(inst, attr, None)
                    if model is not None:
                        key = _jarvis_v4063_stt_key(inst)
                        _JARVIS_V4063_STT_MODEL_CACHE[key] = model
                        try:
                            logger.info("STT preload listo via transcribe key=%s", key)
                        except Exception:
                            pass
                        return True

        except Exception as exc:
            try:
                logger.warning("STT preload fallback falló: %s", exc)
            except Exception:
                pass

        try:
            logger.warning("STT preload no pudo confirmar carga")
        except Exception:
            pass
        return False

except Exception:
    pass
# === JARVIS_V4063_STT_PRELOAD_CACHE_END ===

# === JARVIS_V4063_2_STT_SHARED_MODEL_CACHE_BEGIN ===
# Jarvis v4.0.6.3.2
# Conecta el modelo precargado al runtime real de FasterWhisperSTT.
# Problema anterior: el preload calentaba una instancia, pero el primer comando real
# volvía a ejecutar "Cargando modelo STT faster-whisper: small".
try:
    import logging as _jarvis_v40632_logging
    import inspect as _jarvis_v40632_inspect

    _JARVIS_V4063_STT_MODEL_CACHE = globals().setdefault("_JARVIS_V4063_STT_MODEL_CACHE", {})

    def _jarvis_v40632_key(self):
        return (
            getattr(self, "model_size", None)
            or getattr(self, "model_name", None)
            or getattr(self, "model", None)
            or "small",
            getattr(self, "device", None) or "cpu",
            getattr(self, "compute_type", None) or "int8",
            getattr(self, "language", None) or "es",
        )

    def _jarvis_v40632_model_attrs():
        return ("_model", "model", "_whisper_model", "whisper_model", "_fw_model", "fw_model")

    def _jarvis_v40632_get_cached_for(self):
        key = _jarvis_v40632_key(self)
        if key in _JARVIS_V4063_STT_MODEL_CACHE:
            return _JARVIS_V4063_STT_MODEL_CACHE[key]

        # Fallback flexible: mismo model_size/language si device/compute difieren por defaults.
        for k, model in list(_JARVIS_V4063_STT_MODEL_CACHE.items()):
            try:
                if str(k[0]) == str(key[0]) and str(k[3]) == str(key[3]):
                    return model
            except Exception:
                continue

        # Último fallback: si solo hay un modelo cacheado, úsalo.
        if len(_JARVIS_V4063_STT_MODEL_CACHE) == 1:
            return next(iter(_JARVIS_V4063_STT_MODEL_CACHE.values()))

        return None

    def _jarvis_v40632_attach_cached(self):
        model = _jarvis_v40632_get_cached_for(self)
        if model is None:
            return False
        for attr in _jarvis_v40632_model_attrs():
            try:
                setattr(self, attr, model)
            except Exception:
                pass
        return True

    def _jarvis_v40632_capture_from_instance(self):
        for attr in _jarvis_v40632_model_attrs():
            try:
                model = getattr(self, attr, None)
                if model is not None:
                    _JARVIS_V4063_STT_MODEL_CACHE[_jarvis_v40632_key(self)] = model
                    return model
            except Exception:
                pass
        return None

    def _jarvis_v40632_wrap_loader_method(cls, name):
        if not hasattr(cls, name):
            return False

        orig = getattr(cls, name)
        if not callable(orig) or getattr(orig, "__jarvis_v40632_shared_cache__", False):
            return False

        def _wrapped(self, *args, **kwargs):
            logger = _jarvis_v40632_logging.getLogger("jarvis")

            cached = _jarvis_v40632_get_cached_for(self)
            if cached is not None:
                _jarvis_v40632_attach_cached(self)
                try:
                    logger.info("STT shared cache hit via %s key=%s", name, _jarvis_v40632_key(self))
                except Exception:
                    pass
                return cached

            model = orig(self, *args, **kwargs)
            if model is not None:
                _JARVIS_V4063_STT_MODEL_CACHE[_jarvis_v40632_key(self)] = model
                _jarvis_v40632_attach_cached(self)
                try:
                    logger.info("STT shared cache saved via %s key=%s", name, _jarvis_v40632_key(self))
                except Exception:
                    pass
            else:
                _jarvis_v40632_capture_from_instance(self)
            return model

        _wrapped.__jarvis_v40632_shared_cache__ = True
        _wrapped.__wrapped__ = orig
        setattr(cls, name, _wrapped)
        return True

    def _jarvis_v40632_wrap_class(cls):
        if cls is None:
            return False

        # __init__: al crear una instancia, inyéctale el modelo cacheado si existe.
        try:
            orig_init = cls.__init__
            if not getattr(orig_init, "__jarvis_v40632_shared_cache__", False):
                def _init_wrapped(self, *args, **kwargs):
                    orig_init(self, *args, **kwargs)
                    if _jarvis_v40632_attach_cached(self):
                        try:
                            _jarvis_v40632_logging.getLogger("jarvis").info(
                                "STT shared cache attached on init key=%s",
                                _jarvis_v40632_key(self),
                            )
                        except Exception:
                            pass

                _init_wrapped.__jarvis_v40632_shared_cache__ = True
                _init_wrapped.__wrapped__ = orig_init
                cls.__init__ = _init_wrapped
        except Exception:
            pass

        # Métodos típicos donde se carga el modelo.
        for method in (
            "_ensure_model",
            "ensure_model",
            "_load_model",
            "load_model",
            "_get_model",
            "get_model",
            "_load",
            "load",
            "_model",
        ):
            try:
                _jarvis_v40632_wrap_loader_method(cls, method)
            except Exception:
                pass

        # transcribe: antes de transcribir, inyecta cache; después captura lo cargado.
        try:
            orig_transcribe = cls.transcribe
            if not getattr(orig_transcribe, "__jarvis_v40632_shared_cache__", False):
                def _transcribe_wrapped(self, *args, **kwargs):
                    logger = _jarvis_v40632_logging.getLogger("jarvis")
                    attached = _jarvis_v40632_attach_cached(self)
                    if attached:
                        try:
                            logger.info("STT shared cache attached before transcribe key=%s", _jarvis_v40632_key(self))
                        except Exception:
                            pass
                    result = orig_transcribe(self, *args, **kwargs)
                    _jarvis_v40632_capture_from_instance(self)
                    return result

                _transcribe_wrapped.__jarvis_v40632_shared_cache__ = True
                _transcribe_wrapped.__wrapped__ = orig_transcribe
                cls.transcribe = _transcribe_wrapped
        except Exception:
            pass

        return True

    # Aplicar al cargar el módulo.
    try:
        _jarvis_v40632_wrap_class(globals().get("FasterWhisperSTT"))
    except Exception:
        pass

    # Reemplazar/envolver jarvis_preload_stt_model para que instale wrappers antes de precargar.
    _jarvis_v40632_old_preload = globals().get("jarvis_preload_stt_model")

    def jarvis_preload_stt_model(config=None, logger=None):
        logger = logger or _jarvis_v40632_logging.getLogger("jarvis")
        cls = globals().get("FasterWhisperSTT")
        _jarvis_v40632_wrap_class(cls)

        ok = False
        if callable(_jarvis_v40632_old_preload):
            try:
                ok = bool(_jarvis_v40632_old_preload(config=config, logger=logger))
            except TypeError:
                try:
                    ok = bool(_jarvis_v40632_old_preload(config, logger))
                except Exception as exc:
                    try:
                        logger.warning("STT shared cache preload old fallback falló: %s", exc)
                    except Exception:
                        pass
            except Exception as exc:
                try:
                    logger.warning("STT shared cache preload old falló: %s", exc)
                except Exception:
                    pass

        # Confirmación.
        try:
            if _JARVIS_V4063_STT_MODEL_CACHE:
                logger.info("STT shared cache ready keys=%s", list(_JARVIS_V4063_STT_MODEL_CACHE.keys()))
                return True
        except Exception:
            pass

        return ok

except Exception:
    pass
# === JARVIS_V4063_2_STT_SHARED_MODEL_CACHE_END ===

# === JARVIS_V4064_STT_WAV_TRIM_BEGIN ===
# Jarvis v4.0.6.4: recorte ligero de silencio antes de faster-whisper.
# No sustituye al VAD del micrófono; solo reduce audio sobrante antes de STT.
try:
    import os as _jarvis_v4064_os
    import wave as _jarvis_v4064_wave
    import time as _jarvis_v4064_time
    import math as _jarvis_v4064_math
    import logging as _jarvis_v4064_logging
    from array import array as _jarvis_v4064_array
    from pathlib import Path as _jarvis_v4064_Path

    def _jarvis_v4064_rms_int16(samples):
        if not samples:
            return 0.0
        total = 0
        for s in samples:
            total += int(s) * int(s)
        return _jarvis_v4064_math.sqrt(total / max(1, len(samples)))

    def _jarvis_v4064_trim_wav_for_stt(wav_path):
        if _jarvis_v4064_os.environ.get("JARVIS_STT_TRIM_DISABLE", "").strip() == "1":
            return wav_path

        src = _jarvis_v4064_Path(wav_path)
        if not src.exists():
            return wav_path

        try:
            threshold = float(_jarvis_v4064_os.environ.get("JARVIS_STT_TRIM_RMS", "260"))
        except Exception:
            threshold = 260.0

        try:
            pad_ms = int(float(_jarvis_v4064_os.environ.get("JARVIS_STT_TRIM_PAD_MS", "180")))
        except Exception:
            pad_ms = 180

        try:
            min_keep_ms = int(float(_jarvis_v4064_os.environ.get("JARVIS_STT_TRIM_MIN_KEEP_MS", "500")))
        except Exception:
            min_keep_ms = 500

        try:
            with _jarvis_v4064_wave.open(str(src), "rb") as wf:
                nch = wf.getnchannels()
                sw = wf.getsampwidth()
                fr = wf.getframerate()
                nframes = wf.getnframes()
                frames = wf.readframes(nframes)

            if sw != 2 or fr <= 0 or nframes <= 0:
                return wav_path

            samples = _jarvis_v4064_array("h")
            samples.frombytes(frames)

            # Si es estéreo/multicanal, usamos la energía global de muestras intercaladas.
            chunk_frames = max(1, int(fr * 0.05))  # 50 ms
            chunk_samples = chunk_frames * max(1, nch)
            total_chunks = max(1, len(samples) // chunk_samples)

            speech_chunks = []
            for i in range(total_chunks):
                chunk = samples[i * chunk_samples:(i + 1) * chunk_samples]
                rms = _jarvis_v4064_rms_int16(chunk)
                if rms >= threshold:
                    speech_chunks.append(i)

            if not speech_chunks:
                return wav_path

            first = min(speech_chunks)
            last = max(speech_chunks)

            pad_chunks = max(1, int((pad_ms / 1000.0) / 0.05))
            first = max(0, first - pad_chunks)
            last = min(total_chunks - 1, last + pad_chunks)

            start_sample = first * chunk_samples
            end_sample = min(len(samples), (last + 1) * chunk_samples)
            keep_samples = end_sample - start_sample
            keep_ms = int((keep_samples / max(1, nch)) / fr * 1000)

            if keep_ms < min_keep_ms:
                return wav_path

            # No escribas si el recorte casi no mejora.
            original_ms = int((len(samples) / max(1, nch)) / fr * 1000)
            if original_ms - keep_ms < 250:
                return wav_path

            trimmed = samples[start_sample:end_sample]
            out = src.with_name(src.stem + "_stt_trimmed.wav")

            with _jarvis_v4064_wave.open(str(out), "wb") as wf:
                wf.setnchannels(nch)
                wf.setsampwidth(sw)
                wf.setframerate(fr)
                wf.writeframes(trimmed.tobytes())

            logger = _jarvis_v4064_logging.getLogger("jarvis")
            try:
                logger.info(
                    "LATENCY stt.trim original_ms=%s trimmed_ms=%s threshold=%s path=%s",
                    original_ms,
                    keep_ms,
                    threshold,
                    out,
                )
            except Exception:
                pass

            try:
                from jarvis.bus.event_bus import EventBus
                EventBus().publish(
                    "latency.stt.trim",
                    {
                        "original_ms": original_ms,
                        "trimmed_ms": keep_ms,
                        "threshold": threshold,
                        "path": str(out),
                    },
                    source="stt_trim",
                )
            except Exception:
                pass

            return out

        except Exception as exc:
            try:
                _jarvis_v4064_logging.getLogger("jarvis").warning("STT trim falló, usando WAV original: %s", exc)
            except Exception:
                pass
            return wav_path

    if "FasterWhisperSTT" in globals() and hasattr(FasterWhisperSTT, "transcribe"):
        if not getattr(FasterWhisperSTT.transcribe, "__jarvis_v4064_trim__", False):
            _jarvis_v4064_orig_transcribe = FasterWhisperSTT.transcribe

            def _jarvis_v4064_transcribe_trimmed(self, wav_path, *args, **kwargs):
                trimmed_path = _jarvis_v4064_trim_wav_for_stt(wav_path)
                return _jarvis_v4064_orig_transcribe(self, trimmed_path, *args, **kwargs)

            _jarvis_v4064_transcribe_trimmed.__jarvis_v4064_trim__ = True
            _jarvis_v4064_transcribe_trimmed.__wrapped__ = _jarvis_v4064_orig_transcribe
            FasterWhisperSTT.transcribe = _jarvis_v4064_transcribe_trimmed

except Exception:
    pass
# === JARVIS_V4064_STT_WAV_TRIM_END ===

# === JARVIS_V4072_STT_TINY_FAST_REPLY_BEGIN ===
# Jarvis v4.0.7.2
# STT dual:
# - intenta tiny/int8 primero para frases fast_reply conocidas
# - si tiny produce frase compatible, devuelve ese texto y evita small
# - si no, cae al transcribe original small
try:
    import os as _jarvis_v4072_os
    import re as _jarvis_v4072_re
    import time as _jarvis_v4072_time
    import logging as _jarvis_v4072_logging
    from pathlib import Path as _jarvis_v4072_Path

    _JARVIS_V4072_TINY_MODEL = None
    _JARVIS_V4072_TINY_MODEL_KEY = None

    def _jarvis_v4072_publish(topic, payload):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload, source="stt_tiny_fast_reply")
        except Exception:
            pass

    def _jarvis_v4072_norm(text):
        text = str(text or "").strip().lower()
        text = text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        text = text.replace("¿", "").replace("?", "").replace("¡", "").replace("!", "")
        text = _jarvis_v4072_re.sub(r"[^a-z0-9ñ\s]", " ", text)
        text = _jarvis_v4072_re.sub(r"\s+", " ", text).strip()
        return text

    def _jarvis_v4072_is_fast_reply_candidate(text):
        n = _jarvis_v4072_norm(text)
        if not n:
            return False

        # Evitar comandos complejos, archivos, builds, web, etc.
        complex_words = (
            "abre ", "abrir ", "busca ", "buscar ", "borra ", "elimina ",
            "ejecuta ", "instala ", "descarga ", "reproduce ", "youtube",
            "archivo", "carpeta", "build", "aab", "apk", "servicio",
            "jellyfin", "immich", "terminal", "navegador", "chrome"
        )
        if any(w in n for w in complex_words):
            return False

        patterns = [
            r"^(dime )?(que )?hora es$",
            r"^(que )?horas son$",
            r"^(dime )?la hora$",
            r"^(estas|esta) ahi$",
            r"^sigues ahi$",
            r"^hola( jarvis)?$",
            r"^hey jarvis$",
            r"^gracias( jarvis)?$",
            r"^muchas gracias$",
            r"^(que )?puedes hacer$",
            r"^(que )?sabes hacer$",
            r"^(que )?fecha es$",
            r"^que dia es$",
            r"^buenos dias$",
            r"^buenas tardes$",
            r"^buenas noches$",
        ]

        return any(_jarvis_v4072_re.search(p, n) for p in patterns)

    def _jarvis_v4072_get_tiny_model(logger=None):
        global _JARVIS_V4072_TINY_MODEL, _JARVIS_V4072_TINY_MODEL_KEY
        logger = logger or _jarvis_v4072_logging.getLogger("jarvis")

        model_size = _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_MODEL", "tiny")
        device = _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_DEVICE", "cpu")
        compute_type = _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_COMPUTE", "int8")
        key = (model_size, device, compute_type)

        if _JARVIS_V4072_TINY_MODEL is not None and _JARVIS_V4072_TINY_MODEL_KEY == key:
            return _JARVIS_V4072_TINY_MODEL

        try:
            from faster_whisper import WhisperModel
            start = _jarvis_v4072_time.monotonic()
            logger.info("FAST_STT tiny cargando modelo=%s device=%s compute=%s", model_size, device, compute_type)
            _JARVIS_V4072_TINY_MODEL = WhisperModel(model_size, device=device, compute_type=compute_type)
            _JARVIS_V4072_TINY_MODEL_KEY = key
            elapsed_ms = int((_jarvis_v4072_time.monotonic() - start) * 1000)
            logger.info("FAST_STT tiny cargado elapsed_ms=%s key=%s", elapsed_ms, key)
            _jarvis_v4072_publish("stt.fast_tiny.loaded", {"elapsed_ms": elapsed_ms, "key": str(key)})
            return _JARVIS_V4072_TINY_MODEL
        except Exception as exc:
            logger.warning("FAST_STT tiny no pudo cargar: %s", exc)
            _jarvis_v4072_publish("stt.fast_tiny.load_failed", {"error": str(exc), "key": str(key)})
            return None

    def jarvis_preload_fast_tiny_stt(logger=None):
        logger = logger or _jarvis_v4072_logging.getLogger("jarvis")
        if _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_DISABLE", "").strip() == "1":
            return False

        model = _jarvis_v4072_get_tiny_model(logger=logger)
        if model is None:
            return False

        # Warmup mínimo con silencio si es posible.
        try:
            import tempfile
            import wave
            p = _jarvis_v4072_Path(tempfile.gettempdir()) / "jarvis_fast_tiny_stt_warmup.wav"
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * int(16000 * 0.15))
            try:
                segs, info = model.transcribe(str(p), language="es", vad_filter=True, beam_size=1, condition_on_previous_text=False)
                list(segs)
            except Exception:
                pass
        except Exception:
            pass

        logger.info("FAST_STT tiny preload listo")
        return True

    def _jarvis_v4072_transcribe_tiny(wav_path, logger=None):
        logger = logger or _jarvis_v4072_logging.getLogger("jarvis")
        model = _jarvis_v4072_get_tiny_model(logger=logger)
        if model is None:
            return "", 0

        # Reusar trim si existe.
        path = wav_path
        try:
            trim_fn = globals().get("_jarvis_v4064_trim_wav_for_stt")
            if callable(trim_fn):
                path = trim_fn(wav_path)
        except Exception:
            path = wav_path

        start = _jarvis_v4072_time.monotonic()
        text = ""
        try:
            segments, info = model.transcribe(
                str(path),
                language="es",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=350, speech_pad_ms=120),
                beam_size=1,
                condition_on_previous_text=False,
            )
            parts = []
            for s in segments:
                try:
                    parts.append(str(s.text or "").strip())
                except Exception:
                    pass
            text = " ".join([p for p in parts if p]).strip()
        except Exception as exc:
            logger.warning("FAST_STT tiny transcribe falló: %s", exc)
            _jarvis_v4072_publish("stt.fast_tiny.failed", {"error": str(exc)})
            text = ""

        elapsed_ms = int((_jarvis_v4072_time.monotonic() - start) * 1000)
        logger.info("FAST_STT tiny result elapsed_ms=%s text=%r", elapsed_ms, text)
        _jarvis_v4072_publish("stt.fast_tiny.result", {"elapsed_ms": elapsed_ms, "text": text})
        return text, elapsed_ms

    if "FasterWhisperSTT" in globals() and hasattr(FasterWhisperSTT, "transcribe"):
        if not getattr(FasterWhisperSTT.transcribe, "__jarvis_v4072_fast_tiny__", False):
            _jarvis_v4072_original_transcribe = FasterWhisperSTT.transcribe

            def _jarvis_v4072_fast_tiny_transcribe(self, wav_path, *args, **kwargs):
                logger = _jarvis_v4072_logging.getLogger("jarvis")

                if _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_DISABLE", "").strip() == "1":
                    return _jarvis_v4072_original_transcribe(self, wav_path, *args, **kwargs)

                text, elapsed_ms = _jarvis_v4072_transcribe_tiny(wav_path, logger=logger)

                if _jarvis_v4072_is_fast_reply_candidate(text):
                    logger.info("FAST_STT tiny usado para fast_reply text=%r elapsed_ms=%s", text, elapsed_ms)
                    _jarvis_v4072_publish("stt.fast_tiny.used", {"elapsed_ms": elapsed_ms, "text": text})
                    return text

                logger.info("FAST_STT tiny miss; usando small original text=%r elapsed_ms=%s", text, elapsed_ms)
                _jarvis_v4072_publish("stt.fast_tiny.miss", {"elapsed_ms": elapsed_ms, "text": text})
                return _jarvis_v4072_original_transcribe(self, wav_path, *args, **kwargs)

            _jarvis_v4072_fast_tiny_transcribe.__jarvis_v4072_fast_tiny__ = True
            _jarvis_v4072_fast_tiny_transcribe.__wrapped__ = _jarvis_v4072_original_transcribe
            FasterWhisperSTT.transcribe = _jarvis_v4072_fast_tiny_transcribe

except Exception:
    pass
# === JARVIS_V4072_STT_TINY_FAST_REPLY_END ===

# === JARVIS_V4072_1_STT_TINY_FUZZY_FAST_REPLY_BEGIN ===
# Jarvis v4.0.7.2.1
# Mejora STT tiny: acepta errores típicos como "Díma que orés" -> "dime qué hora es"
# y evita correr tiny dos veces cuando hay miss.
try:
    import os as _jarvis_v40721_os
    import re as _jarvis_v40721_re
    import time as _jarvis_v40721_time
    import logging as _jarvis_v40721_logging

    def _jarvis_v40721_publish(topic, payload):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload, source="stt_tiny_fuzzy_fast_reply")
        except Exception:
            pass

    def _jarvis_v40721_norm(text):
        text = str(text or "").strip().lower()
        repl = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
            "¿": "", "?": "", "¡": "", "!": "",
        }
        for a, b in repl.items():
            text = text.replace(a, b)
        text = _jarvis_v40721_re.sub(r"[^a-z0-9ñ\s]", " ", text)
        text = _jarvis_v40721_re.sub(r"\s+", " ", text).strip()
        return text

    def _jarvis_v40721_canonical_fast_reply(text):
        n = _jarvis_v40721_norm(text)
        if not n:
            return None

        # Evitar comandos reales: tiny fuzzy solo debe usarse para conversación/fast replies.
        complex_words = (
            "abre", "abrir", "busca", "buscar", "borra", "elimina", "ejecuta",
            "instala", "descarga", "reproduce", "youtube", "archivo", "carpeta",
            "build", "aab", "apk", "servicio", "jellyfin", "immich", "terminal",
        )
        if any(_jarvis_v40721_re.search(rf"\b{_jarvis_v40721_re.escape(w)}\b", n) for w in complex_words):
            return None

        # Hora: errores comunes de tiny con español.
        # Ejemplos vistos: "dima que ores", "dime que ores", "que or es", "que hor es".
        time_patterns = [
            r"\b(dima|dime|diga|dimele)?\s*(que|ke)?\s*(hora|horas|ora|oras|ore|ores|orez|ores|or es|hor es)\s*(es|son)?\b",
            r"\b(que|ke)\s*(hora|horas|ora|oras|ore|ores|orez|or es|hor es)\s*(es|son)?\b",
            r"\b(la\s*)?(hora|ora)\b",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in time_patterns):
            return "dime qué hora es"

        # Presencia.
        presence_patterns = [
            r"\b(estas|esta|estas|tas)\s*(ahi|hay|ai)\b",
            r"\b(sigues|sigue)\s*(ahi|hay|ai)\b",
            r"\b(aqui|aki)\s*(estas|esta)\b",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in presence_patterns):
            return "estás ahí"

        # Gracias.
        thanks_patterns = [
            r"\bgracias\b",
            r"\bmuchas\s+gracias\b",
            r"\bte\s+agradezco\b",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in thanks_patterns):
            return "gracias"

        # Saludos.
        greeting_patterns = [
            r"^hola(\s+jarvis)?$",
            r"^(oye|hey)\s+jarvis$",
            r"^buenos\s+dias$",
            r"^buenas\s+(tardes|noches)$",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in greeting_patterns):
            return "hola jarvis"

        # Capacidades.
        capability_patterns = [
            r"\b(que|ke)\s+puedes\s+hacer\b",
            r"\b(que|ke)\s+sabes\s+hacer\b",
            r"\b(cuales|cual)\s+son\s+tus\s+capacidades\b",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in capability_patterns):
            return "qué puedes hacer"

        # Fecha/día.
        date_patterns = [
            r"\b(que|ke)\s+fecha\s+es\b",
            r"\b(que|ke)\s+dia\s+es\b",
            r"\bfecha\s+de\s+hoy\b",
        ]
        if any(_jarvis_v40721_re.search(p, n) for p in date_patterns):
            return "qué fecha es"

        return None

    if "FasterWhisperSTT" in globals() and hasattr(FasterWhisperSTT, "transcribe"):
        if not getattr(FasterWhisperSTT.transcribe, "__jarvis_v40721_tiny_fuzzy__", False):
            _jarvis_v40721_previous_transcribe = FasterWhisperSTT.transcribe
            # Si el transcribe anterior era el wrapper tiny v4072, su __wrapped__ apunta al small original.
            _jarvis_v40721_small_fallback = getattr(_jarvis_v40721_previous_transcribe, "__wrapped__", _jarvis_v40721_previous_transcribe)

            def _jarvis_v40721_transcribe(self, wav_path, *args, **kwargs):
                logger = _jarvis_v40721_logging.getLogger("jarvis")

                if _jarvis_v40721_os.environ.get("JARVIS_FAST_STT_DISABLE", "").strip() == "1":
                    return _jarvis_v40721_small_fallback(self, wav_path, *args, **kwargs)

                if _jarvis_v40721_os.environ.get("JARVIS_FAST_STT_FUZZY_DISABLE", "").strip() == "1":
                    return _jarvis_v40721_small_fallback(self, wav_path, *args, **kwargs)

                tiny_fn = globals().get("_jarvis_v4072_transcribe_tiny")
                if callable(tiny_fn):
                    start = _jarvis_v40721_time.monotonic()
                    tiny_text, tiny_ms = tiny_fn(wav_path, logger=logger)
                    canonical = _jarvis_v40721_canonical_fast_reply(tiny_text)

                    if canonical:
                        total_ms = int((_jarvis_v40721_time.monotonic() - start) * 1000)
                        logger.info(
                            "FAST_STT tiny fuzzy usado raw=%r canonical=%r tiny_ms=%s total_ms=%s",
                            tiny_text,
                            canonical,
                            tiny_ms,
                            total_ms,
                        )
                        _jarvis_v40721_publish(
                            "stt.fast_tiny.fuzzy_used",
                            {
                                "raw": tiny_text,
                                "canonical": canonical,
                                "tiny_ms": tiny_ms,
                                "total_ms": total_ms,
                            },
                        )
                        return canonical

                    logger.info("FAST_STT tiny fuzzy miss raw=%r tiny_ms=%s; usando small fallback", tiny_text, tiny_ms)
                    _jarvis_v40721_publish(
                        "stt.fast_tiny.fuzzy_miss",
                        {"raw": tiny_text, "tiny_ms": tiny_ms},
                    )

                # Importante: caer al small original, no al wrapper tiny viejo, para evitar tiny doble.
                return _jarvis_v40721_small_fallback(self, wav_path, *args, **kwargs)

            _jarvis_v40721_transcribe.__jarvis_v40721_tiny_fuzzy__ = True
            _jarvis_v40721_transcribe.__wrapped__ = _jarvis_v40721_small_fallback
            FasterWhisperSTT.transcribe = _jarvis_v40721_transcribe

except Exception:
    pass
# === JARVIS_V4072_1_STT_TINY_FUZZY_FAST_REPLY_END ===

# === JARVIS_V4077_STT_BASE_SAFE_FAST_REPLY_BEGIN ===
# Jarvis v4.0.7.7
# STT base-safe:
# - usa faster-whisper base/int8 como primera pasada rápida
# - SOLO acepta fast replies claras
# - si la transcripción base es ambigua, cae al small actual
try:
    import os as _jarvis_v4077_os
    import re as _jarvis_v4077_re
    import time as _jarvis_v4077_time
    import logging as _jarvis_v4077_logging

    _JARVIS_V4077_BASE_MODEL = None
    _JARVIS_V4077_BASE_KEY = None

    def _jarvis_v4077_publish(topic, payload):
        try:
            from jarvis.bus.event_bus import EventBus
            EventBus().publish(topic, payload, source="stt_base_safe_fast_reply")
        except Exception:
            pass

    def _jarvis_v4077_norm(text):
        text = str(text or "").strip().lower()
        for a, b in {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "¿": "", "?": "", "¡": "", "!": "",
        }.items():
            text = text.replace(a, b)
        text = _jarvis_v4077_re.sub(r"[^a-z0-9ñ\s]", " ", text)
        text = _jarvis_v4077_re.sub(r"\s+", " ", text).strip()
        return text

    def _jarvis_v4077_base_model(logger=None):
        global _JARVIS_V4077_BASE_MODEL, _JARVIS_V4077_BASE_KEY
        logger = logger or _jarvis_v4077_logging.getLogger("jarvis")

        model_size = _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_MODEL", "base")
        device = _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_DEVICE", "cpu")
        compute = _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_COMPUTE", "int8")
        key = (model_size, device, compute)

        if _JARVIS_V4077_BASE_MODEL is not None and _JARVIS_V4077_BASE_KEY == key:
            return _JARVIS_V4077_BASE_MODEL

        try:
            from faster_whisper import WhisperModel
            start = _jarvis_v4077_time.monotonic()
            logger.info("BASE_STT cargando modelo=%s device=%s compute=%s", model_size, device, compute)
            _JARVIS_V4077_BASE_MODEL = WhisperModel(model_size, device=device, compute_type=compute)
            _JARVIS_V4077_BASE_KEY = key
            elapsed_ms = int((_jarvis_v4077_time.monotonic() - start) * 1000)
            logger.info("BASE_STT cargado elapsed_ms=%s key=%s", elapsed_ms, key)
            _jarvis_v4077_publish("stt.base_fast.loaded", {"elapsed_ms": elapsed_ms, "key": str(key)})
            return _JARVIS_V4077_BASE_MODEL
        except Exception as exc:
            logger.warning("BASE_STT no pudo cargar: %s", exc)
            _jarvis_v4077_publish("stt.base_fast.load_failed", {"error": str(exc), "key": str(key)})
            return None

    def jarvis_preload_base_fast_stt(logger=None):
        logger = logger or _jarvis_v4077_logging.getLogger("jarvis")
        if _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_DISABLE", "").strip() == "1":
            return False
        model = _jarvis_v4077_base_model(logger=logger)
        ok = model is not None
        logger.info("BASE_STT preload listo ok=%s", ok)
        return bool(ok)

    def _jarvis_v4077_canonical_fast_reply(text):
        n = _jarvis_v4077_norm(text)
        if not n:
            return None

        # No aceptar comandos de acción por base-safe.
        complex_words = (
            "abre", "abrir", "busca", "buscar", "borra", "elimina", "ejecuta",
            "instala", "descarga", "reproduce", "youtube", "archivo", "carpeta",
            "build", "aab", "apk", "servicio", "jellyfin", "immich", "terminal",
            "navegador", "chrome"
        )
        if any(_jarvis_v4077_re.search(rf"\b{_jarvis_v4077_re.escape(w)}\b", n) for w in complex_words):
            return None

        # Hora: SOLO señales claras. No aceptamos "dime que eres", porque base lo confunde
        # tanto con "hora es" como con "era eso".
        time_patterns = [
            r"\b(dime\s+)?(que\s+)?hora\s+es\b",
            r"\b(dime\s+)?(que\s+)?horas\s+son\b",
            r"\b(dime\s+)?(que\s+)?ahora\s+es\b",
            r"\b(dime\s+)?(que\s+)?ahora\s+son\b",
            r"\bla\s+hora\b",
        ]
        if any(_jarvis_v4077_re.search(p, n) for p in time_patterns):
            return "dime qué hora es"

        # Presencia.
        if _jarvis_v4077_re.search(r"\b(estas|esta|sigues|sigue)\s+(ahi|hay|ai)\b", n):
            return "estás ahí"

        # Gracias.
        if _jarvis_v4077_re.search(r"\b(muchas\s+)?gracias\b", n):
            return "gracias"

        # Saludos claros.
        if _jarvis_v4077_re.search(r"^(hey|oye)\s+jarvis$", n):
            return "hola jarvis"
        if _jarvis_v4077_re.search(r"^hola(\s+jarvis)?$", n):
            return "hola jarvis"
        if _jarvis_v4077_re.search(r"^(buenos\s+dias|buenas\s+tardes|buenas\s+noches)$", n):
            return "hola jarvis"

        # Capacidades.
        if _jarvis_v4077_re.search(r"\b(que|ke)\s+(puedes|sabes)\s+hacer\b", n):
            return "qué puedes hacer"

        # Fecha.
        if _jarvis_v4077_re.search(r"\b(que|ke)\s+(fecha|dia)\s+es\b", n):
            return "qué fecha es"

        return None

    def _jarvis_v4077_transcribe_base(wav_path, logger=None):
        logger = logger or _jarvis_v4077_logging.getLogger("jarvis")
        model = _jarvis_v4077_base_model(logger=logger)
        if model is None:
            return "", 0

        path = wav_path
        try:
            trim_fn = globals().get("_jarvis_v4064_trim_wav_for_stt")
            if callable(trim_fn):
                path = trim_fn(wav_path)
        except Exception:
            path = wav_path

        start = _jarvis_v4077_time.monotonic()
        text = ""
        try:
            initial_prompt = _jarvis_v4077_os.environ.get(
                "JARVIS_BASE_STT_PROMPT",
                "Frases comunes: dime qué hora es. dime qué era eso. estás ahí. gracias. hola jarvis."
            )
            segments, info = model.transcribe(
                str(path),
                language="es",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=160),
                beam_size=1,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
            )
            parts = []
            for seg in segments:
                try:
                    parts.append(str(seg.text or "").strip())
                except Exception:
                    pass
            text = " ".join([p for p in parts if p]).strip()
        except Exception as exc:
            logger.warning("BASE_STT transcribe falló: %s", exc)
            _jarvis_v4077_publish("stt.base_fast.failed", {"error": str(exc)})
            text = ""

        elapsed_ms = int((_jarvis_v4077_time.monotonic() - start) * 1000)
        logger.info("BASE_STT result elapsed_ms=%s text=%r", elapsed_ms, text)
        _jarvis_v4077_publish("stt.base_fast.result", {"elapsed_ms": elapsed_ms, "text": text})
        return text, elapsed_ms

    if "FasterWhisperSTT" in globals() and hasattr(FasterWhisperSTT, "transcribe"):
        if not getattr(FasterWhisperSTT.transcribe, "__jarvis_v4077_base_safe__", False):
            _jarvis_v4077_prev_transcribe = FasterWhisperSTT.transcribe

            def _jarvis_v4077_base_safe_transcribe(self, wav_path, *args, **kwargs):
                logger = _jarvis_v4077_logging.getLogger("jarvis")

                if _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_DISABLE", "").strip() == "1":
                    return _jarvis_v4077_prev_transcribe(self, wav_path, *args, **kwargs)

                text, elapsed_ms = _jarvis_v4077_transcribe_base(wav_path, logger=logger)
                canonical = _jarvis_v4077_canonical_fast_reply(text)

                if canonical:
                    logger.info(
                        "BASE_STT usado para fast_reply raw=%r canonical=%r elapsed_ms=%s",
                        text,
                        canonical,
                        elapsed_ms,
                    )
                    _jarvis_v4077_publish(
                        "stt.base_fast.used",
                        {"raw": text, "canonical": canonical, "elapsed_ms": elapsed_ms},
                    )
                    return canonical

                logger.info("BASE_STT miss; usando small actual raw=%r elapsed_ms=%s", text, elapsed_ms)
                _jarvis_v4077_publish("stt.base_fast.miss", {"raw": text, "elapsed_ms": elapsed_ms})
                return _jarvis_v4077_prev_transcribe(self, wav_path, *args, **kwargs)

            _jarvis_v4077_base_safe_transcribe.__jarvis_v4077_base_safe__ = True
            _jarvis_v4077_base_safe_transcribe.__wrapped__ = _jarvis_v4077_prev_transcribe
            FasterWhisperSTT.transcribe = _jarvis_v4077_base_safe_transcribe

except Exception:
    pass
# === JARVIS_V4077_STT_BASE_SAFE_FAST_REPLY_END ===

# === JARVIS_V4083_BASE_STT_HELP_CANONICAL_BEGIN ===
# Jarvis v4.0.8.3
# Enseña a base-safe que "ayúzame" / "ayuda a mi" equivale a "ayúdame".
try:
    import re as _jarvis_v4083_re

    def _jarvis_v4083_norm(text):
        t = str(text or "").strip().lower()
        repl = {"á":"a","é":"e","í":"i","ó":"o","ú":"u","¿":"","?":"","¡":"","!":""}
        for a, b in repl.items():
            t = t.replace(a, b)
        t = _jarvis_v4083_re.sub(r"[^a-z0-9ñ\s]", " ", t)
        t = _jarvis_v4083_re.sub(r"\s+", " ", t).strip()
        return t

    if "_jarvis_v4077_canonical_fast_reply" in globals():
        _jarvis_v4083_prev_canonical = _jarvis_v4077_canonical_fast_reply

        def _jarvis_v4077_canonical_fast_reply(text):
            n = _jarvis_v4083_norm(text)
            help_patterns = [
                r"^ayudame$",
                r"^ayudame por favor$",
                r"^ayuzame$",
                r"^ayusame$",
                r"^necesito ayuda$",
                r"^ayuda a mi$",
                r"^ocup[oó] ayuda$",
            ]
            if any(_jarvis_v4083_re.search(p, n) for p in help_patterns):
                return "ayudame"
            return _jarvis_v4083_prev_canonical(text)

        _jarvis_v4077_canonical_fast_reply.__jarvis_v4083_help__ = True
        _jarvis_v4077_canonical_fast_reply.__wrapped__ = _jarvis_v4083_prev_canonical

except Exception:
    pass
# === JARVIS_V4083_BASE_STT_HELP_CANONICAL_END ===

# === JARVIS_V4084_BASE_STT_SHORT_ONLY_BEGIN ===
# Jarvis v4.0.8.4
# BASE_STT solo para clips cortos. Evita perder segundos en audios más largos.
try:
    import os as _jarvis_v4084_os
    import wave as _jarvis_v4084_wave
    import logging as _jarvis_v4084_logging

    def _jarvis_v4084_int_env(name, default):
        raw = _jarvis_v4084_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _jarvis_v4084_short_audio_ok(wav_path):
        max_ms = _jarvis_v4084_int_env("JARVIS_BASE_STT_MAX_AUDIO_MS", 900)
        max_bytes = _jarvis_v4084_int_env("JARVIS_BASE_STT_MAX_BYTES", 90000)

        try:
            size = int(getattr(wav_path, "stat", lambda: None)().st_size) if hasattr(wav_path, "stat") else None
        except Exception:
            size = None

        try:
            import pathlib as _pathlib
            p = _pathlib.Path(wav_path)
            size = p.stat().st_size
        except Exception:
            pass

        if size is not None and size > max_bytes:
            return False, {"reason": "bytes", "size": int(size), "max_bytes": int(max_bytes)}

        try:
            with _jarvis_v4084_wave.open(str(wav_path), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate() or 16000
                dur_ms = int((frames / float(rate)) * 1000)
        except Exception:
            dur_ms = None

        if dur_ms is not None and dur_ms > max_ms:
            return False, {"reason": "duration_ms", "duration_ms": int(dur_ms), "max_ms": int(max_ms), "size": int(size or 0)}

        return True, {"duration_ms": dur_ms, "size": int(size or 0), "max_ms": int(max_ms), "max_bytes": int(max_bytes)}

    if "FasterWhisperSTT" in globals() and hasattr(FasterWhisperSTT, "transcribe"):
        if not getattr(FasterWhisperSTT.transcribe, "__jarvis_v4084_short_only__", False):
            _jarvis_v4084_prev_transcribe = FasterWhisperSTT.transcribe
            _jarvis_v4084_small_fallback = getattr(_jarvis_v4084_prev_transcribe, "__wrapped__", _jarvis_v4084_prev_transcribe)

            def _jarvis_v4084_transcribe(self, wav_path, *args, **kwargs):
                logger = _jarvis_v4084_logging.getLogger("jarvis")

                if _jarvis_v4084_os.environ.get("JARVIS_BASE_STT_DISABLE", "").strip() == "1":
                    return _jarvis_v4084_small_fallback(self, wav_path, *args, **kwargs)

                try:
                    trim_fn = globals().get("_jarvis_v4064_trim_wav_for_stt")
                    probe_path = trim_fn(wav_path) if callable(trim_fn) else wav_path
                except Exception:
                    probe_path = wav_path

                ok, meta = _jarvis_v4084_short_audio_ok(probe_path)
                if not ok:
                    try:
                        logger.info("BASE_STT short-only skip meta=%s", meta)
                    except Exception:
                        pass
                    try:
                        from jarvis.bus.event_bus import EventBus
                        EventBus().publish("stt.base_fast.short_skip", meta, source="base_stt_short_only")
                    except Exception:
                        pass
                    return _jarvis_v4084_small_fallback(self, wav_path, *args, **kwargs)

                return _jarvis_v4084_prev_transcribe(self, wav_path, *args, **kwargs)

            _jarvis_v4084_transcribe.__jarvis_v4084_short_only__ = True
            _jarvis_v4084_transcribe.__wrapped__ = _jarvis_v4084_small_fallback
            FasterWhisperSTT.transcribe = _jarvis_v4084_transcribe

except Exception:
    pass
# === JARVIS_V4084_BASE_STT_SHORT_ONLY_END ===

# === JARVIS_V4136_STT_SHORT_TUNE_BEGIN ===
# Jarvis v4.1.3.6
# Ajusta defaults para frases cortas: menos recorte agresivo y BASE_STT útil en clips breves un poco más grandes.
try:
    import os as _jarvis_v4136stt_os
    import logging as _jarvis_v4136stt_logging

    if 'FasterWhisperSTT' in globals() and hasattr(FasterWhisperSTT, 'transcribe'):
        _jarvis_v4136stt_prev = FasterWhisperSTT.transcribe
        if not getattr(_jarvis_v4136stt_prev, '__jarvis_v4136_short_tune__', False):
            def transcribe(self, wav_path, *args, **kwargs):
                logger = _jarvis_v4136stt_logging.getLogger('jarvis')
                restore = {}
                defaults = {
                    'JARVIS_STT_TRIM_PAD_MS': '240',
                    'JARVIS_STT_TRIM_MIN_KEEP_MS': '700',
                    'JARVIS_BASE_STT_MAX_AUDIO_MS': '1200',
                    'JARVIS_BASE_STT_MAX_BYTES': '120000',
                }
                try:
                    for key, value in defaults.items():
                        raw = _jarvis_v4136stt_os.environ.get(key)
                        if raw is None or str(raw).strip() == '':
                            restore[key] = None
                            _jarvis_v4136stt_os.environ[key] = value
                    logger.info(
                        'STT_SHORT_TUNE pad_ms=%s min_keep_ms=%s base_max_ms=%s base_max_bytes=%s',
                        _jarvis_v4136stt_os.environ.get('JARVIS_STT_TRIM_PAD_MS'),
                        _jarvis_v4136stt_os.environ.get('JARVIS_STT_TRIM_MIN_KEEP_MS'),
                        _jarvis_v4136stt_os.environ.get('JARVIS_BASE_STT_MAX_AUDIO_MS'),
                        _jarvis_v4136stt_os.environ.get('JARVIS_BASE_STT_MAX_BYTES'),
                    )
                except Exception:
                    restore = {}
                try:
                    return _jarvis_v4136stt_prev(self, wav_path, *args, **kwargs)
                finally:
                    for key, old in restore.items():
                        if old is None:
                            _jarvis_v4136stt_os.environ.pop(key, None)
                        else:
                            _jarvis_v4136stt_os.environ[key] = old

            transcribe.__jarvis_v4136_short_tune__ = True
            transcribe.__wrapped__ = _jarvis_v4136stt_prev
            FasterWhisperSTT.transcribe = transcribe
except Exception:
    pass
# === JARVIS_V4136_STT_SHORT_TUNE_END ===
