from __future__ import annotations

from typing import Any
import importlib

from jarvis.brain.intent_model import Intent
from jarvis.brain.smart_router import SmartRouter
from jarvis.brain.action_validator import ActionValidator


def _get_tool_planner_class():
    mod = importlib.import_module("jarvis.brain.tool_planner")
    cls = getattr(mod, "ToolPlanner", None) or getattr(mod, "Planner", None)
    if cls is None:
        raise RuntimeError("No encontré ToolPlanner ni Planner en jarvis.brain.tool_planner")
    return cls


def _step_tool(step: Any) -> str:
    if isinstance(step, dict):
        return str(step.get("tool", "") or "")
    return str(getattr(step, "tool", "") or "")


def _step_params(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        params = step.get("params", {}) or {}
    else:
        params = getattr(step, "params", {}) or {}
    return dict(params)


class IntentClassifier:
    """
    IntentClassifier v3.1.3

    Usa ToolPlanner primero. Si el planner produce varios pasos, los colapsa
    a un Intent compatible con el daemon actual. Esto evita que el daemon
    ejecute solo el primer paso del plan.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        PlannerCls = _get_tool_planner_class()
        try:
            self.planner = PlannerCls(self.config)
        except TypeError:
            self.planner = PlannerCls()
        self.router = SmartRouter(self.config)
        self.validator = ActionValidator(self.config)

    def classify(self, text: str) -> Intent:
        raw_text = text or ""
        t = raw_text.lower().strip().strip(".,;:!?¡¿")

        positive_feedback_phrases = {
            "eso estuvo bien",
            "eso estuvo perfecto",
            "eso funciono",
            "eso funcionó",
            "bien hecho",
            "lo hiciste bien",
            "correcto",
            "muy bien jarvis",
        }
        negative_feedback_phrases = {
            "eso estuvo mal",
            "eso fallo",
            "eso falló",
            "eso no funciono",
            "eso no funcionó",
            "lo hiciste mal",
            "incorrecto",
            "mal jarvis",
        }

        if t in positive_feedback_phrases:
            return Intent("feedback_positive", 1.0, {"value": 1}, raw_text)

        if t in negative_feedback_phrases:
            return Intent("feedback_negative", 1.0, {"value": -1}, raw_text)

        import re as _re
        m_alias = _re.search(r"(?:recuerda que|recuerda alias|guardar alias|guarda alias)\s+(.+?)\s+(?:es|como)\s+(.+)$", t)
        if m_alias:
            alias = m_alias.group(1).strip()
            path = m_alias.group(2).strip()
            return Intent("remember_alias", 0.99, {"alias": alias, "path": path}, raw_text)

        raw = text or ""

        # 1) Planner estructurado primero.
        try:
            steps = self.planner.plan(raw)
            intent = self._steps_to_intent(steps, raw)
            if intent is not None:
                return intent
        except Exception:
            # No romper Jarvis si el planner falla; cae al router viejo.
            pass

        # 2) Fallback compatible con la arquitectura anterior.
        action = self.router.parse(raw)
        return self.validator.to_intent(action, raw)

    def _steps_to_intent(self, steps: Any, raw: str) -> Intent | None:
        if not steps:
            return None

        normalized = []
        for step in steps:
            tool = _step_tool(step)
            params = _step_params(step)
            if tool:
                normalized.append((tool, params))

        if not normalized:
            return None

        # Si el plan contiene búsqueda, el daemon actual debe ejecutar search_file,
        # no solo el primer open_folder. FilesSkill se encargará de open_base/open_first.
        search_i = None
        for i, (tool, _params) in enumerate(normalized):
            if tool == "search_files":
                search_i = i
                break

        if search_i is not None:
            search_params = normalized[search_i][1]
            query = str(search_params.get("query", "") or "").strip()
            base = str(search_params.get("base", "") or search_params.get("path", "") or "").strip()

            entities: dict[str, Any] = {"query": query}
            if base:
                entities["path"] = base

            # Si antes de search_files hubo open_folder, abrir también la carpeta base.
            for tool, params in normalized[:search_i]:
                if tool == "open_folder":
                    open_path = str(params.get("path", "") or "").strip()
                    if open_path:
                        entities["path"] = base or open_path
                        entities["open_base"] = True
                        entities["base_path"] = open_path
                    break

            # Si después de search_files hay open_result, buscar y abrir ese resultado.
            for tool, params in normalized[search_i + 1:]:
                if tool == "open_result":
                    try:
                        idx = int(params.get("index", 1) or 1)
                    except Exception:
                        idx = 1
                    # IMPORTANTE: este proyecto usa índices 1-based:
                    # 1 = primero, 2 = segundo.
                    if idx < 1:
                        idx = 1
                    entities["open_first"] = True
                    entities["open_index"] = idx
                    break

            if query:
                return Intent("search_file", 0.99, entities, raw)

        # Un solo open_folder o plan de solo open_folder.
        if len(normalized) == 1 and normalized[0][0] == "open_folder":
            path = str(normalized[0][1].get("path", "") or "").strip()
            if path:
                target = path.rstrip("/").split("/")[-1] or path
                return Intent("open_folder", 0.999, {"path": path, "target": target}, raw)

        # Abrir resultado anterior.
        if len(normalized) == 1 and normalized[0][0] == "open_result":
            try:
                idx = int(normalized[0][1].get("index", 1) or 1)
            except Exception:
                idx = 1
            if idx < 1:
                idx = 1
            return Intent("open_result", 0.98, {"index": idx}, raw)

        # Dejar al router viejo manejar URLs, música, servicios, etc. por ahora.
        return None

# ---------------------------------------------------------------------------
# v3.4.9 compatibility: clean query in final Intent entities
# ---------------------------------------------------------------------------
try:
    import re as _jv349_intent_re

    def _jv349_intent_clean_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv349_intent_re.sub(r"\s+", " ", q).strip()
        corrections = {
            "a a b": "aab",
            "a a ve": "aab",
            "aave": "aab",
            "aap": "aab",
            "abb": "aab",
            "aav": "aab",
            "ab": "aab",
        }
        if q in corrections:
            return corrections[q]
        q = _jv349_intent_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv349_intent_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jv349_intent_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        return _jv349_intent_re.sub(r"\s+", " ", q).strip()

    if "IntentClassifier" in globals() and not getattr(IntentClassifier.classify, "_jv349_wrapped", False):
        _jv349_orig_classify = IntentClassifier.classify

        def _jv349_classify(self, text, *args, **kwargs):
            intent = _jv349_orig_classify(self, text, *args, **kwargs)
            entities = getattr(intent, "entities", None)
            if isinstance(entities, dict):
                for key in ("query", "search_query"):
                    if key in entities:
                        entities[key] = _jv349_intent_clean_query(entities.get(key))
            return intent

        _jv349_classify._jv349_wrapped = True
        IntentClassifier.classify = _jv349_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.13 compatibility: prevent filler phrase from going to LLM
# ---------------------------------------------------------------------------
try:
    if "IntentClassifier" in globals() and not getattr(IntentClassifier.classify, "_jv3413_farewell_wrapped", False):
        _jv3413_orig_classify = IntentClassifier.classify

        def _jv3413_classify(self, text, *args, **kwargs):
            raw_text = text or ""
            t = raw_text.lower().strip().strip(".,;:!?¡¿")
            if t in {"todo bien", "ya quedó", "ya quedo", "listo", "gracias", "ok gracias"}:
                return Intent("farewell", 1.0, {"text": raw_text}, raw_text)
            return _jv3413_orig_classify(self, text, *args, **kwargs)

        _jv3413_classify._jv3413_farewell_wrapped = True
        IntentClassifier.classify = _jv3413_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.14 compatibility: normalize dictated artifact queries early
# ---------------------------------------------------------------------------
try:
    import re as _jv3414_re

    def _jv3414_clean_artifact_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        aab_variants = {
            "aab", ".aab",
            "a a b", "a a ve", "aave",
            "a ap", "a a p", "aap",
            "a ab", "a abe", "a b",
            "abb", "aav", "ab",
        }
        apk_variants = {
            "apk", ".apk",
            "a p k", "a pe ka", "a p ka", "ap k", "a pk",
        }

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        q = _jv3414_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+a\s+p\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ab\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*p\s*k\b", "apk", q)
        q = _jv3414_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        return q

    def _jv3414_clean_mapping(obj):
        if not isinstance(obj, dict):
            return obj
        for key in ("query", "search_query"):
            if key in obj:
                obj[key] = _jv3414_clean_artifact_query(obj.get(key))
        if isinstance(obj.get("params"), dict):
            _jv3414_clean_mapping(obj["params"])
        if isinstance(obj.get("entities"), dict):
            _jv3414_clean_mapping(obj["entities"])
        return obj

    def _jv3414_clean_any(obj):
        if obj is None:
            return obj

        if isinstance(obj, list):
            for i, item in enumerate(obj):
                obj[i] = _jv3414_clean_any(item)
            return obj

        if isinstance(obj, tuple):
            return tuple(_jv3414_clean_any(x) for x in obj)

        if isinstance(obj, dict):
            return _jv3414_clean_mapping(obj)

        # dataclass / normal objects used by Jarvis: Intent, SemanticAction, Plan, etc.
        for attr in ("query", "search_query"):
            if hasattr(obj, attr):
                try:
                    setattr(obj, attr, _jv3414_clean_artifact_query(getattr(obj, attr)))
                except Exception:
                    pass

        for attr in ("params", "entities"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, dict):
                        _jv3414_clean_mapping(val)
                except Exception:
                    pass

        for attr in ("steps", "planner_steps"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, list):
                        setattr(obj, attr, _jv3414_clean_any(val))
                except Exception:
                    pass

        return obj
except Exception:
    pass

try:
    if "IntentClassifier" in globals() and hasattr(IntentClassifier, "classify") and not getattr(IntentClassifier.classify, "_jv3414_wrapped", False):
        _jv3414_orig_classify = IntentClassifier.classify

        def _jv3414_classify(self, *args, **kwargs):
            return _jv3414_clean_any(_jv3414_orig_classify(self, *args, **kwargs))

        _jv3414_classify._jv3414_wrapped = True
        IntentClassifier.classify = _jv3414_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v4.0.3 Fast Replies: local personality replies before LLM
# ---------------------------------------------------------------------------
try:
    if "IntentClassifier" in globals() and "Intent" in globals() and not getattr(IntentClassifier.classify, "_jv403_fast_replies", False):
        _jv403_original_classify = IntentClassifier.classify

        def _jv403_classify(self, text, *args, **kwargs):
            try:
                from jarvis.brain.fast_replies import match_fast_reply
                match = match_fast_reply(text)
                if match:
                    return Intent(
                        "fast_reply",
                        1.0,
                        {
                            "text": text,
                            "response": match["response"],
                            "fast_key": match["key"],
                            "local": True,
                        },
                        text,
                    )
            except Exception:
                pass

            return _jv403_original_classify(self, text, *args, **kwargs)

        _jv403_classify._jv403_fast_replies = True
        IntentClassifier.classify = _jv403_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v4.0.3.2 Fast Replies SAFE FIX: local personality replies before LLM
# ---------------------------------------------------------------------------
try:
    if "IntentClassifier" in globals() and "Intent" in globals() and not getattr(IntentClassifier.classify, "_jv4032_fast_replies", False):
        _jv4032_original_classify = IntentClassifier.classify

        def _jv4032_classify(self, text, *args, **kwargs):
            try:
                from jarvis.brain.fast_replies import match_fast_reply
                match = match_fast_reply(text)
                if match:
                    return Intent(
                        "fast_reply",
                        1.0,
                        {
                            "text": text,
                            "response": match["response"],
                            "fast_key": match["key"],
                            "local": True,
                        },
                        text,
                    )
            except Exception:
                pass
            return _jv4032_original_classify(self, text, *args, **kwargs)

        _jv4032_classify._jv4032_fast_replies = True
        IntentClassifier.classify = _jv4032_classify
except Exception:
    pass


# ---------------------------------------------------------------------------
# v4.1.1.8 compatibility: direct apps/media intents for phase 1B
# ---------------------------------------------------------------------------
try:
    import re as _jv4118_re

    def _jv4118_norm(value: str) -> str:
        t = (value or "").lower().strip()
        t = t.strip(".,;:!?¡¿")
        t = _jv4118_re.sub(r"\s+", " ", t)
        return t.strip()

    def _jv4118_parse_percent(text: str):
        m = _jv4118_re.search(r"(\d{1,3})", text or "")
        if not m:
            return None
        try:
            return max(0, min(150, int(m.group(1))))
        except Exception:
            return None

    def _jv4118_clean_music_query(value: str) -> str:
        q = str(value or "").strip()
        q = _jv4118_re.sub(r"\s+", " ", q)
        return q.strip(" .,:;!?¡¿\"'")

    def _jv4118_extract_app(raw: str, prefixes: tuple[str, ...]) -> str:
        t = _jv4118_norm(raw)
        for prefix in prefixes:
            if t.startswith(prefix):
                return t[len(prefix):].strip()
        return ""

    def _jv4118_extract_music(raw: str):
        t = _jv4118_norm(raw)
        m = _jv4118_re.search(r"(?:reproduce|ponme|pon|toca|quiero escuchar)\s+(.+?)(?:\s+en\s+(youtube|spotify|tidal|youtube music))?$", t)
        if not m:
            return None
        query = _jv4118_clean_music_query(m.group(1))
        if not query:
            return None
        return {"query": query, "platform": (m.group(2) or "youtube")}

    if "IntentClassifier" in globals() and not getattr(IntentClassifier.classify, "_jv4118_apps_media_wrapped", False):
        _jv4118_orig_classify = IntentClassifier.classify

        def _jv4118_classify(self, text, *args, **kwargs):
            raw_text = text or ""
            t = _jv4118_norm(raw_text)
            play = _jv4118_extract_music(raw_text)
            if play is not None:
                return Intent("play_music", 0.98, play, raw_text)
            if t in {"pausa", "pausar", "pausa la musica", "pausa la música", "pause music", "pause"}:
                return Intent("media_pause", 0.99, {}, raw_text)
            if t in {"reanuda", "reanudar", "continua", "continúa", "resume", "resume music", "reanuda la musica", "reanuda la música", "continua la musica", "continúa la música"}:
                return Intent("media_resume", 0.99, {}, raw_text)
            if t in {"deten la musica", "detén la música", "para la musica", "para la música", "stop music", "deten musica", "detén música"}:
                return Intent("media_stop", 0.99, {}, raw_text)
            if t in {"siguiente cancion", "siguiente canción", "siguiente pista", "next song", "next track"}:
                return Intent("media_next", 0.98, {}, raw_text)
            if t in {"cancion anterior", "canción anterior", "pista anterior", "anterior pista", "previous song", "previous track"}:
                return Intent("media_previous", 0.98, {}, raw_text)
            if any(x in t for x in ["sube el volumen", "más volumen", "mas volumen", "volumen arriba"]):
                return Intent("media_volume_up", 0.98, {"step": _jv4118_parse_percent(t) or 8}, raw_text)
            if any(x in t for x in ["baja el volumen", "menos volumen", "volumen abajo"]):
                return Intent("media_volume_down", 0.98, {"step": _jv4118_parse_percent(t) or 8}, raw_text)
            if ("volumen al" in t or "pon el volumen al" in t or "ajusta el volumen al" in t) and _jv4118_parse_percent(t) is not None:
                return Intent("media_volume_set", 0.99, {"percent": _jv4118_parse_percent(t)}, raw_text)
            if t in {"silencia", "silencia el audio", "mute", "mutea", "mutear", "quita el sonido"}:
                return Intent("media_mute", 0.99, {}, raw_text)
            if t in {"quita el mute", "activa el sonido", "unmute", "reactiva el audio", "vuelve el sonido"}:
                return Intent("media_unmute", 0.99, {}, raw_text)
            app = _jv4118_extract_app(raw_text, ("cierra ", "cierra la app ", "cierra la aplicación "))
            if app:
                return Intent("close_app", 0.98, {"app": app}, raw_text)
            app = _jv4118_extract_app(raw_text, ("enfoca ", "cambia a ", "ve a ", "muestrame ", "muéstrame "))
            if app:
                return Intent("focus_app", 0.97, {"app": app}, raw_text)
            if t in {"que apps estan abiertas", "qué apps están abiertas", "lista aplicaciones abiertas", "que ventanas estan abiertas", "qué ventanas están abiertas", "lista apps abiertas"}:
                return Intent("list_apps", 0.97, {}, raw_text)
            return _jv4118_orig_classify(self, text, *args, **kwargs)

        _jv4118_classify._jv4118_apps_media_wrapped = True
        IntentClassifier.classify = _jv4118_classify
except Exception:
    pass



# ---------------------------------------------------------------------------
# v4.1.1.9 phase 1C: direct files/system intent parsing
# ---------------------------------------------------------------------------
try:
    import re as _v4119_phase1c_re

    def _v4119_phase1c_strip(text):
        return str(text or '').strip().strip(" .,:;!?¡¿\"'")

    def _v4119_phase1c_maybe_intent(raw_text):
        t = (raw_text or '').lower().strip().strip('.,;:!?¡¿')
        if not t:
            return None

        m = _v4119_phase1c_re.match(r'^(?:crea|crear|haz) (?:una )?carpeta (.+)$', t)
        if m:
            return Intent('create_folder', 0.99, {'name': _v4119_phase1c_strip(m.group(1))}, raw_text)

        m = _v4119_phase1c_re.match(r'^(?:renombra|renombrar) (?:el archivo |la carpeta |el directorio )?(.+?) a (.+)$', t)
        if m:
            return Intent('rename_path', 0.99, {'source': _v4119_phase1c_strip(m.group(1)), 'new_name': _v4119_phase1c_strip(m.group(2))}, raw_text)

        m = _v4119_phase1c_re.match(r'^(?:copia|copiar) (.+?) a (.+)$', t)
        if m:
            return Intent('copy_path', 0.99, {'source': _v4119_phase1c_strip(m.group(1)), 'destination_dir': _v4119_phase1c_strip(m.group(2))}, raw_text)

        m = _v4119_phase1c_re.match(r'^(?:mueve|mover) (.+?) a (.+)$', t)
        if m:
            return Intent('move_path', 0.99, {'source': _v4119_phase1c_strip(m.group(1)), 'destination_dir': _v4119_phase1c_strip(m.group(2))}, raw_text)

        m = _v4119_phase1c_re.match(r'^(?:borra|borrar|elimina|eliminar|manda a la papelera) (?:el archivo |la carpeta |el directorio )?(.+)$', t)
        if m:
            return Intent('delete_path', 0.99, {'source': _v4119_phase1c_strip(m.group(1))}, raw_text)

        m = _v4119_phase1c_re.match(r'^(?:lista|listar|muestra|mostrar) (?:los )?(?:archivos|contenido)(?: de)? (.+)$', t)
        if m:
            return Intent('list_directory', 0.98, {'path': _v4119_phase1c_strip(m.group(1))}, raw_text)

        if any(key in t for key in ('cuánta ram', 'cuanta ram', 'memoria ram', 'uso de memoria', 'memoria usada')):
            return Intent('system_memory_status', 0.98, {}, raw_text)
        if any(key in t for key in ('uso de cpu', 'cómo va la cpu', 'como va la cpu', 'estado de cpu', 'carga de cpu')):
            return Intent('system_cpu_status', 0.98, {}, raw_text)
        if any(key in t for key in ('espacio en disco', 'uso de disco', 'disco duro', 'almacenamiento')):
            return Intent('system_disk_status', 0.98, {'path': '/'}, raw_text)
        if any(key in t for key in ('nombre del equipo', 'hostname', 'nombre de la pc', 'nombre de la computadora')):
            return Intent('system_hostname', 0.98, {}, raw_text)
        if any(key in t for key in ('cuánto lleva encendida', 'cuanto lleva encendida', 'uptime', 'tiempo encendida', 'tiempo prendida')):
            return Intent('system_uptime', 0.98, {}, raw_text)
        if 'batería' in t or 'bateria' in t:
            return Intent('system_battery_status', 0.98, {}, raw_text)
        return None

    if 'IntentClassifier' in globals() and not getattr(IntentClassifier.classify, '_v4119_phase1c_wrapped', False):
        _v4119_phase1c_orig_classify = IntentClassifier.classify

        def _v4119_phase1c_classify(self, text, *args, **kwargs):
            raw_text = text or ''
            direct = _v4119_phase1c_maybe_intent(raw_text)
            if direct is not None:
                return direct
            return _v4119_phase1c_orig_classify(self, text, *args, **kwargs)

        _v4119_phase1c_classify._v4119_phase1c_wrapped = True
        IntentClassifier.classify = _v4119_phase1c_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v4.1.2.0 compatibility: services + windows direct intents
# ---------------------------------------------------------------------------
try:
    import re as _jv4120_re

    _jv4120_num_words = {
        'uno': 1, 'una': 1, 'primer': 1, 'primero': 1,
        'dos': 2, 'segundo': 2,
        'tres': 3, 'tercero': 3,
        'cuatro': 4, 'cuarto': 4,
        'cinco': 5, 'quinto': 5,
        'seis': 6, 'sexto': 6,
        'siete': 7, 'septimo': 7, 'séptimo': 7,
        'ocho': 8, 'octavo': 8,
        'nueve': 9, 'noveno': 9,
        'diez': 10, 'decimo': 10, 'décimo': 10,
    }
    _jv4120_services = ('jarvis', 'jellyfin', 'immich', 'docker', 'ssh', 'sshd')

    def _jv4120_find_service(text: str) -> str:
        for service in _jv4120_services:
            if _jv4120_re.search(rf'\b{service}\b', text):
                return service
        return ''

    def _jv4120_find_workspace(text: str):
        m = _jv4120_re.search(r'\b(?:escritorio|workspace)\s+(\d{1,2})\b', text)
        if m:
            return int(m.group(1))
        for word, value in _jv4120_num_words.items():
            if _jv4120_re.search(rf'\b(?:escritorio|workspace)\s+{word}\b', text):
                return value
        return None

    if 'IntentClassifier' in globals() and not getattr(IntentClassifier.classify, '_jv4120_services_windows_wrapped', False):
        _jv4120_orig_classify = IntentClassifier.classify

        def _jv4120_classify(self, text, *args, **kwargs):
            raw_text = text or ''
            t = raw_text.lower().strip().strip('.,;:!?¡¿')

            if _jv4120_re.search(r'\b(servicios? fallando|servicios? fallaron|que servicios? fallaron|failed services?)\b', t):
                return Intent('service_list_failed', 0.99, {}, raw_text)

            service = _jv4120_find_service(t)
            if service:
                if _jv4120_re.search(r'\b(logs?|journal)\b', t):
                    return Intent('service_logs', 0.99, {'service': service}, raw_text)
                if _jv4120_re.search(r'\b(reinicia|reiniciar|restart)\b', t):
                    return Intent('service_restart', 0.99, {'service': service}, raw_text)
                if _jv4120_re.search(r'\b(inicia|arranca|levanta|start)\b', t):
                    return Intent('service_start', 0.99, {'service': service}, raw_text)
                if _jv4120_re.search(r'\b(det[eé]n|detener|para|stop)\b', t):
                    return Intent('service_stop', 0.99, {'service': service}, raw_text)
                if _jv4120_re.search(r'\b(estado|status|como esta|cómo está|esta activo|est[aá] activo)\b', t):
                    return Intent('service_status', 0.99, {'service': service}, raw_text)

            workspace = _jv4120_find_workspace(t)
            if workspace is not None and _jv4120_re.search(r'\b(cambia|ve|ir|switch|mueve)\b', t):
                return Intent('window_switch_workspace', 0.99, {'workspace': workspace}, raw_text)

            if _jv4120_re.search(r'\b(cierra|cerrar)\b', t) and _jv4120_re.search(r'\b(ventana|actual)\b', t):
                return Intent('window_close', 0.99, {}, raw_text)
            if _jv4120_re.search(r'\b(minimiza|minimizar)\b', t):
                return Intent('window_minimize', 0.99, {}, raw_text)
            if _jv4120_re.search(r'\b(maximiza|maximizar)\b', t):
                return Intent('window_maximize', 0.99, {}, raw_text)
            if _jv4120_re.search(r'\b(pantalla completa|fullscreen)\b', t):
                return Intent('window_fullscreen', 0.99, {}, raw_text)
            if _jv4120_re.search(r'\b(mosaico|acomoda|pon)\b', t) and _jv4120_re.search(r'\b(izquierda|left)\b', t):
                return Intent('window_tile_left', 0.99, {}, raw_text)
            if _jv4120_re.search(r'\b(mosaico|acomoda|pon)\b', t) and _jv4120_re.search(r'\b(derecha|right)\b', t):
                return Intent('window_tile_right', 0.99, {}, raw_text)

            return _jv4120_orig_classify(self, text, *args, **kwargs)

        _jv4120_classify._jv4120_services_windows_wrapped = True
        IntentClassifier.classify = _jv4120_classify
except Exception:
    pass


# ---------------------------------------------------------------------------
# v4.1.2.1 phase 1E: broader Linux desktop intents + smoke-test helpers
# ---------------------------------------------------------------------------
try:
    import os as _jv4121_os
    import re as _jv4121_re

    _jv4121_num_words = {
        'primer': 1, 'primero': 1, 'uno': 1, 'una': 1,
        'segundo': 2, 'dos': 2,
        'tercer': 3, 'tercero': 3, 'tres': 3,
        'cuarto': 4, 'cuatro': 4,
        'quinto': 5, 'cinco': 5,
    }
    _jv4121_common_folders = {
        'descargas': '~/Descargas',
        'downloads': '~/Descargas',
        'documentos': '~/Documentos',
        'documents': '~/Documentos',
        'escritorio': '~/Escritorio',
        'desktop': '~/Escritorio',
        'imagenes': '~/Imágenes',
        'imágenes': '~/Imágenes',
        'fotos': '~/Imágenes',
        'musica': '~/Música',
        'música': '~/Música',
        'videos': '~/Videos',
        'vídeos': '~/Videos',
    }
    _jv4121_webish = {
        'youtube', 'spotify', 'google', 'gmail', 'drive', 'calendar', 'github', 'chatgpt',
        'whatsapp', 'telegram', 'netflix', 'amazon', 'facebook', 'instagram', 'twitter'
    }
    _jv4121_app_blockers = {'carpeta', 'archivo', 'directorio', 'resultado', 'resultados', 'servicio', 'logs'}
    _jv4121_known_services = ('jarvis', 'jellyfin', 'immich', 'docker', 'ssh', 'sshd')

    def _jv4121_norm(value: str) -> str:
        t = (value or '').lower().strip()
        t = t.strip('.,;:!?¡¿')
        t = _jv4121_re.sub(r'\s+', ' ', t)
        return t.strip()

    def _jv4121_strip(value: str) -> str:
        return str(value or '').strip().strip(" .,:;!?¡¿\"'`“”‘’")

    def _jv4121_extract_after_prefixes(raw_text: str, prefixes: tuple[str, ...]) -> str:
        t = _jv4121_norm(raw_text)
        for prefix in prefixes:
            if t.startswith(prefix):
                return _jv4121_strip(t[len(prefix):])
        return ''

    def _jv4121_common_folder_path(target: str) -> str:
        value = _jv4121_norm(target)
        value = value.replace('la carpeta ', '').replace('el directorio ', '').strip()
        direct = _jv4121_common_folders.get(value)
        if direct:
            return _jv4121_os.path.expanduser(direct)
        return ''

    def _jv4121_should_open_app(target: str) -> bool:
        t = _jv4121_norm(target)
        if not t:
            return False
        if any(block in t for block in _jv4121_app_blockers):
            return False
        if t in _jv4121_webish:
            return False
        if 'http://' in t or 'https://' in t or '.com' in t or '.mx' in t or '.org' in t:
            return False
        if len(t.split()) > 4:
            return False
        return True

    def _jv4121_result_index(text: str):
        m = _jv4121_re.search(r'\bresultado\s+(\d{1,2})\b', text)
        if m:
            return max(1, int(m.group(1)))
        for word, value in _jv4121_num_words.items():
            if _jv4121_re.search(rf'\b{word}\s+resultado\b', text) or _jv4121_re.search(rf'\bresultado\s+{word}\b', text):
                return value
        return None

    def _jv4121_find_service(text: str) -> str:
        for service in _jv4121_known_services:
            if _jv4121_re.search(rf'\b{service}\b', text):
                return service
        return ''

    if 'IntentClassifier' in globals() and not getattr(IntentClassifier.classify, '_jv4121_phase1e_wrapped', False):
        _jv4121_orig_classify = IntentClassifier.classify

        def _jv4121_classify(self, text, *args, **kwargs):
            raw_text = text or ''
            t = _jv4121_norm(raw_text)

            if t in {
                'estado del sistema', 'estado de la pc', 'estado de la computadora', 'estado del equipo',
                'como esta la pc', 'cómo está la pc', 'como esta la computadora', 'cómo está la computadora',
                'como esta el sistema', 'cómo está el sistema', 'resumen del sistema'
            }:
                return Intent('system_status', 0.99, {}, raw_text)

            # Abrir carpetas comunes rápidamente.
            folder_target = _jv4121_extract_after_prefixes(raw_text, (
                'abre ', 'abre la carpeta ', 'abre el directorio ', 'muestra ', 'muestrame ', 'muéstrame '
            ))
            folder_path = _jv4121_common_folder_path(folder_target)
            if folder_path:
                label = folder_path.rstrip('/').split('/')[-1] or folder_target
                return Intent('open_folder', 0.99, {'path': folder_path, 'target': label}, raw_text)

            # Abrir resultados guardados.
            result_index = _jv4121_result_index(t)
            if result_index is not None and _jv4121_re.search(r'\b(abre|abrir|open)\b', t):
                return Intent('open_result', 0.99, {'index': result_index}, raw_text)

            # Listado/directorio con lenguaje natural.
            m = _jv4121_re.match(r'^(?:que hay(?: en)?|qué hay(?: en)?|que contiene(?: en)?|qué contiene(?: en)?|muestra(?:me)? el contenido de|ensena(?:me)? el contenido de|enseña(?:me)? el contenido de)\s+(.+)$', t)
            if m:
                return Intent('list_directory', 0.98, {'path': _jv4121_strip(m.group(1))}, raw_text)

            # Abrir aplicaciones con más verbos.
            open_app_target = _jv4121_extract_after_prefixes(raw_text, (
                'abre la app ', 'abre la aplicación ', 'abre ', 'inicia ', 'lanza ', 'ejecuta '
            ))
            if _jv4121_should_open_app(open_app_target):
                return Intent('open_app', 0.98, {'app': open_app_target}, raw_text)

            if t in {
                'que programas estan abiertos', 'qué programas están abiertos', 'que aplicaciones estan abiertas',
                'qué aplicaciones están abiertas', 'que ventanas tengo abiertas', 'qué ventanas tengo abiertas',
                'programas abiertos'
            }:
                return Intent('list_apps', 0.98, {}, raw_text)

            # Más variantes de media.
            if t in {'subele al volumen', 'súbele al volumen', 'subele', 'súbele', 'subele un poco', 'súbele un poco'}:
                return Intent('media_volume_up', 0.98, {'step': 8}, raw_text)
            if t in {'bajale al volumen', 'bájale al volumen', 'bajale', 'bájale', 'bajale un poco', 'bájale un poco'}:
                return Intent('media_volume_down', 0.98, {'step': 8}, raw_text)
            if t in {'pon en silencio', 'pon silencio', 'mutealo', 'mutealo todo', 'mutealo', 'silencia todo'}:
                return Intent('media_mute', 0.99, {}, raw_text)
            if t in {'quita el silencio', 'devuelve el sonido', 'regresa el sonido', 'vuelve el audio'}:
                return Intent('media_unmute', 0.99, {}, raw_text)

            # Servicios con frases más naturales.
            service = _jv4121_find_service(t)
            if service:
                if _jv4121_re.search(r'\b(como va|cómo va|como esta|cómo está|esta corriendo|est[aá] corriendo)\b', t):
                    return Intent('service_status', 0.98, {'service': service}, raw_text)

            return _jv4121_orig_classify(self, text, *args, **kwargs)

        _jv4121_classify._jv4121_phase1e_wrapped = True
        IntentClassifier.classify = _jv4121_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v4.1.2.2 phase 2A: network + power direct intents
# ---------------------------------------------------------------------------
try:
    import re as _jv4122_re

    if 'IntentClassifier' in globals() and not getattr(IntentClassifier.classify, '_jv4122_network_power_wrapped', False):
        _jv4122_orig_classify = IntentClassifier.classify

        def _jv4122_classify(self, text, *args, **kwargs):
            raw_text = text or ''
            t = raw_text.lower().strip().strip('.,;:!?¡¿')

            if any(key in t for key in (
                'estado de red', 'estado del wifi', 'estado del wi-fi',
                'como esta la red', 'cómo está la red', 'resumen de red'
            )):
                return Intent('network_status', 0.99, {}, raw_text)

            if any(key in t for key in (
                'cual es mi ip', 'cuál es mi ip', 'que ip tengo', 'qué ip tengo',
                'direccion ip', 'dirección ip', 'mi ip local'
            )):
                return Intent('network_ip', 0.99, {}, raw_text)

            if any(key in t for key in (
                'hay internet', 'tengo internet', 'prueba internet',
                'prueba de internet', 'test de internet', 'internet funciona'
            )):
                return Intent('network_test_internet', 0.99, {}, raw_text)

            if _jv4122_re.search(r'\b(lista|muestra|ver|escanea|buscar)\b', t) and _jv4122_re.search(r'\b(redes? wifi|wifi|wi-fi)\b', t):
                return Intent('network_list_wifi', 0.98, {}, raw_text)

            if _jv4122_re.search(r'\b(enciende|activa|prende|habilita)\b', t) and _jv4122_re.search(r'\b(wifi|wi-fi)\b', t):
                return Intent('network_wifi_on', 0.99, {}, raw_text)

            if _jv4122_re.search(r'\b(apaga|desactiva|deshabilita)\b', t) and _jv4122_re.search(r'\b(wifi|wi-fi)\b', t):
                return Intent('network_wifi_off', 0.99, {}, raw_text)

            if _jv4122_re.search(r'\b(enciende|activa|prende|habilita)\b', t) and 'bluetooth' in t:
                return Intent('network_bluetooth_on', 0.99, {}, raw_text)

            if _jv4122_re.search(r'\b(apaga|desactiva|deshabilita)\b', t) and 'bluetooth' in t:
                return Intent('network_bluetooth_off', 0.99, {}, raw_text)

            if any(key in t for key in ('bloquea la pantalla', 'bloquea la sesion', 'bloquea la sesión', 'lock screen', 'bloquear pantalla')):
                return Intent('power_lock_screen', 0.99, {}, raw_text)

            if any(key in t for key in ('suspende la pc', 'suspende el equipo', 'suspender la pc', 'suspender el equipo', 'suspendeme la pc', 'suspend')):
                return Intent('power_suspend', 0.99, {}, raw_text)

            if any(key in t for key in ('cierra sesion', 'cierra sesión', 'cerrar sesion', 'cerrar sesión', 'logout', 'sal de la sesion', 'sal de la sesión')):
                return Intent('power_logout', 0.99, {}, raw_text)

            if any(key in t for key in ('reinicia la pc', 'reinicia el equipo', 'reiniciar la pc', 'reiniciar el equipo', 'reboot')):
                return Intent('power_reboot', 0.99, {}, raw_text)

            if any(key in t for key in ('apaga la pc', 'apaga el equipo', 'apagar la pc', 'apagar el equipo', 'shutdown', 'apaga la computadora')):
                return Intent('power_shutdown', 0.99, {}, raw_text)

            return _jv4122_orig_classify(self, text, *args, **kwargs)

        _jv4122_classify._jv4122_network_power_wrapped = True
        IntentClassifier.classify = _jv4122_classify
except Exception:
    pass

# ---------------------------------------------------------------------------
# v4.1.2.3 phase 2B: devices + display direct intents
# ---------------------------------------------------------------------------
try:
    import re as _jv4123_re

    if 'IntentClassifier' in globals() and not getattr(IntentClassifier.classify, '_jv4123_devices_display_wrapped', False):
        _jv4123_orig_classify = IntentClassifier.classify

        def _jv4123_classify(self, text, *args, **kwargs):
            raw_text = text or ''
            t = raw_text.lower().strip().strip('.,;:!?¡¿')

            if any(key in t for key in (
                'estado de audio', 'dispositivos de audio', 'como esta el audio', 'cómo está el audio'
            )):
                return Intent('devices_audio_status', 0.99, {}, raw_text)

            if (_jv4123_re.search(r'\b(lista|muestra|ver|que|qué)\b', t) and _jv4123_re.search(r'\b(microfonos|micrófonos|micros|entradas de audio)\b', t)) or 'que microfono' in t or 'qué micrófono' in t:
                return Intent('devices_list_microphones', 0.98, {}, raw_text)

            if (_jv4123_re.search(r'\b(lista|muestra|ver|que|qué)\b', t) and _jv4123_re.search(r'\b(bocinas|salidas de audio|altavoces|speakers)\b', t)) or 'salida de audio' in t:
                return Intent('devices_list_speakers', 0.98, {}, raw_text)

            if _jv4123_re.search(r'\b(usa|cambia|pon|establece)\b', t) and _jv4123_re.search(r'\b(microfono|micrófono|entrada de audio)\b', t):
                target = t
                for prefix in ('usa ', 'cambia ', 'pon ', 'establece '):
                    if target.startswith(prefix):
                        target = target[len(prefix):]
                target = target.replace('el microfono', '').replace('el micrófono', '').replace('el dispositivo de entrada', '').replace('la entrada de audio', '').strip()
                return Intent('devices_set_default_input', 0.97, {'device': target}, raw_text)

            if _jv4123_re.search(r'\b(usa|cambia|pon|establece)\b', t) and _jv4123_re.search(r'\b(bocinas|altavoces|salida de audio|speaker|speakers)\b', t):
                target = t
                for prefix in ('usa ', 'cambia ', 'pon ', 'establece '):
                    if target.startswith(prefix):
                        target = target[len(prefix):]
                target = target.replace('las bocinas', '').replace('los altavoces', '').replace('la salida de audio', '').strip()
                return Intent('devices_set_default_output', 0.97, {'device': target}, raw_text)

            if (_jv4123_re.search(r'\b(lista|muestra|ver|que|qué)\b', t) and _jv4123_re.search(r'\b(camaras|cámaras|webcams|camaras web|cámaras web)\b', t)) or 'camara detectada' in t or 'cámara detectada' in t:
                return Intent('devices_list_cameras', 0.98, {}, raw_text)

            if (_jv4123_re.search(r'\b(lista|muestra|ver|que|qué)\b', t) and 'usb' in t) or 'dispositivos usb' in t:
                return Intent('devices_list_usb', 0.98, {}, raw_text)

            if any(key in t for key in ('estado de pantalla', 'estado del display', 'como esta la pantalla', 'cómo está la pantalla')):
                return Intent('display_status', 0.99, {}, raw_text)

            if (_jv4123_re.search(r'\b(lista|muestra|ver|que|qué)\b', t) and _jv4123_re.search(r'\b(monitores|pantallas)\b', t)):
                return Intent('display_list_monitors', 0.98, {}, raw_text)

            if _jv4123_re.search(r'\b(sube|aumenta|mas|más)\b', t) and 'brillo' in t:
                return Intent('display_brightness_up', 0.98, {}, raw_text)

            if _jv4123_re.search(r'\b(baja|reduce|menos)\b', t) and 'brillo' in t:
                return Intent('display_brightness_down', 0.98, {}, raw_text)

            m = _jv4123_re.search(r'brillo(?: al| a)?\s+(\d{1,3})', t)
            if m:
                percent = max(1, min(100, int(m.group(1))))
                return Intent('display_brightness_set', 0.99, {'percent': percent}, raw_text)

            if any(key in t for key in ('apaga la pantalla', 'duerme la pantalla', 'screen off')):
                return Intent('display_screen_off', 0.99, {}, raw_text)

            if any(key in t for key in ('duplica pantallas', 'modo espejo', 'duplica la pantalla', 'mirror display')):
                return Intent('display_mirror', 0.99, {}, raw_text)

            if any(key in t for key in ('extiende pantallas', 'modo extendido', 'extiende la pantalla', 'monitor extendido')):
                return Intent('display_extend', 0.99, {}, raw_text)

            if any(key in t for key in ('solo monitor externo', 'solo pantalla externa', 'usa solo monitor externo')):
                return Intent('display_external_only', 0.99, {}, raw_text)

            return _jv4123_orig_classify(self, text, *args, **kwargs)

        _jv4123_classify._jv4123_devices_display_wrapped = True
        IntentClassifier.classify = _jv4123_classify
except Exception:
    pass
