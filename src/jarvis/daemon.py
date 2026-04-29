from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from jarvis.audio.recorder import Recorder
from jarvis.audio.wakeword import WakeWordDetector
from jarvis.audio.echo_guard import mark_tts_start, mark_tts_end
from jarvis.brain.executor import Executor
from jarvis.brain.intent_classifier import IntentClassifier
from jarvis.brain.event_journal import EventJournal
from jarvis.brain.tool_planner import ToolPlanner
from jarvis.config import load_config
from jarvis.llm.router import LLMRouter
from jarvis.logger import setup_logger
from jarvis.skills.registry import SkillRegistry
from jarvis.state import JarvisState
from jarvis.stt.factory import create_stt
from jarvis.tts.manager import TTSManager
from jarvis.audio.echo_guard import mark_tts_start, mark_tts_end
from jarvis.brain.artifact_search import can_handle_artifact_search, execute_artifact_search
from jarvis.bus.event_bus import EventBus, install_event_journal_bridge
from jarvis.audio.kokoro_bridge import kokoro_speak_if_enabled
from jarvis.audio.followup_hint import mark_last_user_text
from jarvis.brain.short_context import expand_short_context, remember_turn
from jarvis.audio.post_question_listen import mark_pending_from_assistant
from types import SimpleNamespace
from jarvis.audio.conversation_state import note_assistant_response, note_tts_done
from jarvis.audio.conversation_state import note_false_wake
from jarvis.audio.conversation_state import note_classified_intent

# === JARVIS_V4079_NEOBUS_SAFE_EVENTBUS_BEGIN ===
# Jarvis v4.0.7.9
# Evita UnboundLocalError: EventBus cuando algún import local sombrea el nombre.
def _jarvis_v4079_get_event_bus_class():
    from jarvis.bus.event_bus import EventBus as _JarvisEventBus
    return _JarvisEventBus
# === JARVIS_V4079_NEOBUS_SAFE_EVENTBUS_END ===

# === JARVIS_V4077_BASE_STT_PRELOAD_DAEMON_BEGIN ===
# Jarvis v4.0.7.7: preload background para base-safe STT.
try:
    import os as _jarvis_v4077_os
    import threading as _jarvis_v4077_threading
    import logging as _jarvis_v4077_logging

    def _jarvis_v4077_preload_base_worker():
        if _jarvis_v4077_os.environ.get("JARVIS_BASE_STT_DISABLE", "").strip() == "1":
            return
        logger = _jarvis_v4077_logging.getLogger("jarvis")
        try:
            logger.info("BASE_STT preload background iniciando")
            from jarvis.stt.faster_whisper_stt import jarvis_preload_base_fast_stt
            ok = jarvis_preload_base_fast_stt(logger=logger)
            logger.info("BASE_STT preload background terminado ok=%s", ok)
        except Exception as exc:
            try:
                logger.warning("BASE_STT preload background falló: %s", exc)
            except Exception:
                pass

    if not globals().get("_JARVIS_V4077_BASE_STT_PRELOAD_STARTED", False):
        _JARVIS_V4077_BASE_STT_PRELOAD_STARTED = True
        _jarvis_v4077_threading.Thread(
            target=_jarvis_v4077_preload_base_worker,
            name="jarvis-base-stt-preload",
            daemon=True,
        ).start()

except Exception:
    pass
# === JARVIS_V4077_BASE_STT_PRELOAD_DAEMON_END ===

# === JARVIS_V4072_STT_TINY_PRELOAD_DAEMON_BEGIN ===
# Jarvis v4.0.7.2: preload temprano de STT tiny para fast replies.
try:
    import os as _jarvis_v4072_os
    import threading as _jarvis_v4072_threading
    import logging as _jarvis_v4072_logging

    def _jarvis_v4072_preload_fast_tiny_worker():
        if _jarvis_v4072_os.environ.get("JARVIS_FAST_STT_DISABLE", "").strip() == "1":
            return
        logger = _jarvis_v4072_logging.getLogger("jarvis")
        try:
            logger.info("FAST_STT tiny preload background iniciando")
            from jarvis.stt.faster_whisper_stt import jarvis_preload_fast_tiny_stt
            ok = jarvis_preload_fast_tiny_stt(logger=logger)
            logger.info("FAST_STT tiny preload background terminado ok=%s", ok)
        except Exception as exc:
            try:
                logger.warning("FAST_STT tiny preload background falló: %s", exc)
            except Exception:
                pass

    if not globals().get("_JARVIS_V4072_FAST_TINY_PRELOAD_STARTED", False):
        _JARVIS_V4072_FAST_TINY_PRELOAD_STARTED = True
        _jarvis_v4072_threading.Thread(
            target=_jarvis_v4072_preload_fast_tiny_worker,
            name="jarvis-fast-tiny-stt-preload",
            daemon=True,
        ).start()

