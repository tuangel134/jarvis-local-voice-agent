from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class SpeakerError(RuntimeError):
    pass


class Speaker:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.output_device = config.get('audio', {}).get('output_device', 'default')

    def play_wav(self, path: str | Path, volume: float = 1.0) -> None:
        wav = Path(path).expanduser()
        if not wav.exists():
            raise SpeakerError(f'No existe audio: {wav}')
        try:
            import sounddevice as sd
            import soundfile as sf
            data, samplerate = sf.read(str(wav), dtype='float32')
            data = data * float(volume)
            device = None if self.output_device in (None, '', 'default') else self.output_device
            sd.play(data, samplerate=samplerate, device=device)
            sd.wait()
            return
        except Exception:
            pass
        for player in ('aplay', 'paplay', 'ffplay'):
            if shutil.which(player):
                if player == 'ffplay':
                    subprocess.run([player, '-nodisp', '-autoexit', '-loglevel', 'quiet', str(wav)], check=False)
                else:
                    subprocess.run([player, str(wav)], check=False)
                return
        raise SpeakerError('No hay reproductor WAV disponible. Instala alsa-utils, pulseaudio-utils o ffmpeg.')

# === JARVIS_V4126_AUDIO_PREF_SPEAKER_BEGIN ===
# Jarvis v4.1.2.6
# Usa preferencias persistentes de salida de audio para TTS/playback.
try:
    import logging as _jarvis_v4126s_logging
    from jarvis.audio.device_selector import resolve_output_device as _jarvis_v4126s_resolve_output

    if 'Speaker' in globals() and hasattr(Speaker, '__init__'):
        _jarvis_v4126s_orig_init = Speaker.__init__
        if not getattr(_jarvis_v4126s_orig_init, '__jarvis_v4126_audio_pref__', False):
            def __init__(self, *args, **kwargs):
                _jarvis_v4126s_orig_init(self, *args, **kwargs)
                logger = _jarvis_v4126s_logging.getLogger('jarvis')
                result = _jarvis_v4126s_resolve_output(getattr(self, 'config', {}) or {}, current=getattr(self, 'output_device', None))
                chosen = result.get('device', 'default')
                try:
                    self.output_device = chosen
                except Exception:
                    pass
                logger.info(
                    'AUDIO_DEVICE_SELECT role=tts requested=%r requested_name=%r chosen=%r chosen_name=%s reason=%s',
                    result.get('requested'),
                    result.get('requested_name'),
                    getattr(self, 'output_device', None),
                    result.get('name'),
                    result.get('reason'),
                )
            __init__.__jarvis_v4126_audio_pref__ = True
            __init__.__wrapped__ = _jarvis_v4126s_orig_init
            Speaker.__init__ = __init__
except Exception:
    pass
# === JARVIS_V4126_AUDIO_PREF_SPEAKER_END ===

# === JARVIS_V4136_OUTPUT_HOTPLUG_RECOVERY_BEGIN ===
# Jarvis v4.1.3.6
# Refuerza la salida de audio para respetar la configuración actual del usuario,
# re-resolver salida preferida y reintentar playback cuando una bocina/USB desaparece y vuelve.
try:
    import time as _jarvis_v4136s_time
    import logging as _jarvis_v4136s_logging
    from jarvis.audio.device_selector import resolve_output_device as _jarvis_v4136s_resolve_output

    def _jarvis_v4136s_is_output_error(exc: Exception) -> bool:
        low = str(exc or '').lower()
        return (
            'portaudioerror' in low
            or 'broken pipe' in low
            or 'input/output error' in low
            or 'unanticipated host error' in low
            or 'illegal combination of i/o devices' in low
            or 'device unavailable' in low
            or 'device disconnected' in low
            or 'internal portaudio error' in low
            or 'paerrorcode -9999' in low
            or 'paerrorcode -9993' in low
            or 'paerrorcode -9985' in low
        )

    if 'Speaker' in globals() and hasattr(Speaker, 'play_wav'):
        _jarvis_v4136s_orig_play_wav = Speaker.play_wav
        if not getattr(_jarvis_v4136s_orig_play_wav, '__jarvis_v4136_output_hotplug__', False):
            def play_wav(self, path, volume=1.0):
                logger = _jarvis_v4136s_logging.getLogger('jarvis')
                wav = Path(path).expanduser()
                last_exc = None

                for attempt in range(1, 6 + 1):
                    try:
                        result = _jarvis_v4136s_resolve_output(getattr(self, 'config', {}) or {}, current=getattr(self, 'output_device', None))
                        chosen = result.get('device', 'default')
                        self.output_device = chosen
                        logger.info(
                            'TTS_OUTPUT_RESELECT attempt=%s/%s requested=%r requested_name=%r chosen=%r chosen_name=%s reason=%s',
                            attempt,
                            6,
                            result.get('requested'),
                            result.get('requested_name'),
                            chosen,
                            result.get('name'),
                            result.get('reason'),
                        )
                    except Exception:
                        pass

                    try:
                        import sounddevice as sd
                        import soundfile as sf
                        data, samplerate = sf.read(str(wav), dtype='float32')
                        data = data * float(volume)
                        device = None if getattr(self, 'output_device', None) in (None, '', 'default', 'sysdefault') else getattr(self, 'output_device', None)
                        sd.play(data, samplerate=samplerate, device=device)
                        sd.wait()
                        logger.info('TTS_OUTPUT_READY device=%r', getattr(self, 'output_device', None))
                        return None
                    except Exception as exc:
                        last_exc = exc
                        if not _jarvis_v4136s_is_output_error(exc):
                            break
                        backoff = round(min(0.30 * attempt, 1.50), 2)
                        logger.warning(
                            'TTS_OUTPUT_RECOVERY attempt=%s/%s device=%r error=%s backoff=%.2fs',
                            attempt,
                            6,
                            getattr(self, 'output_device', None),
                            exc,
                            backoff,
                        )
                        _jarvis_v4136s_time.sleep(backoff)

                if last_exc is not None:
                    logger.warning('TTS_OUTPUT_RECOVERY falling back to legacy playback after retries: %s', last_exc)
                return _jarvis_v4136s_orig_play_wav(self, path, volume=volume)

            play_wav.__jarvis_v4136_output_hotplug__ = True
            play_wav.__wrapped__ = _jarvis_v4136s_orig_play_wav
            Speaker.play_wav = play_wav
except Exception:
    pass
# === JARVIS_V4136_OUTPUT_HOTPLUG_RECOVERY_END ===
