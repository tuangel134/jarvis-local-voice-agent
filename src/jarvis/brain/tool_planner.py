from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from jarvis.brain.intent_model import Intent
from jarvis.brain.tools import ToolCall
from jarvis.brain.event_journal import EventJournal


def _clean_spoken_query(value: str) -> str:
    """Limpia puntuación basura que deja Whisper al final de una búsqueda."""
    q = str(value or "").strip().lower()
    q = re.sub(r"^[\s\.,;:¡!¿\?\(\)\[\]\"']+", "", q)
    q = re.sub(r"[\s\.,;:¡!¿\?\(\)\[\]\"']+$", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q

try:
    from jarvis.brain.context_store import ContextStore
except Exception:  # pragma: no cover
    ContextStore = None  # type: ignore

try:
    from jarvis.brain.folder_index import FolderIndex
except Exception:  # pragma: no cover
    FolderIndex = None  # type: ignore

try:
    from jarvis.brain.memory_store import MemoryStore
except Exception:  # pragma: no cover
    MemoryStore = None  # type: ignore


class ToolPlanner:
    def _resolve_learned_alias(self, query: str) -> str:
        try:
            return EventJournal().resolve_alias(query)
        except Exception:
            return ""

    """
    Jarvis v3.1 Tool Planner.

    Importante:
    - Detecta comandos compuestos antes que reglas especiales como servidor 1.
    - "primer resultado" NO debe activar "servidor 1".
    - Convierte planes a Intent clásico para integrarse con el daemon actual.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.ctx = ContextStore(self.config) if ContextStore else None
        self.idx = FolderIndex(self.config) if FolderIndex else None
        self.memory = MemoryStore(self.config) if MemoryStore else None

    def plan(self, text: str) -> list[ToolCall]:
        raw = str(text or "").strip()
        t = self._norm(raw)

        if not t:
            return [ToolCall("respond", {"text": "No escuché un comando claro."})]

        t = self._strip_wake_prefix(t)

        # 1) PRIORIDAD MÁXIMA: compuestos de búsqueda + abrir resultado.
        #    Esto debe correr ANTES de servidor 1.
        compound = self._plan_search_and_open(raw, t)
        if compound:
            return compound

        # 2) Buscar dentro de última carpeta.
        search = self._plan_search(raw, t)
        if search:
            return search

        # 3) Abrir resultado anterior.
        result_ref = self._plan_open_result(raw, t)
        if result_ref:
            return result_ref

        # 4) Abrir carpeta explícita.
        folder = self._plan_open_folder(raw, t)
        if folder:
            return folder

        # 5) Música.
        music = self._plan_music(raw, t)
        if music:
            return music

        # 6) URLs conocidas.
        url = self._plan_url(raw, t)
        if url:
            return url

        # 7) Servicios.
        service = self._plan_service(raw, t)
        if service:
            return service

        # 8) Escaneo.
        if "escanea" in t or "recarga carpetas" in t or "actualiza carpetas" in t:
            return [ToolCall("scan_folders", {})]

        return [ToolCall("respond", {"text": raw})]

    def plan_to_intent(self, text: str) -> Intent | None:
        """Convierte el plan a un Intent clásico compatible con el daemon actual."""
        raw = str(text or "").strip()
        steps = self.plan(raw)

        if not steps:
            return None

        # search_files + open_result => search_file con open_first/open_index.
        if len(steps) >= 2 and steps[0].tool == "search_files" and steps[1].tool == "open_result":
            query = str(steps[0].params.get("query", "")).strip()
            base = steps[0].params.get("base") or self._last_folder()
            index = int(steps[1].params.get("index", 1) or 1)
            entities: dict[str, Any] = {
                "query": query,
                "open_first": True,
                "open_index": index,
            }
            if base:
                entities["path"] = str(base)
            return Intent("search_file", 0.99, entities, raw)

        # search_files simple.
        if len(steps) == 1 and steps[0].tool == "search_files":
            query = str(steps[0].params.get("query", "")).strip()
            base = steps[0].params.get("base") or self._last_folder()
            entities = {"query": query}
            if base:
                entities["path"] = str(base)
            return Intent("search_file", 0.97, entities, raw)

        # open_result simple: resolver desde contexto ahora mismo.
        if len(steps) == 1 and steps[0].tool == "open_result":
            index = int(steps[0].params.get("index", 1) or 1)
            path = self._search_result(index)
            if not path:
                return Intent("chat", 0.95, {"text": f"No tengo un resultado número {index} guardado."}, raw)
            p = Path(path).expanduser()
            if p.is_dir():
                return Intent("open_folder", 0.98, {"path": str(p), "target": p.name}, raw)
            return Intent("open_file", 0.98, {"path": str(p), "target": p.name}, raw)

        # resolve_folder + open_folder.
        if len(steps) >= 2 and steps[0].tool == "resolve_folder" and steps[1].tool == "open_folder":
            query = str(steps[0].params.get("query", "")).strip()
            path = self._resolve_folder(query)
            if path:
                return Intent("open_folder", 0.98, {"path": str(path), "target": Path(str(path)).name}, raw)
            return None

        # open_folder directo.
        if len(steps) == 1 and steps[0].tool == "open_folder":
            path = str(steps[0].params.get("path", "")).strip()
            if path:
                return Intent("open_folder", 0.98, {"path": path, "target": Path(path).name}, raw)

        # open_url.
        if len(steps) == 1 and steps[0].tool == "open_url":
            alias = str(steps[0].params.get("alias", "")).strip()
            url = str(steps[0].params.get("url", "")).strip()
            return Intent("open_url", 0.94, {"target": alias or url, "url": url or alias}, raw)

        # play_music.
        if len(steps) == 1 and steps[0].tool == "play_music":
            return Intent("play_music", 0.94, dict(steps[0].params), raw)

        # stop_music.
        if len(steps) == 1 and steps[0].tool == "stop_music":
            return Intent("stop_music", 0.95, {}, raw)

        # check_service.
        if len(steps) == 1 and steps[0].tool == "check_service":
            return Intent("service_status", 0.95, {"service": steps[0].params.get("service", "")}, raw)

        # scan_folders.
        if len(steps) == 1 and steps[0].tool == "scan_folders":
            return Intent("scan_folders", 0.90, {}, raw)

        # respond: dejar que el sistema viejo maneje chat para no romper conversación.
        return None

    def _plan_search_and_open(self, raw: str, t: str) -> list[ToolCall] | None:
        """
        Prioridad máxima para comandos compuestos de búsqueda + abrir resultado.

        Casos soportados:
        - busca media y abre el primer resultado
        - busca media en servidor 1 y abre el primero
        - abre servidor 1 y busca media y abre el primero
        - abre servidor 1 busca media y abre el primero

        Reglas importantes:
        - "primer resultado" NO debe activar Servidor1.
        - Si se menciona carpeta explícita, usar esa carpeta como base.
        - Si el usuario dijo "abre <carpeta>", el plan conserva open_folder antes de buscar.
        - Los índices siguen siendo 1-based en este proyecto: primero=1, segundo=2.
        """

        # A) "abre servidor 1 y busca media y abre el primero"
        #    "abre servidor 1 busca media y abre el primero"
        patterns_open_folder_then_search_open = [
            r"\babre\s+(.+?)\s+y\s+busca\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\babre\s+(.+?)\s+busca\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\babrir\s+(.+?)\s+y\s+busca\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\babro\s+(.+?)\s+y\s+busca\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
        ]
        for pat in patterns_open_folder_then_search_open:
            m = re.search(pat, t)
            if m:
                folder_q = self._clean_folder_query(m.group(1))
                query = self._clean_query(m.group(2))
                idx = self._parse_result_index(m.group(3))
                base = self._resolve_folder(folder_q) or self._last_folder()
                steps = []
                if base:
                    steps.append(ToolCall("open_folder", {"path": str(base)}))
                steps.append(ToolCall("search_files", {"query": query, "base": base}))
                steps.append(ToolCall("open_result", {"index": idx}))
                return steps

        # B) "busca media en servidor 1 y abre el primero"
        patterns_search_in_folder_then_open = [
            r"\bbusca\s+(.+?)\s+en\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\bbuscar\s+(.+?)\s+en\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\bencuentra\s+(.+?)\s+en\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
        ]
        for pat in patterns_search_in_folder_then_open:
            m = re.search(pat, t)
            if m:
                query = self._clean_query(m.group(1))
                folder_q = self._clean_folder_query(m.group(2))
                idx = self._parse_result_index(m.group(3))
                base = self._resolve_folder(folder_q) or self._last_folder()
                return [
                    ToolCall("search_files", {"query": query, "base": base}),
                    ToolCall("open_result", {"index": idx}),
                ]

        # C) "busca media y abre el primer resultado" dentro de última carpeta.
        patterns = [
            r"\bbusca\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\bbuscar\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
            r"\bencuentra\s+(.+?)\s+y\s+abre\s+(?:el\s+)?(primer|primero|segundo|tercero|cuarto|quinto|1|2|3|4|5)(?:\s+resultado|\s+opcion|\s+opción)?\b",
        ]
        for pat in patterns:
            m = re.search(pat, t)
            if m:
                query = self._clean_query(m.group(1))
                idx = self._parse_result_index(m.group(2))
                base = self._last_folder()
                return [
                    ToolCall("search_files", {"query": query, "base": base}),
                    ToolCall("open_result", {"index": idx}),
                ]
        return None

    def _plan_search(self, raw: str, t: str) -> list[ToolCall] | None:
        """
        Búsqueda simple.

        Casos soportados:
        - busca ahí media
        - busca media
        - busca media en servidor 1
        - abre servidor 1 y busca media
        - abre servidor 1 busca media

        Si el usuario dice "abre <carpeta> y busca <query>", se devuelven dos pasos:
        open_folder + search_files. El daemon actual lo ejecuta como search_file con
        pre_open_folder para no perder la acción de abrir.
        """

        # A) "abre servidor 1 y busca media" / "abre servidor 1 busca media".
        patterns_open_folder_then_search = [
            r"\babre\s+(.+?)\s+y\s+busca\s+(.+)$",
            r"\babre\s+(.+?)\s+busca\s+(.+)$",
            r"\babrir\s+(.+?)\s+y\s+busca\s+(.+)$",
            r"\babro\s+(.+?)\s+y\s+busca\s+(.+)$",
            r"\babres\s+(.+?)\s+y\s+busca\s+(.+)$",
        ]
        for pat in patterns_open_folder_then_search:
            m = re.search(pat, t)
            if m:
                folder_q = self._clean_folder_query(m.group(1))
                query = self._clean_query(m.group(2))
                if not query:
                    return None
                base = self._resolve_folder(folder_q) or self._last_folder()
                steps = []
                if base:
                    steps.append(ToolCall("open_folder", {"path": str(base)}))
                steps.append(ToolCall("search_files", {"query": query, "base": base}))
                return steps

        # B) "busca media en servidor 1".
        patterns_search_in_folder = [
            r"\bbusca\s+(.+?)\s+en\s+(.+)$",
            r"\bbuscar\s+(.+?)\s+en\s+(.+)$",
            r"\bencuentra\s+(.+?)\s+en\s+(.+)$",
            r"\bbuscame\s+(.+?)\s+en\s+(.+)$",
            r"\bbúscame\s+(.+?)\s+en\s+(.+)$",
        ]
        for pat in patterns_search_in_folder:
            m = re.search(pat, t)
            if m:
                query = self._clean_query(m.group(1))
                folder_q = self._clean_folder_query(m.group(2))
                if not query:
                    return None
                base = self._resolve_folder(folder_q) or self._last_folder()
                return [ToolCall("search_files", {"query": query, "base": base})]

        # C) "busca ahí media" / "busca media" en last_folder.
        m = re.search(r"\b(?:busca|buscar|encuentra|buscame|búscame)\s+(?:ahi|ahí|en esa carpeta|dentro)?\s*(.+)$", t)
        if not m:
            return None
        query = self._clean_query(m.group(1))
        if not query:
            return None
        # Evitar capturar búsquedas web conocidas; el sistema viejo ya maneja Google/Youtube.
        if any(x in t for x in ["google", "youtube", "internet", "web"]):
            return None
        return [ToolCall("search_files", {"query": query, "base": self._last_folder()})]

    def _plan_open_result(self, raw: str, t: str) -> list[ToolCall] | None:
        # MUY IMPORTANTE: no tratar "servidor 1" como resultado 1.
        if "servidor" in t or "server" in t or "serobidor" in t:
            return None
        if not any(x in t for x in ["resultado", "primero", "primer", "segundo", "tercero", "opcion", "opción", "ese", "esa"]):
            return None
        if not any(x in t for x in ["abre", "abrir", "abro", "muestra", "ensename", "enseñame"]):
            return None
        return [ToolCall("open_result", {"index": self._parse_result_index(t)})]

    def _plan_open_folder(self, raw: str, t: str) -> list[ToolCall] | None:
        if not any(x in t for x in ["abre", "abrir", "abro", "abres", "abra", "muestra"]):
            return None
        # No convertir comandos compuestos de búsqueda en abrir carpeta.
        if "resultado" in t and ("busca" in t or "buscar" in t or "encuentra" in t):
            return None
        q = re.sub(r"\b(abre|abrir|abro|abres|abra|muestra|la|el|carpeta|folder|directorio|de|del)\b", " ", t)
        q = self._clean_query(q)
        if not q:
            return None
        path = self._resolve_folder(q)
        if path:
            return [ToolCall("open_folder", {"path": str(path)})]
        return [ToolCall("resolve_folder", {"query": q}), ToolCall("open_folder", {"path": "$resolved"})]

    def _plan_music(self, raw: str, t: str) -> list[ToolCall] | None:
        if any(x in t for x in ["deten la musica", "detén la música", "para la musica", "pausa la musica", "stop music"]):
            return [ToolCall("stop_music", {})]
        m = re.search(r"\b(?:reproduce|ponme|pon|toca)\s+(.+?)(?:\s+en\s+(youtube|spotify|tidal))?$", t)
        if m:
            return [ToolCall("play_music", {"query": self._clean_query(m.group(1)), "platform": m.group(2) or "youtube"})]
        return None

    def _plan_url(self, raw: str, t: str) -> list[ToolCall] | None:
        if not any(x in t for x in ["abre", "abrir", "abro"]):
            return None
        known = ["youtube", "google", "play console", "github", "groq", "chatgpt", "firebase", "whatsapp", "gmail", "drive"]
        for name in known:
            if name in t:
                return [ToolCall("open_url", {"alias": name})]
        return None

    def _plan_service(self, raw: str, t: str) -> list[ToolCall] | None:
        if "servidor de peliculas" in t or "servidor de películas" in raw.lower():
            return [ToolCall("check_service", {"service": "jellyfin"})]
        if "jellyfin" in t and any(x in t for x in ["revisa", "estado", "activo"]):
            return [ToolCall("check_service", {"service": "jellyfin"})]
        return None

    def _resolve_folder(self, query: str) -> str | None:
        learned_alias = self._resolve_learned_alias(query)
        if learned_alias:
            return learned_alias

        q = self._norm(query)
        compact = q.replace(" ", "")

        # Aliases naturales. Esto NO se activa para "primer resultado" porque _plan_open_folder lo bloquea.
        if any(x in q for x in ["servidor 1", "servidor uno", "serobidor 1"]) or "servidor1" in compact:
            return str(Path.home() / "Escritorio" / "Servidor1")
        if any(x in q for x in ["servidor 2", "servidor dos", "serobidor 2"]) or "servidor2" in compact:
            return str(Path.home() / "Escritorio" / "Servidor2")
        if q in ["descargas", "downloads"]:
            return str(Path.home() / "Descargas")
        if q in ["documentos", "documents"]:
            return str(Path.home() / "Documentos")
        if q in ["escritorio", "desktop"]:
            return str(Path.home() / "Escritorio")

        # Memoria si existe.
        if self.memory:
            try:
                m = self.memory.resolve_folder(query) or self.memory.resolve_folder(q)
                if m:
                    return str(m)
            except Exception:
                pass

        # Índice si existe.
        if self.idx:
            try:
                match = self.idx.best(query, min_score=45)
                if match:
                    return str(match.path)
            except Exception:
                pass
        return None

    def _last_folder(self) -> str:
        if self.ctx:
            try:
                return self.ctx.get_last_folder()
            except Exception:
                return ""
        return ""

    def _search_result(self, index_1_based: int) -> str:
        if self.ctx:
            try:
                return self.ctx.get_search_result(index_1_based)
            except Exception:
                return ""
        return ""

    def _parse_result_index(self, text: str) -> int:
        t = self._norm(text)
        if any(w in t for w in ["segundo", "segunda", " 2", "numero 2", "número 2"]):
            return 2
        if any(w in t for w in ["tercero", "tercer", "tercera", " 3", "numero 3", "número 3"]):
            return 3
        if any(w in t for w in ["cuarto", "cuarta", " 4", "numero 4", "número 4"]):
            return 4
        if any(w in t for w in ["quinto", "quinta", " 5", "numero 5", "número 5"]):
            return 5
        return 1

    def _clean_folder_query(self, text: str) -> str:
        """Limpia frases de carpeta sin quitar números importantes como servidor 1."""
        q = self._norm(text)
        q = re.sub(r"\b(abre|abrir|abro|abres|abra|muestra|la|el|carpeta|folder|directorio|de|del|en|ahi|ahí)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _clean_query(self, text: str) -> str:
        q = self._norm(text)
        q = re.sub(r"\b(resultado|resultados|opcion|opción|primero|primer|primera|segundo|tercero|cuarto|quinto|abre|abrir|el|la|los|las|de|del|en|ahi|ahí)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _strip_wake_prefix(self, t: str) -> str:
        t = re.sub(r"^(hey|ey|oye)?\s*(jarvis|yervis|jervis|gervis|harvis)\s*", "", t).strip()
        return t

    def _norm(self, text: str) -> str:
        text = str(text or "").lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\s:/._-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

# ---------------------------------------------------------------------------
# Jarvis v3.1.6 fixed: limpieza final de query en ToolPlanner.
# Evita que frases como "busca media." generen query="media.".
# Se aplica como wrapper para no depender de la forma interna del planner.
# ---------------------------------------------------------------------------
def _jarvis_v31_6_clean_query_value(value):
    import re
    if value is None:
        return value
    q = str(value).strip()
    q = re.sub(r'^[\s"\'“”‘’¡¿]+', '', q)
    q = re.sub(r'[\s"\'“”‘’.,;:!?]+$', '', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q


def _jarvis_v31_6_patch_planner_class(cls):
    if getattr(cls, "_jarvis_v31_6_query_cleanup", False):
        return
    old_plan = cls.plan

    def plan(self, text, *args, **kwargs):
        steps = old_plan(self, text, *args, **kwargs)
        try:
            for step in steps or []:
                params = getattr(step, "params", None)
                if isinstance(params, dict):
                    for key in ("query", "search_query"):
                        if key in params:
                            params[key] = _jarvis_v31_6_clean_query_value(params[key])
        except Exception:
            # No romper el planner por una limpieza de texto.
            pass
        return steps

    cls.plan = plan
    cls._jarvis_v31_6_query_cleanup = True


for _jarvis_v31_6_cls_name in ("ToolPlanner", "Planner"):
    _jarvis_v31_6_cls = globals().get(_jarvis_v31_6_cls_name)
    if _jarvis_v31_6_cls is not None and hasattr(_jarvis_v31_6_cls, "plan"):
        _jarvis_v31_6_patch_planner_class(_jarvis_v31_6_cls)

# ---------------------------------------------------------------------------
# v3.4.8 compatibility: clean dictated Android extension queries in planner output
# ---------------------------------------------------------------------------
try:
    import re as _jarvis_planner_re

    def _jarvis_v34_8_clean_planner_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jarvis_planner_re.sub(r"\s+", " ", q).strip()
        corrections = {
            "a a b": "aab",
            "a a ve": "aab",
            "aave": "aab",
            "aap": "aab",
            "abb": "aab",
        }
        if q in corrections:
            return corrections[q]
        q = _jarvis_planner_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jarvis_planner_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jarvis_planner_re.sub(r"\b(aap|abb|aave)\b", "aab", q)
        return _jarvis_planner_re.sub(r"\s+", " ", q).strip()

    def _jarvis_v34_8_clean_step(step):
        if isinstance(step, dict):
            params = step.get("params") or {}
            if isinstance(params, dict):
                if "query" in params:
                    params["query"] = _jarvis_v34_8_clean_planner_query(params.get("query"))
                if "search_query" in params:
                    params["search_query"] = _jarvis_v34_8_clean_planner_query(params.get("search_query"))
        return step

    def _jarvis_v34_8_clean_plan_result(result):
        if isinstance(result, list):
            return [_jarvis_v34_8_clean_step(s) for s in result]
        if isinstance(result, dict):
            if isinstance(result.get("planner_steps"), list):
                result["planner_steps"] = [_jarvis_v34_8_clean_step(s) for s in result["planner_steps"]]
            if isinstance(result.get("steps"), list):
                result["steps"] = [_jarvis_v34_8_clean_step(s) for s in result["steps"]]
        if hasattr(result, "steps") and isinstance(getattr(result, "steps"), list):
            result.steps = [_jarvis_v34_8_clean_step(s) for s in result.steps]
        if hasattr(result, "planner_steps") and isinstance(getattr(result, "planner_steps"), list):
            result.planner_steps = [_jarvis_v34_8_clean_step(s) for s in result.planner_steps]
        return result

    if "ToolPlanner" in globals():
        for _jarvis_method_name in ("plan", "parse", "create_plan"):
            if hasattr(ToolPlanner, _jarvis_method_name):
                _jarvis_orig = getattr(ToolPlanner, _jarvis_method_name)
                if not getattr(_jarvis_orig, "_jarvis_v34_8_wrapped", False):
                    def _make_wrapper(orig):
                        def _wrapped(self, *args, **kwargs):
                            return _jarvis_v34_8_clean_plan_result(orig(self, *args, **kwargs))
                        _wrapped._jarvis_v34_8_wrapped = True
                        return _wrapped
                    setattr(ToolPlanner, _jarvis_method_name, _make_wrapper(_jarvis_orig))
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.9 compatibility: alias fuzzy resolver + dictated Android extension cleanup
# ---------------------------------------------------------------------------
try:
    import re as _jv349_re
    import difflib as _jv349_difflib

    def _jv349_clean_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv349_re.sub(r"\s+", " ", q).strip()

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

        q = _jv349_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv349_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jv349_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        return _jv349_re.sub(r"\s+", " ", q).strip()

    def _jv349_clean_params(params):
        if not isinstance(params, dict):
            return params
        for key in ("query", "search_query"):
            if key in params:
                params[key] = _jv349_clean_query(params.get(key))
        return params

    def _jv349_clean_step(step):
        if isinstance(step, dict):
            params = step.get("params")
            if isinstance(params, dict):
                _jv349_clean_params(params)
        elif hasattr(step, "params"):
            params = getattr(step, "params", None)
            if isinstance(params, dict):
                _jv349_clean_params(params)
        return step

    def _jv349_clean_result(result):
        # Plan result may be list[dict], dict with steps/planner_steps, SemanticAction, Intent, etc.
        if isinstance(result, list):
            return [_jv349_clean_step(x) for x in result]

        if isinstance(result, dict):
            for key in ("planner_steps", "steps"):
                if isinstance(result.get(key), list):
                    result[key] = [_jv349_clean_step(x) for x in result[key]]
            if isinstance(result.get("params"), dict):
                _jv349_clean_params(result["params"])
            if isinstance(result.get("entities"), dict):
                _jv349_clean_params(result["entities"])
            if "query" in result:
                result["query"] = _jv349_clean_query(result.get("query"))
            return result

        for attr in ("planner_steps", "steps"):
            if hasattr(result, attr) and isinstance(getattr(result, attr), list):
                setattr(result, attr, [_jv349_clean_step(x) for x in getattr(result, attr)])

        for attr in ("params", "entities"):
            if hasattr(result, attr) and isinstance(getattr(result, attr), dict):
                _jv349_clean_params(getattr(result, attr))

        if hasattr(result, "query"):
            try:
                setattr(result, "query", _jv349_clean_query(getattr(result, "query")))
            except Exception:
                pass

        return result

    # Wrap all ToolPlanner public callables that may return plans/actions.
    if "ToolPlanner" in globals() and not getattr(ToolPlanner, "_jv349_all_wrapped", False):
        for _name, _value in list(ToolPlanner.__dict__.items()):
            if _name.startswith("__"):
                continue
            if not callable(_value):
                continue
            if _name in {"_jv349_all_wrapped"}:
                continue
            if getattr(_value, "_jv349_wrapped", False):
                continue

            def _make_wrapper(_orig):
                def _wrapped(self, *args, **kwargs):
                    return _jv349_clean_result(_orig(self, *args, **kwargs))
                _wrapped._jv349_wrapped = True
                return _wrapped

            try:
                setattr(ToolPlanner, _name, _make_wrapper(_value))
            except Exception:
                pass
        ToolPlanner._jv349_all_wrapped = True

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
    if "ToolPlanner" in globals() and not getattr(ToolPlanner, "_jv3414_wrapped", False):
        for _name, _value in list(ToolPlanner.__dict__.items()):
            if _name.startswith("__") or not callable(_value) or getattr(_value, "_jv3414_wrapped", False):
                continue

            def _jv3414_make_wrapper(orig):
                def _wrapped(self, *args, **kwargs):
                    return _jv3414_clean_any(orig(self, *args, **kwargs))
                _wrapped._jv3414_wrapped = True
                return _wrapped

            try:
                setattr(ToolPlanner, _name, _jv3414_make_wrapper(_value))
            except Exception:
                pass

        ToolPlanner._jv3414_wrapped = True
except Exception:
    pass

