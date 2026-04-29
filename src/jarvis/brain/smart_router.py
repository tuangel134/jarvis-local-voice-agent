from __future__ import annotations

import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from jarvis.brain.action_schema import SemanticAction
from jarvis.brain.folder_index import FolderIndex
from jarvis.brain.discovery_agent import DiscoveryAgent
from jarvis.brain.memory_store import MemoryStore
from jarvis.brain.context_store import ContextStore
from jarvis.brain.semantic_router import SemanticRouter as BaseSemanticRouter


class SmartRouter:
    """
    Capa de inteligencia extra sobre SemanticRouter.

    Objetivo:
    - No dejar que frases de acción caigan fácil en chat.
    - Reparar malas transcripciones.
    - Usar índice de carpetas.
    - Abrir búsquedas en Google/YouTube.
    - Resolver carpetas ocultas tipo "punto hermes".
    - Mantener seguridad: solo devuelve SemanticAction, no ejecuta comandos.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.discovery = DiscoveryAgent(self.config)
        self.base = BaseSemanticRouter(self.config)
        self.memory = MemoryStore(self.config)
        self.folder_index = FolderIndex(self.config)
        self.context = ContextStore(self.config)

    def parse(self, text: str) -> SemanticAction:
        raw = (text or "").strip()

        # V26: prioridad absoluta para carpetas Servidor1/Servidor2.
        # Esto evita que "servidor 1" sea interpretado como "abre el primer resultado".
        server_priority = self._v26_server_folder_priority(raw)
        if server_priority:
            return server_priority

        if not raw:
            return SemanticAction(action="unknown", confidence=0.0, text=raw, source="smart_empty")

        # v3 discovery_direct: prioridad antes de contexto/resultados/chat.
        direct = self.discovery.semantic_direct(raw)
        if direct is not None:
            return direct

        forced_server = self._v27_force_server_folder(raw)
        if forced_server:
            return forced_server

        base_action = self.base.parse(raw)

        # Si el router base ya resolvió algo real, respetarlo.
        if base_action.normalized_action() not in {"chat", "unknown"}:
            return base_action

        # Respetar respuestas internas de memoria.
        if base_action.source == "memory" and str(base_action.reason).startswith("memory_"):
            return base_action

        repaired = self._repair_action(raw)

        if repaired:
            return repaired

        return base_action

    def _v26_server_folder_priority(self, raw: str) -> SemanticAction | None:
        """
        Prioridad absoluta para abrir Servidor1/Servidor2.

        Arregla frases y transcripciones como:
        - abre la carpeta servidor 1
        - abres servidor 1
        - abre la carpeta serobidor 1
        - abré la carpeta del servidor 1
        - abre servidor dos
        """
        original = str(raw or "")
        t = original.lower().strip()
        t = unicodedata.normalize("NFKD", t)
        t = "".join(c for c in t if not unicodedata.combining(c))
        t = re.sub(r"[^a-z0-9ñ\s]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        compact = t.replace(" ", "")

        open_like = (
            "abre" in t
            or "abres" in t
            or "abro" in t
            or "abrir" in t
            or "abras" in t
            or "abrela" in compact
            or compact.startswith("abre")
            or compact.startswith("abri")
            or compact.startswith("abro")
        )

        server_like = (
            "servidor" in t
            or "server" in t
            or "serobidor" in t
            or "serbidor" in t
            or "servidor" in compact
            or "server" in compact
            or "serobidor" in compact
            or "serbidor" in compact
        )

        if not (open_like and server_like):
            return None

        is_one = (
            " 1" in f" {t}"
            or t.endswith("1")
            or "uno" in t
            or "servidor1" in compact
            or "server1" in compact
            or "serobidor1" in compact
            or "serbidor1" in compact
        )

        is_two = (
            " 2" in f" {t}"
            or t.endswith("2")
            or "dos" in t
            or "servidor2" in compact
            or "server2" in compact
            or "serobidor2" in compact
            or "serbidor2" in compact
        )

        if is_one:
            return SemanticAction(
                action="open_folder",
                confidence=0.999,
                path="/home/angel/Escritorio/Servidor1",
                folder="Servidor1",
                text=raw,
                reason="v26_server_priority",
                source="v26_server_priority",
            )

        if is_two:
            return SemanticAction(
                action="open_folder",
                confidence=0.999,
                path="/home/angel/Escritorio/Servidor2",
                folder="Servidor2",
                text=raw,
                reason="v26_server_priority",
                source="v26_server_priority",
            )

        return None


    def _v27_force_server_folder(self, raw: str) -> SemanticAction | None:
        # Prioridad absoluta para carpetas físicas Servidor1/Servidor2.
        t = self._norm(raw)
        compact = t.replace(" ", "")

        openish = (
            "abre" in t
            or "abres" in t
            or "abra" in t
            or "abro" in t
            or "abrir" in t
            or "abri" in t
            or "carpeta" in t
            or "carpita" in t
            or "acarpita" in t
            or "folder" in t
            or "directorio" in t
            or compact.startswith("abre")
            or compact.startswith("abra")
            or compact.startswith("abri")
            or compact.startswith("abro")
        )

        server1 = (
            re.search(r"\b(servidor|serobidor|server)\s*(1|uno)\b", t) is not None
            or "servidor1" in compact
            or "serobidor1" in compact
            or "server1" in compact
        )

        server2 = (
            re.search(r"\b(servidor|serobidor|server)\s*(2|dos)\b", t) is not None
            or "servidor2" in compact
            or "serobidor2" in compact
            or "server2" in compact
        )

        if server1 and (openish or "servidor" in t or "serobidor" in t or "server" in t):
            return SemanticAction(
                action="open_folder",
                confidence=0.999,
                path="/home/angel/Escritorio/Servidor1",
                folder="Servidor1",
                text=raw,
                reason="v27_server_absolute_priority",
                source="v27_server_absolute_priority",
            )

        if server2 and (openish or "servidor" in t or "serobidor" in t or "server" in t):
            return SemanticAction(
                action="open_folder",
                confidence=0.999,
                path="/home/angel/Escritorio/Servidor2",
                folder="Servidor2",
                text=raw,
                reason="v27_server_absolute_priority",
                source="v27_server_absolute_priority",
            )

        return None


    def _repair_action(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)
        compact = t.replace(" ", "")

        # 0. Acciones usando contexto: ahí, esa carpeta, anterior, última carpeta.
        contextual = self._context_action(raw, t)
        if contextual:
            return contextual

        # 1. Carpetas especiales/ocultas tipo "punto hermes".
        hidden = self._hidden_folder_action(raw, t)
        if hidden:
            return hidden

        # 2. Servidor1/Servidor2 siempre como carpeta cuando se pide abrir.
        server = self._server_folder_action(raw, t, compact)
        if server:
            return server

        # 3. Búsquedas web.
        search = self._search_action(raw, t)
        if search:
            return search

        # 4. Carpetas por índice.
        folder = self._indexed_folder_action(raw, t, compact)
        if folder:
            return folder

        # 5. Webs conocidas.
        url = self._known_url_action(raw, t)
        if url:
            return url

        # 6. Apps conocidas.
        app = self._known_app_action(raw, t)
        if app:
            return app

        # 7. Música por frase flexible.
        music = self._music_action(raw, t)
        if music:
            return music

        # 8. Frases de acción no resueltas: evitar que el LLM finja ejecución.
        if self._looks_like_action(t, compact):
            return SemanticAction(
                action="chat",
                confidence=0.90,
                text="No encontré una acción segura para ejecutar eso. Prueba con un nombre más específico.",
                reason="unresolved_action_not_executed",
                source="smart_router",
            )

        return None

    def _context_action(self, raw: str, t: str) -> SemanticAction | None:
        # V26: si menciona servidor, NO usar resultados de búsqueda previos.
        # Servidor1/2 se resuelve arriba por _v26_server_folder_priority.
        if any(x in t for x in ["servidor", "server", "serobidor", "serbidor"]):
            return None
        last_folder = self.context.get_last_folder()
        previous_folder = self.context.get_previous_folder()
        asks_context = ("que tienes en contexto" in t or "qué tienes en contexto" in raw.lower() or "contexto actual" in t or "que recuerdas de contexto" in t)
        if asks_context:
            return SemanticAction(action="chat", confidence=0.98, text=self.context.describe(), reason="context_describe", source="context")
        asks_results = ("muestrame los resultados" in t or "muéstrame los resultados" in raw.lower() or "dime los resultados" in t or "lista resultados" in t or "ver resultados" in t or "que encontraste" in t or "qué encontraste" in raw.lower())
        if asks_results:
            return SemanticAction(action="chat", confidence=0.98, text=self.context.describe_results(limit=10), reason="context_show_results", source="context")
        result_index = self._extract_result_index(t)
        wants_open_result = result_index is not None and ("abre" in t or "abro" in t or "abrir" in t or "muestra" in t or "ensename" in t or "enséñame" in raw.lower())
        if wants_open_result:
            path = self.context.get_search_result(result_index)
            if not path:
                return SemanticAction(action="chat", confidence=0.95, text=f"No tengo un resultado número {result_index} guardado.", reason="context_result_missing", source="context")
            p = Path(path).expanduser()
            if p.is_dir():
                return SemanticAction(action="open_folder", confidence=0.98, path=str(p), folder=p.name, text=raw, reason=f"context_open_result_{result_index}", source="context")
            return SemanticAction(action="open_file", confidence=0.98, path=str(p), folder=p.name, text=raw, reason=f"context_open_result_{result_index}", source="context")
        wants_previous = ("carpeta anterior" in t or "abre la anterior" in t or "vuelve a la anterior" in t or "vuelve a esa carpeta" in t or "abre la ultima carpeta" in t or "abre la última carpeta" in raw.lower() or "abre esa carpeta" in t)
        if wants_previous:
            path = previous_folder if "anterior" in t and previous_folder else last_folder
            if path:
                return SemanticAction(action="open_folder", confidence=0.97, path=path, folder=Path(path).name, text=raw, reason="context_open_folder", source="context")
        refers_here = ("ahi" in t or "ahí" in raw.lower() or "alli" in t or "allí" in raw.lower() or "esa carpeta" in t or "en esa carpeta" in t or "en la carpeta actual" in t or "dentro de esa carpeta" in t or "dentro" in t)
        wants_search = ("busca" in t or "buscar" in t or "encuentra" in t or "buscame" in t or "búscame" in raw.lower())
        if wants_search and refers_here and last_folder:
            query = self._extract_context_search_query(raw) or "."
            return SemanticAction(action="search_file", confidence=0.96, search_query=query, path=last_folder, text=raw, reason="context_search_in_last_folder", source="context")
        return None


    def _extract_result_index(self, t: str) -> int | None:
        compact = t.replace(" ", "")
        mapping = {"primero": 1, "primer": 1, "uno": 1, "1": 1, "segundo": 2, "dos": 2, "2": 2, "tercero": 3, "tres": 3, "3": 3, "cuarto": 4, "cuatro": 4, "4": 4, "quinto": 5, "cinco": 5, "5": 5, "sexto": 6, "seis": 6, "6": 6, "septimo": 7, "séptimo": 7, "siete": 7, "7": 7, "octavo": 8, "ocho": 8, "8": 8, "noveno": 9, "nueve": 9, "9": 9, "decimo": 10, "décimo": 10, "diez": 10, "10": 10}
        for word, idx in mapping.items():
            if word in t.split() or word in compact:
                return idx
        if "ese" in t or "esa" in t:
            return 1
        return None

    def _extract_context_search_query(self, raw: str) -> str:
        q = self._norm(raw)

        remove = [
            "busca ahi",
            "busca ahí",
            "buscar ahi",
            "buscar ahí",
            "busca en esa carpeta",
            "buscar en esa carpeta",
            "busca dentro de esa carpeta",
            "buscar dentro de esa carpeta",
            "buscame ahi",
            "búscame ahí",
            "encuentra ahi",
            "encuentra ahí",
            "archivos",
            "archivo",
            "carpetas",
            "carpeta",
            "ahi",
            "ahí",
            "alli",
            "allí",
            "en",
            "de",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")

        q = re.sub(r"\s+", " ", q).strip()
        return q


    def _hidden_folder_action(self, raw: str, t: str) -> SemanticAction | None:
        if not self._looks_like_open(t, t.replace(" ", "")):
            return None

        hidden_map = {
            "punto hermes": Path.home() / ".hermes",
            "dot hermes": Path.home() / ".hermes",
            ".hermes": Path.home() / ".hermes",
            "punto config": Path.home() / ".config",
            "dot config": Path.home() / ".config",
            ".config": Path.home() / ".config",
            "punto local": Path.home() / ".local",
            "dot local": Path.home() / ".local",
            ".local": Path.home() / ".local",
            "punto cache": Path.home() / ".cache",
            "dot cache": Path.home() / ".cache",
            ".cache": Path.home() / ".cache",
        }

        for phrase, path in hidden_map.items():
            if phrase in t or phrase.replace(" ", "") in t.replace(" ", ""):
                return SemanticAction(
                    action="open_folder",
                    confidence=0.99,
                    path=str(path),
                    folder=path.name,
                    text=raw,
                    reason="smart_hidden_folder",
                    source="smart_router",
                )

        return None

    def _server_folder_action(self, raw: str, t: str, compact: str) -> SemanticAction | None:
        if not self._looks_like_open(t, compact):
            return None

        if (
            "servidor 1" in t
            or "servidor uno" in t
            or "servidor1" in compact
            or "server 1" in t
            or "server1" in compact
        ):
            return SemanticAction(
                action="open_folder",
                confidence=0.995,
                path="/home/angel/Escritorio/Servidor1",
                folder="Servidor1",
                text=raw,
                reason="smart_server_folder",
                source="smart_router",
            )

        if (
            "servidor 2" in t
            or "servidor dos" in t
            or "servidor2" in compact
            or "server 2" in t
            or "server2" in compact
        ):
            return SemanticAction(
                action="open_folder",
                confidence=0.995,
                path="/home/angel/Escritorio/Servidor2",
                folder="Servidor2",
                text=raw,
                reason="smart_server_folder",
                source="smart_router",
            )

        return None

    def _search_action(self, raw: str, t: str) -> SemanticAction | None:
        if not any(x in t for x in ["busca", "buscar", "buscame", "búscame", "googlea", "investiga"]):
            return None

        if "youtube" in t or "you tube" in t or "yutube" in t:
            q = self._extract_search_query(raw, platform="youtube")
            if q:
                return SemanticAction(
                    action="open_url",
                    confidence=0.96,
                    url="https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q),
                    url_name="youtube search",
                    text=raw,
                    reason="smart_youtube_search",
                    source="smart_router",
                )

        if "google" in t or "internet" in t or "web" in t or "busca" in t or "googlea" in t:
            q = self._extract_search_query(raw, platform="google")
            if q:
                return SemanticAction(
                    action="open_url",
                    confidence=0.96,
                    url="https://www.google.com/search?q=" + urllib.parse.quote_plus(q),
                    url_name="google search",
                    text=raw,
                    reason="smart_google_search",
                    source="smart_router",
                )

        return None

    def _indexed_folder_action(self, raw: str, t: str, compact: str) -> SemanticAction | None:
        if not (
            self._looks_like_open(t, compact)
            or "carpeta" in t
            or "carpita" in t
            or "folder" in t
            or "directorio" in t
        ):
            return None

        # Evitar que búsquedas web o música caigan a carpetas.
        if any(x in t for x in ["youtube", "spotify", "tidal", "google", "play console", "reproduce", "ponme"]):
            return None

        q = self._extract_folder_query(raw)

        if not q:
            return None

        # Primero memoria exacta/fuzzy segura.
        memory_path = self.memory.resolve_folder(q) or self.memory.resolve_folder(raw)

        if memory_path:
            return SemanticAction(
                action="open_folder",
                confidence=0.98,
                path=memory_path,
                folder=q,
                text=raw,
                reason="smart_memory_folder",
                source="smart_router",
            )

        match = self.folder_index.best(q, min_score=45)

        if not match:
            return None

        return SemanticAction(
            action="open_folder",
            confidence=0.94,
            path=match.path,
            folder=match.name,
            text=raw,
            reason=f"smart_folder_index:{match.reason}",
            source="smart_router",
        )

    def _known_url_action(self, raw: str, t: str) -> SemanticAction | None:
        if not self._looks_like_open(t, t.replace(" ", "")):
            return None

        mapping = {
            "play console": "google play console",
            "google play console": "google play console",
            "panel de apps": "google play console",
            "donde subo mis apps": "google play console",
            "firebase": "firebase",
            "revenuecat": "revenuecat",
            "expo": "expo",
            "github": "github",
            "groq": "groq",
            "openrouter": "openrouter",
            "chatgpt": "chatgpt",
            "claude": "claude",
            "gemini": "gemini",
            "gmail": "gmail",
            "drive": "drive",
            "whatsapp": "whatsapp",
            "telegram": "telegram",
            "youtube": "youtube",
            "youtube music": "youtube music",
            "tidal": "tidal",
            "spotify": "spotify",
        }

        for phrase, url_name in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
            if phrase in t:
                return SemanticAction(
                    action="open_url",
                    confidence=0.95,
                    url_name=url_name,
                    text=raw,
                    reason="smart_known_url",
                    source="smart_router",
                )

        return None

    def _known_app_action(self, raw: str, t: str) -> SemanticAction | None:
        if not self._looks_like_open(t, t.replace(" ", "")):
            return None

        mapping = {
            "calculadora": "calculadora",
            "calculator": "calculator",
            "terminal": "terminal",
            "consola": "terminal",
            "archivos": "archivos",
            "explorador": "archivos",
            "monitor del sistema": "monitor del sistema",
            "vscode": "vscode",
            "visual studio code": "visual studio code",
            "cursor": "cursor",
            "vlc": "vlc",
            "obs": "obs",
            "discord": "discord",
            "spotify": "spotify",
            "steam": "steam",
            "gimp": "gimp",
            "blender": "blender",
        }

        for phrase, app in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
            if phrase in t:
                return SemanticAction(
                    action="open_app",
                    confidence=0.94,
                    app_name=app,
                    text=raw,
                    reason="smart_known_app",
                    source="smart_router",
                )

        return None

    def _music_action(self, raw: str, t: str) -> SemanticAction | None:
        play_words = [
            "reproduce",
            "reproducir",
            "reproduzca",
            "reproduciendo",
            "pon",
            "ponme",
            "toca",
            "escuchar",
            "quiero escuchar",
            "música",
            "musica",
        ]

        if not any(w in t for w in play_words):
            return None

        q = self._extract_music_query(raw)

        if not q:
            return None

        platform = self.memory.get_preference("plataforma musical", "youtube_music") or "youtube_music"

        if "youtube" in t:
            platform = "youtube"
        elif "tidal" in t:
            platform = "tidal"
        elif "spotify" in t:
            platform = "spotify"

        return SemanticAction(
            action="play_music",
            confidence=0.92,
            query=q,
            platform=platform,
            text=raw,
            reason="smart_music",
            source="smart_router",
        )

    def _extract_search_query(self, raw: str, platform: str) -> str:
        q = self._norm(raw)

        remove = [
            "busca en google",
            "buscar en google",
            "buscame en google",
            "búscame en google",
            "busca en internet",
            "buscar en internet",
            "busca en la web",
            "googlea",
            "busca",
            "buscar",
            "buscame",
            "búscame",
            "investiga",
            "en google",
            "en internet",
            "en la web",
            "en youtube",
            "en you tube",
            "en yutube",
            "youtube",
            "you tube",
            "yutube",
            "por favor",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")

        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _extract_folder_query(self, raw: str) -> str:
        q = self._norm(raw)

        replacements = {
            "punto hermes": "hermes",
            "dot hermes": "hermes",
            "carpita": "carpeta",
            "abrilacarpita": "carpeta",
            "abrilacarpeta": "carpeta",
        }

        for bad, good in replacements.items():
            q = q.replace(bad, good)

        remove = [
            "abre la carpeta de",
            "abre la carpeta del",
            "abre carpeta de",
            "abre carpeta del",
            "abro la carpeta de",
            "abro la carpeta del",
            "abrir la carpeta de",
            "abrir la carpeta del",
            "que abras la carpeta de",
            "que abras la carpeta del",
            "muestra la carpeta de",
            "muestra la carpeta del",
            "ensename la carpeta de",
            "ensename la carpeta del",
            "enséñame la carpeta de",
            "enséñame la carpeta del",
            "quiero ver la carpeta de",
            "quiero ver la carpeta del",
            "carpeta de",
            "carpeta del",
            "carpeta",
            "folder",
            "directorio",
            "abre",
            "abro",
            "abrir",
            "abras",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")

        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _extract_music_query(self, raw: str) -> str:
        q = self._norm(raw)

        remove = [
            "reproduce",
            "reproducir",
            "reproduzca",
            "reproduciendo",
            "ponme",
            "pon",
            "toca",
            "quiero escuchar",
            "escuchar",
            "musica",
            "música",
            "en youtube",
            "en youtube music",
            "en tidal",
            "en spotify",
            "youtube",
            "youtube music",
            "tidal",
            "spotify",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")

        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _looks_like_action(self, t: str, compact: str) -> bool:
        return (
            self._looks_like_open(t, compact)
            or any(x in t for x in ["busca", "buscar", "reproduce", "ponme", "pausa", "deten", "detén", "revisa"])
        )

    def _looks_like_open(self, t: str, compact: str) -> bool:
        return (
            "abre" in t
            or "abro" in t
            or "abrir" in t
            or "abras" in t
            or "abreme" in t
            or "muestra" in t
            or "ensename" in t
            or "quiero ver" in t
            or "que abras" in t
            or compact.startswith("abri")
            or compact.startswith("abro")
            or compact.startswith("abre")
        )

    def _norm(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\s:/._-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
