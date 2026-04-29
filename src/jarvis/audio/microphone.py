from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io.wavfile import write as wav_write

from jarvis.utils.paths import ensure_dir

class MicrophoneError(RuntimeError):
    pass

class Microphone:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        audio = config.get('audio', {})
        self.sample_rate = int(audio.get('sample_rate', 16000))
        self.channels = int(audio.get('channels', 1))
        self.input_device = audio.get('input_device', 'default')
        self.min_voice_energy = float(audio.get('min_voice_energy', 0.011))

    def _device_arg(self):
        return None if self.input_device in (None, '', 'default') else self.input_device

    def list_devices(self) -> str:
        try:
            import sounddevice as sd
            return str(sd.query_devices())
        except Exception as exc:
            raise MicrophoneError(f'No se pudieron listar dispositivos de audio: {exc}') from exc

    def record_seconds(self, seconds: float, out_path: str | Path) -> Path:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise MicrophoneError('sounddevice no está instalado o PortAudio falló.') from exc
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        frames = int(seconds * self.sample_rate)
        audio = sd.rec(
            frames,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype='float32',
            device=self._device_arg(),
        )
        sd.wait()
        return self._save_wav(out, audio)

    def record_until_silence(self, out_path: str | Path, max_seconds: float | None = None, silence_seconds: float | None = None) -> Path:
        try:
            import sounddevice as sd
        except Exception as exc:
            raise MicrophoneError('sounddevice no está instalado o PortAudio falló.') from exc
        audio_cfg = self.config.get('audio', {})
        max_seconds = float(max_seconds or audio_cfg.get('max_command_seconds', 15))
        silence_seconds = float(silence_seconds or audio_cfg.get('silence_timeout_seconds', 1.2))
        block_duration = float(audio_cfg.get('vad_block_seconds', 0.05))
        block_frames = int(self.sample_rate * block_duration)
        started = False
        silent_for = 0.0
        chunks: list[np.ndarray] = []
        start_time = time.monotonic()

        def callback(indata, frames, callback_time, status):  # noqa: ANN001
            nonlocal started, silent_for
            data = indata.copy()
            chunks.append(data)
            energy = float(np.sqrt(np.mean(np.square(data))) if data.size else 0.0)
            if energy >= self.min_voice_energy:
                started = True
                silent_for = 0.0
            elif started:
                silent_for += block_duration

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype='float32',
                blocksize=block_frames,
                device=self._device_arg(),
                callback=callback,
            ):
                while time.monotonic() - start_time < max_seconds:
                    time.sleep(block_duration)
                    if started and silent_for >= silence_seconds:
                        break
        except Exception as exc:
            raise MicrophoneError(f'No se pudo grabar audio: {exc}') from exc

        if not chunks:
            raise MicrophoneError('No se capturó audio.')
        audio = np.concatenate(chunks, axis=0)
        return self._save_wav(out_path, audio)

    def _save_wav(self, out_path: str | Path, audio: np.ndarray) -> Path:
        out = Path(out_path).expanduser()
        ensure_dir(out.parent)
        audio = np.asarray(audio)
        if audio.dtype != np.int16:
            audio = np.clip(audio, -1.0, 1.0)
            audio = (audio * 32767).astype(np.int16)
        wav_write(str(out), self.sample_rate, audio)
        return out

