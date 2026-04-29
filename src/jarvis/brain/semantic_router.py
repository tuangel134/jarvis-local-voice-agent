from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

import requests

from jarvis.brain.action_schema import SemanticAction
from jarvis.brain.memory_store import MemoryStore
from jarvis.brain.context_store import ContextStore
from jarvis.brain.folder_index import FolderIndex


class SemanticRouter:
    """
    Jarvis v2 Semantic Brain.

    Capas:
    1. Reglas de emergencia para errores comunes de STT.
    2. Comandos de memoria: recuerda/olvida/qué recuerdas.
    3. Memoria local: carpetas, URLs, servicios y preferencias.
    4. Reglas directas rápidas.
    5. Groq JSON parser.
    6. Fallback a chat.
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}
        self.env = self._load_env()
        self.memory = MemoryStore(self.config)
        self.folder_index = FolderIndex(self.config)

    def parse(self, text: str) -> SemanticAction:
        raw = (text or "").strip()

        if not raw:
            return SemanticAction(
                action="unknown",
                confidence=0.0,
                text=raw,
                source="empty",
            )

        # Prioridad máxima: comandos cortos que dependen del contexto.
        # Ejemplos: "abre el primero", "abre el segundo", "muéstrame los resultados".
        context_shortcut = self._context_result_shortcut(raw)
        if context_shortcut:
            return context_shortcut

        # Prioridad máxima: carpetas Servidor1/Servidor2.
        server_folder = self._server_folder_action(raw)
        if server_folder:
            return server_folder

        # Prioridad máxima: malas transcripciones de carpetas.
        emergency_folder = self._emergency_folder_action(raw)
        if emergency_folder:
            return emergency_folder

        # Comandos de memoria.
        memory_cmd = self._memory_command(raw)
        if memory_cmd:
            return memory_cmd

        # Carpetas conocidas primero.
        direct_folder = self._direct_known_folder_action(raw)
        if direct_folder:
            return direct_folder

        # Índice dinámico de carpetas.
        indexed_folder = self._folder_index_action(raw)
        if indexed_folder:
            return indexed_folder

        # Acciones resueltas desde memoria.
        memory_action = self._memory_lookup_action(raw)
        if memory_action:
            return memory_action

        # Reglas directas.
        direct = self._direct_parse(raw)
        if direct:
            return direct

        # Parser semántico con Groq.
        groq = self._groq_parse(raw)
        if groq and groq.normalized_action() != "unknown" and groq.confidence >= 0.45:
            return groq

        return SemanticAction(
            action="chat",
            confidence=0.60,
            text=raw,
            source="fallback_chat",
        )

    def _direct_known_folder_action(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)
        compact = t.replace(" ", "")

        open_like = (
            "abre" in t
            or "abrir" in t
            or "abras" in t
            or "abreme" in t
            or "muestra" in t
            or "ensename" in t
            or "enséñame" in raw.lower()
            or "quiero ver" in t
            or "que abras" in t
            or compact.startswith("abri")
            or "abrilacarpeta" in compact
            or "abrilacarpita" in compact
            or "abrelacarpeta" in compact
            or "abrelacarpita" in compact
        )

        if not open_like:
            return None

        known = {
            "descargas": str(Path.home() / "Descargas"),
            "downloads": str(Path.home() / "Descargas"),
            "documentos": str(Path.home() / "Documentos"),
            "documents": str(Path.home() / "Documentos"),
            "escritorio": str(Path.home() / "Escritorio"),
            "desktop": str(Path.home() / "Escritorio"),
            "videos": str(Path.home() / "Videos"),
            "imagenes": str(Path.home() / "Imágenes"),
            "imágenes": str(Path.home() / "Imágenes"),
            "musica": str(Path.home() / "Música"),
            "música": str(Path.home() / "Música"),
            "home": str(Path.home()),
            "inicio": str(Path.home()),
        }

        for key, path in known.items():
            if key in t or key in compact:
                return SemanticAction(
                    action="open_folder",
                    confidence=0.99,
                    path=path,
                    folder=key,
                    text=raw,
                    reason="direct_known_folder",
                    source="direct",
                )

        # Builds y malas transcripciones van a memoria o ruta por defecto.
        build_terms = ["build", "builds", "buil", "buils", "bild", "bilds", "buyos", "buidos"]

        if any(term in t for term in build_terms) or any(term in compact for term in build_terms):
            remembered = (
                self.memory.resolve_folder("carpeta de builds")
                or self.memory.resolve_folder("builds")
                or self.memory.resolve_folder("carpeta de buyos")
            )

            path = remembered or str(Path.home() / "Descargas/Apps playstore")

            return SemanticAction(
                action="open_folder",
                confidence=0.99,
                path=path,
                folder="builds",
                text=raw,
                reason="direct_known_folder_builds",
                source="direct",
            )

        return None


    def _folder_index_action(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)
        compact = t.replace(" ", "")

        open_like = (
            "abre" in t
            or "abrir" in t
            or "abras" in t
            or "abreme" in t
            or "muestra" in t
            or "ensename" in t
            or "enséñame" in raw.lower()
            or "quiero ver" in t
            or "que abras" in t
            or compact.startswith("abri")
            or "carpeta" in t
            or "carpita" in t
        )

        if not open_like:
            return None

        # No usar índice para URLs o música.
        if any(x in t for x in ["youtube", "spotify", "tidal", "play console", "google", "github", "reproduce", "ponme"]):
            return None

        match = self.folder_index.best(raw)

        if not match:
            return None

        return SemanticAction(
            action="open_folder",
            confidence=0.94,
            path=match.path,
            folder=match.name,
            text=raw,
            reason=f"folder_index:{match.reason}",
            source="folder_index",
        )


    def _context_result_shortcut(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)
        compact = t.replace(" ", "")
        ctx = ContextStore(self.config)

        # Mostrar resultados guardados.
        if (
            "muestrame los resultados" in t
            or "muéstrame los resultados" in raw.lower()
            or "dime los resultados" in t
            or "lista resultados" in t
            or "ver resultados" in t
            or "que encontraste" in t
            or "qué encontraste" in raw.lower()
        ):
            return SemanticAction(
                action="chat",
                confidence=0.99,
                text=ctx.describe_results(limit=10),
                reason="context_show_results_direct",
                source="context_direct",
            )

        mapping = {
            "primero": 1, "primer": 1, "uno": 1, "1": 1,
            "segundo": 2, "dos": 2, "2": 2,
            "tercero": 3, "tres": 3, "3": 3,
            "cuarto": 4, "cuatro": 4, "4": 4,
            "quinto": 5, "cinco": 5, "5": 5,
            "sexto": 6, "seis": 6, "6": 6,
            "septimo": 7, "séptimo": 7, "siete": 7, "7": 7,
            "octavo": 8, "ocho": 8, "8": 8,
            "noveno": 9, "nueve": 9, "9": 9,
            "decimo": 10, "décimo": 10, "diez": 10, "10": 10,
        }

        idx = None
        words = set(t.split())
        for word, value in mapping.items():
            if word in words or word in compact:
                idx = value
                break

        if idx is None and ("ese" in words or "esa" in words):
            idx = 1

        wants_open = (
            "abre" in t
            or "abro" in t
            or "abrir" in t
            or "muestra" in t
            or "ensename" in t
            or "enséñame" in raw.lower()
        )

        if idx is not None and wants_open:
            result_path = ctx.get_search_result(idx)

            if not result_path:
                return SemanticAction(
                    action="chat",
                    confidence=0.98,
                    text=f"No tengo un resultado número {idx} guardado.",
                    reason="context_result_missing_direct",
                    source="context_direct",
                )

            path = Path(result_path).expanduser()

            if path.is_dir():
                return SemanticAction(
                    action="open_folder",
                    confidence=0.99,
                    path=str(path),
                    folder=path.name,
                    text=raw,
                    reason=f"context_open_result_{idx}_direct",
                    source="context_direct",
                )

            return SemanticAction(
                action="open_file",
                confidence=0.99,
                path=str(path),
                folder=path.name,
                text=raw,
                reason=f"context_open_result_{idx}_direct",
                source="context_direct",
            )

        # Búsqueda contextual: "busca ahí media".
        last_folder = ctx.get_last_folder()
        refers_here = (
            "ahi" in t
            or "ahí" in raw.lower()
            or "alli" in t
            or "allí" in raw.lower()
            or "esa carpeta" in t
            or "en esa carpeta" in t
            or "dentro" in t
        )
        wants_search = (
            "busca" in t
            or "buscar" in t
            or "encuentra" in t
            or "buscame" in t
            or "búscame" in raw.lower()
        )
        if wants_search and refers_here and last_folder:
            q = t
            for phrase in ["busca ahi", "busca ahí", "buscar ahi", "buscar ahí", "buscame ahi", "búscame ahí", "encuentra ahi", "encuentra ahí", "archivos", "archivo", "carpetas", "carpeta", "ahi", "ahí", "alli", "allí", "en", "de", "dentro"]:
                q = q.replace(self._norm(phrase), " ")
            q = re.sub(r"[^a-z0-9ñ._-]+", " ", q).strip(" .,:;¡!¿?")
            if not q:
                q = "."
            return SemanticAction(
                action="search_file",
                confidence=0.98,
                search_query=q,
                path=last_folder,
                text=raw,
                reason="context_search_direct",
                source="context_direct",
            )

        return None


    def _server_folder_action(self, raw: str) -> SemanticAction | None:
        """
        Regla de máxima prioridad:
        - "abre la carpeta del servidor 1"
        - "abro la carpeta del servidor 1"
        - "abre servidor 1"
        - "abre la carpeta de servidor2"

        No debe confundirse con "revisa servidor de películas" = Jellyfin.
        """
        t = self._norm(raw)
        compact = t.replace(" ", "")

        wants_open_folder = (
            "abre" in t
            or "abro" in t
            or "abrir" in t
            or "abras" in t
            or "carpeta" in t
            or "folder" in t
            or "directorio" in t
            or compact.startswith("abro")
            or compact.startswith("abre")
            or compact.startswith("abri")
        )

        if not wants_open_folder:
            return None

        # Servidor 1.
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
                reason="server_folder_priority",
                source="direct_server_folder",
            )

        # Servidor 2.
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
                reason="server_folder_priority",
                source="direct_server_folder",
            )

        return None


    def _emergency_folder_action(self, raw: str) -> SemanticAction | None:
        """
        Arregla frases que faster-whisper suele transcribir raro:

        - "abre la carpeta de descargas" -> "abrilacarpita de descargas"
        - "que abras la carpeta de descargas"
        - "abre la carpeta de builds" -> "abre la carpeta de buyos"
        """

        t = self._norm(raw)
        compact = t.replace(" ", "")
        # Si la frase es una búsqueda web/música, NO interpretar "build" como carpeta.
        if any(x in t for x in [
            "busca",
            "buscar",
            "buscame",
            "google",
            "googlea",
            "internet",
            "web",
            "youtube",
            "reproduce",
            "reproducir",
            "ponme",
            "tutorial",
        ]):
            return None


        open_like = (
            "abre" in t
            or "abrir" in t
            or "abras" in t
            or "abreme" in t
            or "ábreme" in raw.lower()
            or "muestra" in t
            or "ensename" in t
            or "enséñame" in raw.lower()
            or "quiero ver" in t
            or "que abras" in t
            or compact.startswith("abri")
            or "abrelacarpeta" in compact
            or "abrelacarpita" in compact
            or "abrilacarpeta" in compact
            or "abrilacarpita" in compact
            or "queabraslacarpeta" in compact
            or "queabraslacarpita" in compact
        )

        folder_like = (
            "carpeta" in t
            or "carpita" in t
            or "folder" in t
            or "directorio" in t
            or "descargas" in t
            or "downloads" in t
            or "build" in t
            or "builds" in t
            or "buyos" in t
            or "buil" in t
            or "bild" in t
            or "buidos" in t
        )

        if not (open_like or folder_like):
            return None

        # Descargas.
        if (
            "descargas" in t
            or "downloads" in t
            or "dedescargas" in compact
            or "carpitadedescargas" in compact
            or "carpetadedescargas" in compact
        ):
            return SemanticAction(
                action="open_folder",
                confidence=0.99,
                path=str(Path.home() / "Descargas"),
                folder="descargas",
                text=raw,
                reason="emergency_folder_descargas",
                source="direct_emergency",
            )

        # Builds / buyos.
        build_terms = [
            "build",
            "builds",
            "buil",
            "buils",
            "bild",
            "bilds",
            "buyos",
            "buidos",
            "bil",
            "bils",
            "billos",
        ]

        if any(term in t for term in build_terms) or any(term in compact for term in build_terms):
            remembered = (
                self.memory.resolve_folder("carpeta de builds")
                or self.memory.resolve_folder("builds")
                or self.memory.resolve_folder("carpeta builds")
                or self.memory.resolve_folder("carpeta de buyos")
                or self.memory.resolve_folder("buyos")
            )

            path = remembered or str(Path.home() / "Descargas/Apps playstore")

            return SemanticAction(
                action="open_folder",
                confidence=0.99,
                path=path,
                folder="builds",
                text=raw,
                reason="emergency_folder_builds",
                source="direct_emergency",
            )

        return None

    def _memory_command(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)

        if t.startswith("recuerda que "):
            try:
                item = self.memory.remember_from_text(raw)

                if item:
                    return SemanticAction(
                        action="chat",
                        confidence=1.0,
                        text=f"Memoria guardada: {item.key} = {item.value}",
                        reason="memory_saved",
                        source="memory",
                    )

                return SemanticAction(
                    action="chat",
                    confidence=1.0,
                    text="No pude convertir eso en una memoria clara.",
                    reason="memory_not_saved",
                    source="memory",
                )

            except Exception as exc:
                return SemanticAction(
                    action="chat",
                    confidence=1.0,
                    text=f"No pude guardar esa memoria: {exc}",
                    reason="memory_error",
                    source="memory",
                )

        if t.startswith("olvida "):
            query = raw.strip()[len("olvida "):].strip()
            deleted = self.memory.forget(query)

            if deleted:
                msg = f"Listo, olvidé {deleted} recuerdo relacionado con {query}."
            else:
                msg = f"No encontré recuerdos relacionados con {query}."

            return SemanticAction(
                action="chat",
                confidence=1.0,
                text=msg,
                reason="memory_forget",
                source="memory",
            )

        if (
            "que recuerdas" in t
            or "qué recuerdas" in raw.lower()
            or "mis recuerdos" in t
            or "lista memorias" in t
            or "lista recuerdos" in t
        ):
            items = self.memory.list()

            if not items:
                msg = "Todavía no tengo recuerdos guardados."
            else:
                compact = ", ".join(f"{i.key}: {i.value}" for i in items[:8])
                msg = f"Recuerdo esto: {compact}"

            return SemanticAction(
                action="chat",
                confidence=1.0,
                text=msg,
                reason="memory_list",
                source="memory",
            )

        return None

    def _memory_lookup_action(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)

        if self._looks_like_open(t):
            folder = self.memory.resolve_folder(raw)

            if folder:
                return SemanticAction(
                    action="open_folder",
                    confidence=0.97,
                    path=folder,
                    text=raw,
                    reason="memory_folder",
                    source="memory",
                )

            url = self.memory.resolve_url(raw)

            if url:
                return SemanticAction(
                    action="open_url",
                    confidence=0.97,
                    url=url,
                    text=raw,
                    reason="memory_url",
                    source="memory",
                )

        # Si pidió abrir carpeta/directorio del servidor, NO debe caer en services.
        if (
            ("carpeta" in t or "folder" in t or "directorio" in t or "abre" in t or "abro" in t or "abrir" in t or "abras" in t)
            and ("servidor" in t or "server" in t)
        ):
            return None

        if (
            "revisa" in t
            or "estado" in t
            or "servicio" in t
            or "servidor" in t
            or "esta activo" in t
            or "está activo" in raw.lower()
        ):
            service = self.memory.resolve_service(raw)

            if service:
                return SemanticAction(
                    action="service_status",
                    confidence=0.97,
                    service=service,
                    text=raw,
                    reason="memory_service",
                    source="memory",
                )

        return None

    def _direct_parse(self, raw: str) -> SemanticAction | None:
        t = self._norm(raw)

        # Google Play Console antes de Google genérico.
        if (
            "subo mis apps" in t
            or "subir mis apps" in t
            or "subo apps" in t
            or "subir apps" in t
            or "apps a google" in t
            or "panel de apps" in t
            or "play console" in t
            or "google play console" in t
            or "consola de google play" in t
            or "consola play" in t
        ):
            return SemanticAction(
                action="open_url",
                confidence=0.98,
                url_name="google play console",
                text=raw,
                source="direct",
            )

        if self._has_any(t, [
            "deten la musica",
            "detén la música",
            "para la musica",
            "para la música",
            "apaga la musica",
            "apaga la música",
            "stop music",
        ]):
            return SemanticAction(action="stop_music", confidence=0.98, text=raw, source="direct")

        if self._has_any(t, [
            "pausa la musica",
            "pausa la música",
            "pausar musica",
            "pausar música",
            "pause music",
        ]):
            return SemanticAction(action="pause_music", confidence=0.98, text=raw, source="direct")

        if self._has_any(t, [
            "continua la musica",
            "continúa la música",
            "reanuda la musica",
            "reanuda la música",
            "sigue la musica",
            "sigue la música",
            "resume music",
        ]):
            return SemanticAction(action="resume_music", confidence=0.98, text=raw, source="direct")

        if self._has_any(t, ["que hora es", "dime la hora", "hora actual"]):
            return SemanticAction(action="get_time", confidence=0.98, text=raw, source="direct")

        if self._has_any(t, ["que fecha es", "fecha de hoy", "dia es hoy"]):
            return SemanticAction(action="get_date", confidence=0.98, text=raw, source="direct")

        if self._has_any(t, ["estado del sistema", "como esta la pc", "memoria", "cpu", "disco"]):
            return SemanticAction(action="system_status", confidence=0.95, text=raw, source="direct")

        if self._has_any(t, ["revisa jellyfin", "servidor de peliculas", "servidor de películas"]):
            return SemanticAction(action="service_status", confidence=0.95, service="jellyfin", text=raw, source="direct")

        if self._has_any(t, ["revisa immich", "servidor de fotos", "mis fotos"]):
            return SemanticAction(action="service_status", confidence=0.95, service="immich", text=raw, source="direct")

        if self._has_any(t, ["revisa docker", "docker esta", "docker está"]):
            return SemanticAction(action="service_status", confidence=0.95, service="docker", text=raw, source="direct")

        music = self._direct_music(raw, t)
        if music:
            return music

        if self._looks_like_open(t):
            folder = self._detect_folder(t)

            if folder:
                return SemanticAction(
                    action="open_folder",
                    confidence=0.93,
                    folder=folder,
                    text=raw,
                    source="direct",
                )

            url_name = self._detect_url_name(t)

            if url_name:
                return SemanticAction(
                    action="open_url",
                    confidence=0.93,
                    url_name=url_name,
                    text=raw,
                    source="direct",
                )

            app_name = self._detect_app_name(t)

            if app_name:
                return SemanticAction(
                    action="open_app",
                    confidence=0.92,
                    app_name=app_name,
                    text=raw,
                    source="direct",
                )

        if self._has_any(t, ["crea una nota", "crear una nota", "guarda una nota", "nota que diga"]):
            note = re.sub(r".*?(crea una nota|crear una nota|guarda una nota|nota que diga)\s*(que diga)?", "", raw, flags=re.I).strip(" :")
            return SemanticAction(action="create_note", confidence=0.92, note=note or raw, text=raw, source="direct")

        if self._has_any(t, ["busca el archivo", "buscar archivo", "encuentra el archivo"]):
            q = re.sub(r".*?(busca|buscar|encuentra)\s+(el\s+)?archivo\s+", "", raw, flags=re.I).strip()
            return SemanticAction(action="search_file", confidence=0.90, search_query=q or raw, text=raw, source="direct")

        if self._has_any(t, ["usa la ia avanzada", "modelo potente", "analiza este error", "revisa este log"]):
            return SemanticAction(action="heavy_reasoning", confidence=0.90, text=raw, source="direct")

        return None

    def _direct_music(self, raw: str, t: str) -> SemanticAction | None:
        play = self._has_any(t, [
            "reproduce",
            "reproducir",
            "reproduzca",
            "reproduciendo",
            "reproduccion",
            "reproducción",
            "pon",
            "ponme",
            "toca",
            "escuchar",
            "quiero escuchar",
        ])

        if not play:
            return None

        platform = self.memory.get_preference("plataforma musical", "youtube_music") or "youtube_music"

        if self._has_any(t, ["youtube music", "musica de youtube", "música de youtube"]):
            platform = "youtube_music"
        elif self._has_any(t, ["youtube", "you tube", "yutube", "jutube"]):
            platform = "youtube"
        elif "tidal" in t:
            platform = "tidal"
        elif "spotify" in t:
            platform = "spotify"

        query = self._extract_music_query(raw)

        if not query:
            return None

        return SemanticAction(
            action="play_music",
            confidence=0.96,
            query=query,
            platform=platform,
            text=raw,
            source="direct",
        )

    def _groq_parse(self, raw: str) -> SemanticAction | None:
        api_key = self.env.get("GROQ_API_KEY") or os.environ.get("GROQ_API_KEY")

        if not api_key:
            return None

        brain_cfg = self.config.get("brain", {})
        llm_cfg = self.config.get("llm", {})
        model = brain_cfg.get("parser_model") or llm_cfg.get("groq_fast_model") or "llama-3.1-8b-instant"

        security = self.config.get("security", {})
        memories = [m.to_dict() for m in self.memory.list()[:20]]

        system = """