except Exception:
    pass
# === JARVIS_V4072_STT_TINY_PRELOAD_DAEMON_END ===

# === JARVIS_V4063_1_STT_PRELOAD_DAEMON_TOP_BEGIN ===
# Jarvis v4.0.6.3.1: precarga STT temprano, antes del loop principal del daemon.
try:
    import os as _jarvis_v40631_os
    import threading as _jarvis_v40631_threading
    import logging as _jarvis_v40631_logging

    def _jarvis_v40631_load_config_dict():
        try:
            import yaml
            from pathlib import Path
            p = Path.home() / ".config/jarvis/config.yaml"
            if p.exists():
                return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _jarvis_v40631_preload_stt_worker():
        if _jarvis_v40631_os.environ.get("JARVIS_STT_PRELOAD_DISABLE", "").strip() == "1":
            return

        logger = _jarvis_v40631_logging.getLogger("jarvis")
        try:
            logger.info("STT preload background iniciando temprano")
        except Exception:
            pass

        try:
            from jarvis.stt.faster_whisper_stt import jarvis_preload_stt_model
            cfg = _jarvis_v40631_load_config_dict()
            ok = jarvis_preload_stt_model(config=cfg, logger=logger)
            try:
                logger.info("STT preload background terminado temprano ok=%s", ok)
            except Exception:
                pass
        except Exception as exc:
            try:
                logger.warning("STT preload background temprano falló: %s", exc)
            except Exception:
                pass

    if not globals().get("_JARVIS_V40631_STT_PRELOAD_STARTED", False):
        _JARVIS_V40631_STT_PRELOAD_STARTED = True
        _jarvis_v40631_threading.Thread(
            target=_jarvis_v40631_preload_stt_worker,
            name="jarvis-stt-preload-early",
            daemon=True,
        ).start()

except Exception:
    pass
# === JARVIS_V4063_1_STT_PRELOAD_DAEMON_TOP_END ===

# >>> JARVIS_V4053_DAEMON_KOKORO_HOT_PRELOAD
# Precalienta Kokoro Hot Server al importar/iniciar el daemon.
# No reproduce audio. Solo arranca el subprocess para que cargue el modelo en background.
def _jarvis_v4053_preload_kokoro_hot() -> None:
    try:
        import os as _os
        if _os.environ.get("JARVIS_KOKORO_HOT_DISABLE", "0").strip().lower() in {"1", "true", "yes", "on"}:
            return
        from jarvis.audio import kokoro_hot_client as _hot
        _hot.preload_async()
    except Exception:
        pass

_jarvis_v4053_preload_kokoro_hot()
# <<< JARVIS_V4053_DAEMON_KOKORO_HOT_PRELOAD

RUNNING = True

def _handle_signal(signum, frame):  # noqa: ANN001
    global RUNNING
    RUNNING = False