# === JARVIS_V4062_LATENCY_MICROPHONE_BEGIN ===
# Jarvis v4.0.6.2 latency profiler: wrapper no destructivo para Microphone.
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

    if "Microphone" in globals() and hasattr(Microphone, "record_until_silence"):
        if not getattr(Microphone.record_until_silence, "__jarvis_v4062_latency__", False):
            _jarvis_v4062_original_record_until_silence = Microphone.record_until_silence

            def _jarvis_v4062_record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4062_logging.getLogger("jarvis")
                audio_cfg = {}
                try:
                    audio_cfg = getattr(self, "config", {}).get("audio", {}) or {}
                except Exception:
                    audio_cfg = {}

                try:
                    max_cfg = float(max_seconds or audio_cfg.get("max_command_seconds", 15))
                except Exception:
                    max_cfg = max_seconds

                try:
                    silence_cfg = float(silence_seconds or audio_cfg.get("silence_timeout_seconds", 1.2))
                except Exception:
                    silence_cfg = silence_seconds

                try:
                    block_cfg = float(audio_cfg.get("vad_block_seconds", 0.05))
                except Exception:
                    block_cfg = None

                start = _jarvis_v4062_time.monotonic()
                logger.info(
                    "LATENCY record.start path=%s max_seconds=%s silence_seconds=%s vad_block_seconds=%s sample_rate=%s",
                    out_path,
                    max_cfg,
                    silence_cfg,
                    block_cfg,
                    getattr(self, "sample_rate", None),
                )

                ok = False
                err = None
                try:
                    result = _jarvis_v4062_original_record_until_silence(
                        self,
                        out_path,
                        max_seconds=max_seconds,
                        silence_seconds=silence_seconds,
                    )
                    ok = True
                    return result
                except Exception as exc:
                    err = str(exc)
                    raise
                finally:
                    elapsed_ms = int((_jarvis_v4062_time.monotonic() - start) * 1000)
                    size = None
                    try:
                        p = _jarvis_v4062_Path(out_path)
                        if p.exists():
                            size = p.stat().st_size
                    except Exception:
                        pass

                    logger.info(
                        "LATENCY record.done elapsed_ms=%s ok=%s bytes=%s error=%s",
                        elapsed_ms,
                        ok,
                        size,
                        err or "",
                    )
                    _jarvis_v4062_emit_latency(
                        "latency.record",
                        f"{elapsed_ms} ms",
                        {
                            "elapsed_ms": elapsed_ms,
                            "ok": ok,
                            "bytes": size,
                            "error": err,
                            "max_seconds": max_cfg,
                            "silence_seconds": silence_cfg,
                            "vad_block_seconds": block_cfg,
                        },
                    )

            _jarvis_v4062_record_until_silence.__jarvis_v4062_latency__ = True
            _jarvis_v4062_record_until_silence.__wrapped__ = _jarvis_v4062_original_record_until_silence
            Microphone.record_until_silence = _jarvis_v4062_record_until_silence

except Exception:
    pass
# === JARVIS_V4062_LATENCY_MICROPHONE_END ===

# === JARVIS_V4073_RECORDER_FAST_CUT_BEGIN ===
# Jarvis v4.0.7.3
# Ajuste no destructivo: fuerza parámetros más rápidos de grabación si el llamador no los pasa.
try:
    import os as _jarvis_v4073_os
    import logging as _jarvis_v4073_logging

    def _jarvis_v4073_float_env(name, default):
        raw = _jarvis_v4073_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return float(raw)
        except Exception:
            return default

    def _jarvis_v4073_get_audio_cfg(self_obj):
        try:
            cfg = getattr(self_obj, "config", None)
            if isinstance(cfg, dict):
                return cfg.get("audio", {}) or {}
        except Exception:
            pass
        return {}

    if "Microphone" in globals() and hasattr(Microphone, "record_until_silence"):
        if not getattr(Microphone.record_until_silence, "__jarvis_v4073_fast_cut__", False):
            _jarvis_v4073_original_record_until_silence = Microphone.record_until_silence

            def _jarvis_v4073_record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4073_logging.getLogger("jarvis")
                audio_cfg = _jarvis_v4073_get_audio_cfg(self)

                try:
                    cfg_max = float(audio_cfg.get("max_command_seconds", 4.0))
                except Exception:
                    cfg_max = 4.0

                try:
                    cfg_silence = float(audio_cfg.get("silence_timeout_seconds", 0.38))
                except Exception:
                    cfg_silence = 0.38

                target_max = _jarvis_v4073_float_env("JARVIS_RECORD_MAX_SECONDS", cfg_max)
                target_silence = _jarvis_v4073_float_env("JARVIS_RECORD_SILENCE_SECONDS", cfg_silence)

                # Solo apretamos si no se pasó nada o si venía más lento.
                if max_seconds is None:
                    max_seconds = target_max
                else:
                    try:
                        max_seconds = min(float(max_seconds), float(target_max))
                    except Exception:
                        pass

                if silence_seconds is None:
                    silence_seconds = target_silence
                else:
                    try:
                        silence_seconds = min(float(silence_seconds), float(target_silence))
                    except Exception:
                        pass

                try:
                    logger.info(
                        "RECORDER_FAST_CUT max_seconds=%s silence_seconds=%s env_max=%s env_silence=%s",
                        max_seconds,
                        silence_seconds,
                        _jarvis_v4073_os.environ.get("JARVIS_RECORD_MAX_SECONDS", ""),
                        _jarvis_v4073_os.environ.get("JARVIS_RECORD_SILENCE_SECONDS", ""),
                    )
                except Exception:
                    pass

                return _jarvis_v4073_original_record_until_silence(
                    self,
                    out_path,
                    max_seconds=max_seconds,
                    silence_seconds=silence_seconds,
                )

            _jarvis_v4073_record_until_silence.__jarvis_v4073_fast_cut__ = True
            _jarvis_v4073_record_until_silence.__wrapped__ = _jarvis_v4073_original_record_until_silence
            Microphone.record_until_silence = _jarvis_v4073_record_until_silence