Eres el Semantic Action Router de Jarvis en Linux.

Tu única tarea es convertir la frase del usuario a JSON válido.
NO respondas al usuario.
NO uses markdown.
NO expliques.
NO ejecutes comandos.
NO inventes acciones fuera del schema.

Acciones:
open_app, open_url, open_folder, play_music, stop_music, pause_music, resume_music,
get_time, get_date, system_status, service_status, create_note, read_note,
search_file, create_reminder, list_reminders, safe_shell, chat, heavy_reasoning, unknown.

Reglas:
- Si quiere reproducir/poner/tocar/escuchar música: play_music.
- Si no menciona plataforma musical, usa la preferencia de memoria si existe; si no, youtube_music.
- Si dice servidor de películas: service_status jellyfin.
- Si dice servidor de fotos: service_status immich.
- Si dice donde subo mis apps a Google, panel de apps, play console o Google Play: open_url google play console.
- Si pide abrir app para calcular: open_app calculadora.
- Si pide abrir carpeta de descargas/documentos/escritorio: open_folder.
- Si coincide con un recuerdo de memoria, úsalo.
- Si es pregunta normal: chat.
- Si pide analizar error largo, programar, depurar proyecto o tarea pesada: heavy_reasoning.
- Para shell, solo usa safe_shell si el usuario pidió explícitamente ejecutar un comando.