def main() -> None:
    global RUNNING
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = load_config()
    logger = setup_logger(config)
    state = JarvisState()
    state.set_pid()
    logger.info('Jarvis daemon iniciado')

    stt = create_stt(config, logger)
    tts = TTSManager(config, logger)
    classifier = IntentClassifier(config)
    skills = SkillRegistry(config)
    llm = LLMRouter(config, logger)
    executor = Executor(config, skills, llm, logger)
    journal = EventJournal(config, logger)
    try:
        event_bus = _jarvis_v4079_get_event_bus_class()(config=config, logger=logger)
        install_event_journal_bridge(event_bus, logger=logger)
        event_bus.publish('system.started', {'component': 'daemon', 'mode': 'shadow'})
        logger.info('NeoBus Shadow Mode activo')
    except Exception as e:
        logger.warning(f'NeoBus Shadow Mode no pudo iniciar: {e}')

    try:
        planner_for_journal = ToolPlanner(config)
    except Exception as exc:
        logger.warning('No se pudo iniciar ToolPlanner para journal: %s', exc)
        planner_for_journal = None
    recorder = Recorder(config)
    wake = WakeWordDetector(config, stt, logger)
    debug = bool(config.get('assistant', {}).get('debug', False))
    require_wake_word = bool(config.get('assistant', {}).get('require_wake_word', True))

    if require_wake_word:
        logger.info('Modo de escucha: wake word')
    else:
        logger.info('Modo de escucha: escucha total sin wake word')

    def should_continue() -> bool:
        return RUNNING and state.is_enabled()

    def safe_speak(text: str) -> None:
        assistant_cfg = config.get("assistant", {})
        hard = float(assistant_cfg.get("tts_hard_cooldown_seconds", 2.5))
        soft = float(assistant_cfg.get("tts_soft_cooldown_seconds", 10.0))
        threshold = float(assistant_cfg.get("openwakeword_cooldown_threshold", 0.85))
        mark_tts_start()
        try:
            note_assistant_response(text)
        except Exception:
            pass
        try:
            tts.speak(text)
        finally:
            mark_tts_end(hard_cooldown=hard, soft_cooldown=soft, soft_threshold=threshold)
            try:
                note_tts_done()
            except Exception:
                pass

    while RUNNING:
        if not state.is_enabled():
            time.sleep(1.0)
            continue
        try:
            command_text = ''
            wav = None

            if require_wake_word:
                logger.info('Escuchando wake word')
                wake_result = wake.wait(should_continue)
                if not RUNNING or not state.is_enabled():
                    continue
                if isinstance(wake_result, bool):

                    logger.info('WAKE_RESULT_COMPAT bool->SimpleNamespace detected=%s', wake_result)

                    wake_result = SimpleNamespace(detected=bool(wake_result), score=None, model_name='post_question_direct_listen', command_after_wake='')

                elif not hasattr(wake_result, 'detected'):

                    logger.info('WAKE_RESULT_COMPAT generic->SimpleNamespace type=%s', type(wake_result).__name__)

                    wake_result = SimpleNamespace(detected=bool(wake_result), score=None, model_name='unknown', command_after_wake='')

                if not wake_result.detected:
                    continue
                if not hasattr(wake_result, 'command_after_wake'):

                    logger.info('WAKE_RESULT_COMPAT missing command_after_wake -> empty string')

                    wake_result.command_after_wake = ''

                command_text = wake_result.command_after_wake.strip()
                if not command_text:
                    activation = config.get('assistant', {}).get('activation_reply', 'Sí, dime.')
                    try:
                        safe_speak(activation)
                    except Exception as exc:
                        logger.warning('No se pudo reproducir respuesta de activación: %s', exc)
                    wav = recorder.record_command()
                    try:
                        command_text = stt.transcribe(wav).strip()
                    finally:
                        if not debug:
                            Path(wav).unlink(missing_ok=True)
            else:
                # Escucha total: no espera wake word. Graba cuando detecta voz y corta por silencio.
                logger.info('Escucha total activa: esperando voz')
                wav = recorder.record_command()
                try:
                    command_text = stt.transcribe(wav).strip()
                finally:
                    if not debug:
                        Path(wav).unlink(missing_ok=True)

            if not command_text:
                short_capture_bytes = None
                try:
                    if wav is not None:
                        short_capture_bytes = Path(wav).stat().st_size
                except Exception:
                    short_capture_bytes = None

                try:
                    short_capture_limit = int(float(os.getenv('JARVIS_EMPTY_SHORT_CAPTURE_BYTES', '90000')))
                except Exception:
                    short_capture_limit = 90000

                should_mark_false_wake = True
                if short_capture_bytes is not None and short_capture_bytes > 44 and short_capture_bytes <= short_capture_limit:
                    should_mark_false_wake = False
                    logger.info('EMPTY_COMMAND_SHORT_CAPTURE bytes=%s limit=%s', short_capture_bytes, short_capture_limit)

                if should_mark_false_wake:
                    try:
                        note_false_wake()
                    except Exception:
                        pass
                    logger.info('MEDIA_GUARD noted empty command after wake')
                else:
                    logger.info('MEDIA_GUARD skipped false_wake note for short/early capture')

                logger.info('Comando vacío')
                try:
                    if should_mark_false_wake:
                        false_rearm_delay = float(os.getenv('JARVIS_FALSE_WAKE_REARM_DELAY_SECONDS', '0.45'))
                    else:
                        false_rearm_delay = float(os.getenv('JARVIS_EARLY_CUTOFF_REARM_DELAY_SECONDS', '0.12'))
                except Exception:
                    false_rearm_delay = 0.45 if should_mark_false_wake else 0.12
                if false_rearm_delay > 0:
                    logger.info('FALSE_WAKE_REARM_DELAY sleep_seconds=%.2f', false_rearm_delay)
                    time.sleep(false_rearm_delay)
                continue

            mark_last_user_text(str(command_text))



            __jarvis_short_raw = str(command_text)



            __jarvis_short_expanded = expand_short_context(__jarvis_short_raw)



            logger.info("SHORT_CONTEXT raw=%r expanded=%r", __jarvis_short_raw, __jarvis_short_expanded)



            command_text = __jarvis_short_expanded



            remember_turn(user_text=str(command_text))





            __jarvis_short_ctx_raw = str(command_text)



            __jarvis_short_ctx_expanded = expand_short_context(__jarvis_short_ctx_raw)



            if __jarvis_short_ctx_expanded != __jarvis_short_ctx_raw:



                logger.info("SHORT_CONTEXT expand raw=%r expanded=%r", __jarvis_short_ctx_raw, __jarvis_short_ctx_expanded)



                command_text = __jarvis_short_ctx_expanded

            journal_start = time.monotonic()
            journal_steps = []
            try:
                if planner_for_journal is not None:
                    journal_steps = EventJournal.normalize_steps(planner_for_journal.plan(command_text))
            except Exception as exc:
                logger.warning('No se pudo calcular planner_steps para journal: %s', exc)
            intent = classifier.classify(command_text)
            logger.info('Intención detectada: %s entities=%s', intent.name, intent.entities)
            try:
                note_classified_intent(intent.name, intent.entities)
            except Exception:
                pass

            if intent.name == 'stop_listening':
                state.set_enabled(False)
                response = 'Jarvis desactivado. El micrófono ya no está siendo escuchado.'
            elif intent.name == 'feedback_positive':
                EventJournal().set_feedback_last(1)
                response = 'Perfecto. Marqué la última acción como buena.'
            elif intent.name == 'feedback_negative':
                EventJournal().set_feedback_last(-1)
                response = 'Entendido. Marqué la última acción como mala para aprender de eso.'
            elif intent.name == 'remember_alias':
                alias = str(intent.entities.get('alias', '')).strip()
                path = str(intent.entities.get('path', '')).strip()
                EventJournal().remember_alias(alias, path)
                response = f'Recordé el alias {alias}.'
            elif intent.name == 'farewell':
                response = 'Perfecto.'
            elif intent.name == 'fast_reply':
                response = intent.entities.get('response', 'Aquí estoy, señor.')
                try:
                    from jarvis.bus.event_bus import EventBus
                    _jarvis_v4079_get_event_bus_class()().publish('fast_reply.matched', {'text': command_text, 'response': response, 'key': intent.entities.get('fast_key')}, source='fast_replies')
                except Exception:
                    pass
            elif intent.name == 'unknown':
                response = 'No escuché un comando claro.'
            else:
                if can_handle_artifact_search(intent):
                    response = execute_artifact_search(intent)
                else:
                    response = executor.execute(intent)
            journal_duration = int((time.monotonic() - journal_start) * 1000)
            try:
                journal.record(
                    input_text=command_text,
                    intent=intent,
                    planner_steps=journal_steps,
                    result_text=response,
                    success=True,
                    duration_ms=journal_duration,
                )
            except Exception as exc:
                logger.warning('No se pudo escribir EventJournal: %s', exc)

            remember_turn(assistant_text=str(response))



            try:

                remember_turn(assistant_text=str(response))

            except Exception:

                pass

            try:
                safe_speak(response)
            except Exception as exc:
                logger.error('Falló TTS final: %s', exc, exc_info=True)
        except Exception as exc:
            logger.error('Error en loop principal: %s', exc, exc_info=True)
            time.sleep(1.0)

    logger.info('Jarvis daemon detenido')

if __name__ == '__main__':
    main()