except Exception:
    pass
# === JARVIS_V4073_RECORDER_FAST_CUT_END ===

# === JARVIS_V4079_RECORDER_PHASE3_WRAPPER_BEGIN ===
# Jarvis v4.0.7.9
# Endurece límites de grabación para reducir "comando vacío" largo.
try:
    import os as _jarvis_v4079_os
    import logging as _jarvis_v4079_logging

    def _jarvis_v4079_float_env(name, default):
        raw = _jarvis_v4079_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            return float(raw)
        except Exception:
            return default

    if "Microphone" in globals() and hasattr(Microphone, "record_until_silence"):
        if not getattr(Microphone.record_until_silence, "__jarvis_v4079_phase3__", False):
            _jarvis_v4079_prev_record_until_silence = Microphone.record_until_silence

            def _jarvis_v4079_record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4079_logging.getLogger("jarvis")
                target_max = _jarvis_v4079_float_env("JARVIS_RECORD_MAX_SECONDS", 3.2)
                target_silence = _jarvis_v4079_float_env("JARVIS_RECORD_SILENCE_SECONDS", 0.34)

                if max_seconds is None:
                    max_seconds = target_max
                else:
                    try:
                        max_seconds = min(float(max_seconds), target_max)
                    except Exception:
                        pass

                if silence_seconds is None:
                    silence_seconds = target_silence
                else:
                    try:
                        silence_seconds = min(float(silence_seconds), target_silence)
                    except Exception:
                        pass

                try:
                    logger.info(
                        "RECORDER_PHASE3 max_seconds=%s silence_seconds=%s env_max=%s env_silence=%s",
                        max_seconds,
                        silence_seconds,
                        _jarvis_v4079_os.environ.get("JARVIS_RECORD_MAX_SECONDS", ""),
                        _jarvis_v4079_os.environ.get("JARVIS_RECORD_SILENCE_SECONDS", ""),
                    )
                except Exception:
                    pass

                return _jarvis_v4079_prev_record_until_silence(
                    self,
                    out_path,
                    max_seconds=max_seconds,
                    silence_seconds=silence_seconds,
                )

            _jarvis_v4079_record_until_silence.__jarvis_v4079_phase3__ = True
            _jarvis_v4079_record_until_silence.__wrapped__ = _jarvis_v4079_prev_record_until_silence
            Microphone.record_until_silence = _jarvis_v4079_record_until_silence

except Exception:
    pass
# === JARVIS_V4079_RECORDER_PHASE3_WRAPPER_END ===