JSON exacto:
{
  "action": "play_music",
  "confidence": 0.0,
  "query": "",
  "platform": "",
  "app_name": "",
  "url_name": "",
  "url": "",
  "folder": "",
  "path": "",
  "service": "",
  "note": "",
  "search_query": "",
  "command": "",
  "text": "",
  "needs_confirmation": false,
  "reason": ""
}
"""

        payload = {
            "text": raw,
            "memories": memories,
            "allowed_apps": security.get("allowed_apps", [])[:100],
            "app_aliases": security.get("app_aliases", {}),
            "url_aliases": security.get("url_aliases", {}),
            "service_aliases": security.get("service_aliases", {}),
        }

        try:
            res = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=8,
            )

            if res.status_code >= 400:
                return None

            content = res.json()["choices"][0]["message"]["content"]
            action = SemanticAction.from_json(content, source=f"groq:{model}")

            if not action.text:
                action.text = raw

            return action

        except Exception:
            return None

    def _extract_music_query(self, raw: str) -> str:
        q = self._norm(raw)

        corrections = {
            "kevin carl": "kevin kaarl",
            "kevin card": "kevin kaarl",
            "kevin karl": "kevin kaarl",
            "kevin kaal": "kevin kaarl",
            "quebin": "kevin",
            "javi carles y sal lucas": "kevin kaarl san lucas",
            "javi carles sal lucas": "kevin kaarl san lucas",
            "javi carlos y sal lucas": "kevin kaarl san lucas",
            "javi carlos sal lucas": "kevin kaarl san lucas",
            "javi carles": "kevin kaarl",
            "javi carlos": "kevin kaarl",
            "sal lucas": "san lucas",
        }

        for bad, good in corrections.items():
            q = q.replace(bad, good)

        remove = [
            "abre youtube y reproduce",
            "abri youtube y reproduzca",
            "abrir youtube y reproduce",
            "abre youtube y pon",
            "abre youtube music y reproduce",
            "abre tidal y reproduce",
            "abre spotify y reproduce",
            "reproduciendo",
            "reproduccion",
            "reproducción",
            "reproduce",
            "reproducir",
            "reproduzca",
            "reprodusca",
            "ponme",
            "pon",
            "toca",
            "escuchar",
            "quiero escuchar",
            "en youtube music",
            "en youtube",
            "en you tube",
            "en yutube",
            "en jutube",
            "en tidal",
            "en spotify",
            "youtube music",
            "youtube",
            "you tube",
            "yutube",
            "jutube",
            "tidal",
            "spotify",
            "por favor",
            "favor",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")

        q = re.sub(r"\b(y|e|el|la|los|las|un|una|de|del|en|con)\b", " ", q)
        q = re.sub(r"\b(reproduciendo|reproduccion|reproducción|reproduce|reproducir|reproduzca|pon|ponme)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()

        return q

    def _detect_folder(self, t: str) -> str:
        mapping = {
            "descargas": "descargas",
            "downloads": "descargas",
            "documentos": "documentos",
            "escritorio": "escritorio",
            "videos": "videos",
            "imagenes": "imagenes",
            "imágenes": "imagenes",
            "musica": "musica",
            "música": "musica",
            "carpeta personal": "home",
            "inicio": "home",
            "home": "home",
            "build": "builds",
            "builds": "builds",
            "buyos": "builds",
            "buil": "builds",
            "bild": "builds",
            "buidos": "builds",
        }

        for k, v in mapping.items():
            if k in t:
                return v

        return ""

    def _detect_url_name(self, t: str) -> str:
        names = [
            "google play console",
            "play console",
            "youtube music",
            "youtube",
            "firebase",
            "revenuecat",
            "expo",
            "github",
            "hugging face",
            "huggingface",
            "chatgpt",
            "claude",
            "gemini",
            "perplexity",
            "groq",
            "openrouter",
            "gmail",
            "drive",
            "calendar",
            "whatsapp",
            "telegram",
            "tidal",
            "spotify",
            "google",
        ]

        for name in names:
            if name in t:
                return name

        return ""

    def _detect_app_name(self, t: str) -> str:
        names = [
            "calculadora",
            "calculator",
            "terminal",
            "consola",
            "archivos",
            "explorador",
            "vscode",
            "visual studio code",
            "cursor",
            "vlc",
            "monitor del sistema",
            "obs",
            "discord",
            "telegram",
            "spotify",
            "steam",
            "gimp",
            "blender",
            "libreoffice",
        ]

        for name in names:
            if name in t:
                return name

        return ""

    def _looks_like_open(self, t: str) -> bool:
        return self._has_any(t, [
            "abre",
            "abro",
            "abrir",
            "abras",
            "abreme",
            "inicia",
            "lanza",
            "ejecuta",
            "muestra",
            "ensename",
            "enséñame",
            "quiero ver",
            "que abras",
        ])

    def _load_env(self) -> dict[str, str]:
        path = Path.home() / ".config/jarvis/.env"
        data: dict[str, str] = {}

        if not path.exists():
            return data

        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")

        return data

    def _norm(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\s:/._-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _has_any(self, text: str, patterns: list[str]) -> bool:
        return any(self._norm(p) in text for p in patterns)

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
    if "SemanticRouter" in globals() and not getattr(SemanticRouter, "_jv3414_wrapped", False):
        for _name, _value in list(SemanticRouter.__dict__.items()):
            if _name.startswith("__") or not callable(_value) or getattr(_value, "_jv3414_wrapped", False):
                continue

            def _jv3414_make_wrapper(orig):
                def _wrapped(self, *args, **kwargs):
                    return _jv3414_clean_any(orig(self, *args, **kwargs))
                _wrapped._jv3414_wrapped = True
                return _wrapped

            try:
                setattr(SemanticRouter, _name, _jv3414_make_wrapper(_value))
            except Exception:
                pass

        SemanticRouter._jv3414_wrapped = True
except Exception:
    pass