# === JARVIS_V4094_MIC_SAMPLE_RATE_FORCE_BEGIN ===
# Jarvis v4.0.9.4
# Fuerza sample_rate 16000 y un blocksize más estable cuando sea posible.
try:
    import os as _jarvis_v4094_os
    import logging as _jarvis_v4094_logging

    def _jarvis_v4094_env_int(name: str, default: int) -> int:
        raw = _jarvis_v4094_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    if "Microphone" in globals():
        _orig_init = getattr(Microphone, "__init__", None)
        if callable(_orig_init) and not getattr(_orig_init, "__jarvis_v4094_sr__", False):
            def __init__(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                logger = _jarvis_v4094_logging.getLogger("jarvis")
                try:
                    forced_sr = _jarvis_v4094_env_int("JARVIS_AUDIO_SAMPLE_RATE", 48000)
                    if hasattr(self, "sample_rate"):
                        self.sample_rate = forced_sr
                    if hasattr(self, "channels") and int(getattr(self, "channels", 1) or 1) < 1:
                        self.channels = 1
                    if hasattr(self, "blocksize"):
                        self.blocksize = _jarvis_v4094_env_int("JARVIS_AUDIO_BLOCKSIZE", 2048)
                    logger.info(
                        "MIC_FORCE sample_rate=%s blocksize=%s channels=%s",
                        getattr(self, "sample_rate", None),
                        getattr(self, "blocksize", None),
                        getattr(self, "channels", None),
                    )
                except Exception as exc:
                    try:
                        logger.warning("MIC_FORCE no pudo ajustar sample_rate/blocksize: %s", exc)
                    except Exception:
                        pass
            __init__.__jarvis_v4094_sr__ = True
            __init__.__wrapped__ = _orig_init
            Microphone.__init__ = __init__
except Exception:
    pass
# === JARVIS_V4094_MIC_SAMPLE_RATE_FORCE_END ===

# === JARVIS_V4096_MIC_RETRY_SAMPLE_RATE_BEGIN ===
# Jarvis v4.0.9.6
# Si el recorder falla por sample rate inválido, reintenta varios sample rates conocidos.
try:
    import os as _jarvis_v4096_os
    import logging as _jarvis_v4096_logging

    def _jarvis_v4096_int_env(name: str, default: int) -> int:
        raw = _jarvis_v4096_os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _jarvis_v4096_is_invalid_rate_error(exc: Exception) -> bool:
        low = str(exc or "").lower()
        return "invalid sample rate" in low or "paerrorcode -9997" in low or "painvalidsamplerate" in low

    def _jarvis_v4096_patch_mic():
        if "Microphone" not in globals():
            return

        _orig_init = getattr(Microphone, "__init__", None)
        if callable(_orig_init) and not getattr(_orig_init, "__jarvis_v4096_retry__", False):
            def __init__(self, *args, **kwargs):
                _orig_init(self, *args, **kwargs)
                logger = _jarvis_v4096_logging.getLogger("jarvis")
                try:
                    self.sample_rate = _jarvis_v4096_int_env("JARVIS_AUDIO_SAMPLE_RATE", 48000)
                    if hasattr(self, "blocksize"):
                        self.blocksize = _jarvis_v4096_int_env("JARVIS_AUDIO_BLOCKSIZE", 2048)
                    if hasattr(self, "channels"):
                        self.channels = 1
                    logger.info(
                        "MIC_RETRY_FORCE sample_rate=%s blocksize=%s channels=%s",
                        getattr(self, "sample_rate", None),
                        getattr(self, "blocksize", None),
                        getattr(self, "channels", None),
                    )
                except Exception as exc:
                    try:
                        logger.warning("MIC_RETRY_FORCE no pudo ajustar inicio: %s", exc)
                    except Exception:
                        pass
            __init__.__jarvis_v4096_retry__ = True
            __init__.__wrapped__ = _orig_init
            Microphone.__init__ = __init__

        _orig_record = getattr(Microphone, "record_until_silence", None)
        if callable(_orig_record) and not getattr(_orig_record, "__jarvis_v4096_retry__", False):
            def record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4096_logging.getLogger("jarvis")
                rates = []
                for v in [
                    _jarvis_v4096_int_env("JARVIS_AUDIO_SAMPLE_RATE", 48000),
                    getattr(self, "sample_rate", None),
                    48000, 44100, 32000, 16000,
                ]:
                    try:
                        iv = int(v)
                    except Exception:
                        continue
                    if iv > 0 and iv not in rates:
                        rates.append(iv)

                last_exc = None
                for idx, rate in enumerate(rates, start=1):
                    try:
                        self.sample_rate = rate
                    except Exception:
                        pass
                    try:
                        logger.info("MIC_SR_RETRY intento=%s/%s rate=%s", idx, len(rates), rate)
                    except Exception:
                        pass
                    try:
                        return _orig_record(self, out_path, max_seconds=max_seconds, silence_seconds=silence_seconds)
                    except Exception as exc:
                        last_exc = exc
                        if _jarvis_v4096_is_invalid_rate_error(exc):
                            try:
                                logger.warning("MIC_SR_RETRY rate=%s rechazado: %s", rate, exc)
                            except Exception:
                                pass
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc
                return _orig_record(self, out_path, max_seconds=max_seconds, silence_seconds=silence_seconds)

            record_until_silence.__jarvis_v4096_retry__ = True
            record_until_silence.__wrapped__ = _orig_record
            Microphone.record_until_silence = record_until_silence

    _jarvis_v4096_patch_mic()

except Exception:
    pass
# === JARVIS_V4096_MIC_RETRY_SAMPLE_RATE_END ===

# === JARVIS_V4125_MICROPHONE_DEVICE_RESOLVER_V2_BEGIN ===
# Jarvis v4.1.2.5
# Corrige el resolver de input_device para recorder/microphone.
try:
    import logging as _jarvis_v4125m_logging
    import os as _jarvis_v4125m_os
    import sounddevice as _jarvis_v4125m_sd

    def _jarvis_v4125m_norm_device(value):
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

    def _jarvis_v4125m_all_devices():
        try:
            return list(_jarvis_v4125m_sd.query_devices())
        except Exception:
            return []

    def _jarvis_v4125m_valid_inputs():
        out = []
        for idx, info in enumerate(_jarvis_v4125m_all_devices()):
            try:
                if int(info.get('max_input_channels', 0)) > 0:
                    out.append((idx, info))
            except Exception:
                continue
        return out

    def _jarvis_v4125m_default_input_index():
        try:
            maybe = getattr(getattr(_jarvis_v4125m_sd, 'default', None), 'device', None)
            if isinstance(maybe, (list, tuple)) and len(maybe) >= 1:
                first = maybe[0]
            else:
                first = maybe
            first = _jarvis_v4125m_norm_device(first)
            return first if isinstance(first, int) else None
        except Exception:
            return None

    def _jarvis_v4125m_choose_by_name(name):
        needle = str(name or '').strip().lower()
        if not needle:
            return None, None
        for idx, info in _jarvis_v4125m_valid_inputs():
            try:
                dev_name = str(info.get('name', '')).lower()
                if needle in dev_name:
                    return idx, f'name_match:{needle}'
            except Exception:
                continue
        return None, None

    def _jarvis_v4125m_pick_input_device(preferred=None):
        preferred = _jarvis_v4125m_norm_device(preferred)
        explicit_name = _jarvis_v4125m_os.environ.get('JARVIS_INPUT_DEVICE_NAME')
        valid_inputs = _jarvis_v4125m_valid_inputs()
        valid_indexes = {idx for idx, _info in valid_inputs}

        if explicit_name:
            idx, reason = _jarvis_v4125m_choose_by_name(explicit_name)
            if idx is not None:
                return idx, reason

        if isinstance(preferred, int):
            if preferred in valid_indexes:
                return preferred, 'preferred_index_valid'
        elif isinstance(preferred, str) and preferred not in (None, ''):
            idx, reason = _jarvis_v4125m_choose_by_name(preferred)
            if idx is not None:
                return idx, reason

        default_in = _jarvis_v4125m_default_input_index()
        if isinstance(default_in, int) and default_in in valid_indexes:
            return default_in, 'default_input_index'

        if valid_inputs:
            return valid_inputs[0][0], 'first_valid_input'

        return None, 'portaudio_default'

    if 'Microphone' in globals() and hasattr(Microphone, '_device_arg'):
        _jarvis_v4125m_orig_device_arg = Microphone._device_arg
        if not getattr(_jarvis_v4125m_orig_device_arg, '__jarvis_v4125_device__', False):
            def _jarvis_v4125m_device_arg(self):
                logger = _jarvis_v4125m_logging.getLogger('jarvis')
                requested = getattr(self, 'input_device', None)
                chosen, reason = _jarvis_v4125m_pick_input_device(requested)
                desired = 'default' if chosen is None else chosen
                if desired != requested:
                    try:
                        self.input_device = desired
                    except Exception:
                        pass
                    logger.warning(
                        'MIC_DEVICE_FALLBACK requested=%r chosen=%r reason=%s',
                        requested,
                        getattr(self, 'input_device', None),
                        reason,
                    )
                return None if getattr(self, 'input_device', None) in (None, '', 'default') else getattr(self, 'input_device', None)
            _jarvis_v4125m_device_arg.__jarvis_v4125_device__ = True
            _jarvis_v4125m_device_arg.__wrapped__ = _jarvis_v4125m_orig_device_arg
            Microphone._device_arg = _jarvis_v4125m_device_arg
except Exception:
    pass
# === JARVIS_V4125_MICROPHONE_DEVICE_RESOLVER_V2_END ===

# === JARVIS_V4126_AUDIO_PREF_MICROPHONE_BEGIN ===
# Jarvis v4.1.2.6
# Usa preferencias persistentes de audio para recorder/STT.
try:
    import logging as _jarvis_v4126m_logging
    from jarvis.audio.device_selector import resolve_input_device as _jarvis_v4126m_resolve_input

    if 'Microphone' in globals() and hasattr(Microphone, '__init__'):
        _jarvis_v4126m_orig_init = Microphone.__init__
        if not getattr(_jarvis_v4126m_orig_init, '__jarvis_v4126_audio_pref__', False):
            def __init__(self, *args, **kwargs):
                _jarvis_v4126m_orig_init(self, *args, **kwargs)
                logger = _jarvis_v4126m_logging.getLogger('jarvis')
                result = _jarvis_v4126m_resolve_input(getattr(self, 'config', {}) or {}, role='stt', current=getattr(self, 'input_device', None))
                chosen = result.get('device', 'default')
                try:
                    self.input_device = chosen
                except Exception:
                    pass
                logger.info(
                    'AUDIO_DEVICE_SELECT role=stt requested=%r requested_name=%r chosen=%r chosen_name=%s reason=%s',
                    result.get('requested'),
                    result.get('requested_name'),
                    getattr(self, 'input_device', None),
                    result.get('name'),
                    result.get('reason'),
                )
            __init__.__jarvis_v4126_audio_pref__ = True
            __init__.__wrapped__ = _jarvis_v4126m_orig_init
            Microphone.__init__ = __init__
except Exception:
    pass
# === JARVIS_V4126_AUDIO_PREF_MICROPHONE_END ===


# === JARVIS_V4135_MICROPHONE_USB_HOTPLUG_RECOVERY_BEGIN ===
# Jarvis v4.1.3.5
# SAFE FIX: reintenta la grabación STT cuando el hub USB pierde momentáneamente
# el micrófono y vuelve a resolver el dispositivo preferido antes de reabrir.
try:
    import logging as _jarvis_v4135m_logging
    import os as _jarvis_v4135m_os
    import time as _jarvis_v4135m_time
    from jarvis.audio.device_selector import resolve_input_device as _jarvis_v4135m_resolve_input

    def _jarvis_v4135m_float_env(name: str, default: float) -> float:
        raw = _jarvis_v4135m_os.getenv(name)
        if raw is None or str(raw).strip() == '':
            return default
        try:
            return float(raw)
        except Exception:
            return default

    def _jarvis_v4135m_int_env(name: str, default: int) -> int:
        raw = _jarvis_v4135m_os.getenv(name)
        if raw is None or str(raw).strip() == '':
            return default
        try:
            return int(raw)
        except Exception:
            return default

    def _jarvis_v4135m_bool_env(name: str, default: bool) -> bool:
        raw = _jarvis_v4135m_os.getenv(name)
        if raw is None:
            return default
        return str(raw).strip().lower() not in ('0', 'false', 'no', 'off', '')

    def _jarvis_v4135m_is_recoverable_message(message: str) -> bool:
        text = str(message or '').lower()
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
            'audio hardware disappeared',
            'host error',
            'alsa',
            'usb',
        )
        return any(needle in text for needle in needles)

    def _jarvis_v4135m_refresh_input_device(self, logger):
        result = _jarvis_v4135m_resolve_input(getattr(self, 'config', {}) or {}, role='stt', current=getattr(self, 'input_device', None))
        chosen = result.get('device', 'default')
        previous = getattr(self, 'input_device', None)
        try:
            self.input_device = chosen
        except Exception:
            pass
        logger.info(
            'MIC_DEVICE_RESELECT previous=%r chosen=%r chosen_name=%s reason=%s requested=%r requested_name=%r',
            previous,
            getattr(self, 'input_device', None),
            result.get('name'),
            result.get('reason'),
            result.get('requested'),
            result.get('requested_name'),
        )
        return result

    if 'Microphone' in globals() and hasattr(Microphone, 'record_until_silence'):
        _jarvis_v4135m_orig_record_until_silence = Microphone.record_until_silence
        if not getattr(_jarvis_v4135m_orig_record_until_silence, '__jarvis_v4135_usb_hotplug__', False):
            def record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4135m_logging.getLogger('jarvis')
                enabled = _jarvis_v4135m_bool_env('JARVIS_MIC_HOTPLUG_RECOVERY', True)
                max_retries = _jarvis_v4135m_int_env('JARVIS_MIC_HOTPLUG_MAX_RETRIES', 6)
                base_backoff = _jarvis_v4135m_float_env('JARVIS_MIC_HOTPLUG_BACKOFF_SECONDS', 0.35)
                attempts = 0

                while True:
                    if enabled:
                        _jarvis_v4135m_refresh_input_device(self, logger)
                    try:
                        return _jarvis_v4135m_orig_record_until_silence(
                            self,
                            out_path,
                            max_seconds=max_seconds,
                            silence_seconds=silence_seconds,
                        )
                    except Exception as exc:
                        message = str(exc)
                        if not enabled or not _jarvis_v4135m_is_recoverable_message(message):
                            raise
                        attempts += 1
                        wait_s = min(base_backoff * max(attempts, 1), 2.0)
                        logger.warning(
                            'MIC_STREAM_RECOVERY attempt=%s/%s device=%r error=%s backoff=%.2fs',
                            attempts,
                            max_retries,
                            getattr(self, 'input_device', None),
                            message,
                            wait_s,
                        )
                        if attempts > max_retries:
                            logger.error(
                                'MIC_STREAM_RECOVERY_GIVEUP attempts=%s device=%r last_error=%s',
                                attempts,
                                getattr(self, 'input_device', None),
                                message,
                            )
                            raise
                        _jarvis_v4135m_time.sleep(wait_s)
                        continue

            record_until_silence.__jarvis_v4135_usb_hotplug__ = True
            record_until_silence.__wrapped__ = _jarvis_v4135m_orig_record_until_silence
            Microphone.record_until_silence = record_until_silence
except Exception:
    pass
# === JARVIS_V4135_MICROPHONE_USB_HOTPLUG_RECOVERY_END ===

# === JARVIS_V4136_MIC_CAPTURE_TUNE_BEGIN ===
# Jarvis v4.1.3.6
# Ajusta valores por defecto del recorder corto para no cortar demasiado pronto.
try:
    import os as _jarvis_v4136m_os
    import logging as _jarvis_v4136m_logging

    if 'Microphone' in globals() and hasattr(Microphone, 'record_until_silence'):
        _jarvis_v4136m_orig_record = Microphone.record_until_silence
        if not getattr(_jarvis_v4136m_orig_record, '__jarvis_v4136_capture_tune__', False):
            def record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4136m_logging.getLogger('jarvis')
                restore = {}
                defaults = {
                    'JARVIS_RECORD_MAX_SECONDS': '3.8',
                    'JARVIS_RECORD_SILENCE_SECONDS': '0.45',
                }
                try:
                    for key, value in defaults.items():
                        raw = _jarvis_v4136m_os.environ.get(key)
                        if raw is None or str(raw).strip() == '':
                            restore[key] = None
                            _jarvis_v4136m_os.environ[key] = value
                    logger.info(
                        'MIC_CAPTURE_TUNE max_seconds=%s silence_seconds=%s',
                        _jarvis_v4136m_os.environ.get('JARVIS_RECORD_MAX_SECONDS'),
                        _jarvis_v4136m_os.environ.get('JARVIS_RECORD_SILENCE_SECONDS'),
                    )
                except Exception:
                    restore = {}
                try:
                    return _jarvis_v4136m_orig_record(self, out_path, max_seconds=max_seconds, silence_seconds=silence_seconds)
                finally:
                    for key, old in restore.items():
                        if old is None:
                            _jarvis_v4136m_os.environ.pop(key, None)
                        else:
                            _jarvis_v4136m_os.environ[key] = old

            record_until_silence.__jarvis_v4136_capture_tune__ = True
            record_until_silence.__wrapped__ = _jarvis_v4136m_orig_record
            Microphone.record_until_silence = record_until_silence
except Exception:
    pass
# === JARVIS_V4136_MIC_CAPTURE_TUNE_END ===

# === JARVIS_V4137_MIC_CAPTURE_LENIENT_TUNE_BEGIN ===
# Jarvis v4.1.3.7
# Da un poco más de ventana para empezar a hablar y evita cortes tan bruscos.
try:
    import os as _jarvis_v4137m_os
    import logging as _jarvis_v4137m_logging

    if 'Microphone' in globals() and hasattr(Microphone, 'record_until_silence'):
        _jarvis_v4137m_prev = Microphone.record_until_silence
        if not getattr(_jarvis_v4137m_prev, '__jarvis_v4137_capture_tune__', False):
            def record_until_silence(self, out_path, max_seconds=None, silence_seconds=None):
                logger = _jarvis_v4137m_logging.getLogger('jarvis')
                restore = {}
                defaults = {
                    'JARVIS_RECORD_MAX_SECONDS': '4.2',
                    'JARVIS_RECORD_SILENCE_SECONDS': '0.60',
                }
                try:
                    for key, value in defaults.items():
                        raw = _jarvis_v4137m_os.environ.get(key)
                        if raw is None or str(raw).strip() == '':
                            restore[key] = None
                            _jarvis_v4137m_os.environ[key] = value
                    logger.info(
                        'MIC_CAPTURE_TUNE2 max_seconds=%s silence_seconds=%s',
                        _jarvis_v4137m_os.environ.get('JARVIS_RECORD_MAX_SECONDS'),
                        _jarvis_v4137m_os.environ.get('JARVIS_RECORD_SILENCE_SECONDS'),
                    )
                except Exception:
                    restore = {}
                try:
                    return _jarvis_v4137m_prev(self, out_path, max_seconds=max_seconds, silence_seconds=silence_seconds)
                finally:
                    for key, old in restore.items():
                        if old is None:
                            _jarvis_v4137m_os.environ.pop(key, None)
                        else:
                            _jarvis_v4137m_os.environ[key] = old

            record_until_silence.__jarvis_v4137_capture_tune__ = True
            record_until_silence.__wrapped__ = _jarvis_v4137m_prev
            Microphone.record_until_silence = record_until_silence
except Exception:
    pass
# === JARVIS_V4137_MIC_CAPTURE_LENIENT_TUNE_END ===
