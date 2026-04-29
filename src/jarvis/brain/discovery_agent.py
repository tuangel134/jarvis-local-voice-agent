from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from jarvis.brain.action_schema import SemanticAction
from jarvis.brain.context_store import ContextStore
from jarvis.brain.folder_index import FolderIndex


class DiscoveryAgent:
    """
    Descubrimiento y resolución automática de acciones locales.

    Objetivo:
    - No depender de rutas hardcodeadas.
    - Resolver carpetas por índice local y escaneo ligero.
    - Preguntar solo cuando haya ambigüedad real.
    - Detectar comandos compuestos tipo:
      "abre servidor 1, busca media y abre el primero".
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.context = ContextStore(self.config)
        self.folder_index = FolderIndex(self.config)

    def semantic_direct(self, raw: str) -> SemanticAction | None:
        text = str(raw or "").strip()
        if not text:
            return None

        t = self._norm(text)
        compact = self._compact(t)

        # Quitar wake words que a veces Whisper mete dentro del comando.
        t = self._remove_wake_noise(t)
        compact = self._compact(t)

        # 1) Comando compuesto: buscar y abrir primer resultado.
        compound = self._compound_search_open(text, t)
        if compound:
            return compound

        # 2) Abrir resultado previo: "abre el primero".
        open_result = self._open_previous_result(text, t)
        if open_result:
            return open_result

        # 3) Abrir carpetas por autodescubrimiento.
        folder = self._open_folder_action(text, t, compact)
        if folder:
            return folder

        # 4) Buscar en la última carpeta: "busca ahí X".
        contextual_search = self._contextual_search(text, t)
        if contextual_search:
            return contextual_search

        return None

    def _compound_search_open(self, raw: str, t: str) -> SemanticAction | None:
        if not self._has_search_word(t):
            return None
        if not self._has_open_word(t):
            return None
        if not self._mentions_result_index(t):
            return None

        # Ejemplos:
        # "busca media y abre el primero"
        # "busca ahí media y abre el primer resultado"
        # "abre servidor 1 busca media y abre el primero" -> aquí solo resolvemos la parte de búsqueda si ya hay contexto.
        q = self._extract_query_between_search_and_open(t)
        if not q:
            q = self._extract_context_search_query(t)
        if not q:
            return None

        base = self.context.get_last_folder() or ""
        if not base:
            # Sin contexto, buscar desde HOME pero no fingir que abrimos una carpeta.
            base = str(Path.home())

        return SemanticAction(
            action="search_file",
            confidence=0.985,
            search_query=q,
            path=base,
            command="open_first_result",
            text=raw,
            reason="v3_compound_search_open",
            source="discovery_agent",
        )

    def _open_previous_result(self, raw: str, t: str) -> SemanticAction | None:
        idx = self._result_index(t)
        if idx is None:
            return None
        if not self._has_open_word(t):
            return None

        # Evitar que "servidor 1" sea leído como "primer resultado".
        if self._looks_like_server_folder(t):
            return None

        path = self.context.get_search_result(idx)
        if not path:
            return SemanticAction(
                action="chat",
                confidence=0.95,
                text=f"No tengo un resultado número {idx} guardado.",
                reason="context_result_missing",
                source="discovery_agent",
            )

        p = Path(path).expanduser()
        if p.is_dir():
            return SemanticAction(
                action="open_folder",
                confidence=0.99,
                path=str(p),
                folder=p.name,
                text=raw,
                reason=f"v3_open_result_{idx}",
                source="discovery_agent",
            )

        return SemanticAction(
            action="open_file",
            confidence=0.99,
            path=str(p),
            folder=p.name,
            text=raw,
            reason=f"v3_open_result_{idx}",
            source="discovery_agent",
        )

    def _open_folder_action(self, raw: str, t: str, compact: str) -> SemanticAction | None:
        if not (self._has_open_word(t) or "carpeta" in t or "carpita" in t or "folder" in t or "directorio" in t):
            return None

        # Evitar que búsquedas web/música caigan en carpetas.
        if any(x in t for x in ["youtube", "spotify", "tidal", "reproduce", "ponme", "busca en google", "googlea"]):
            return None

        q = self._extract_folder_query(t)
        if not q:
            return None

        resolved = self.resolve_folder(q)
        if not resolved:
            return None

        path, label, score, reason = resolved
        return SemanticAction(
            action="open_folder",
            confidence=min(0.999, max(0.88, score / 1000.0)),
            path=path,
            folder=label,
            text=raw,
            reason=f"v3_discovery_folder:{reason}",
            source="discovery_agent",
        )

    def _contextual_search(self, raw: str, t: str) -> SemanticAction | None:
        if not self._has_search_word(t):
            return None
        if not any(x in t for x in ["ahi", "ahí", "alli", "allí", "esa carpeta", "carpeta actual", "dentro"]):
            return None

        base = self.context.get_last_folder()
        if not base:
            return None

        q = self._extract_context_search_query(t)
        if not q:
            return None

        return SemanticAction(
            action="search_file",
            confidence=0.97,
            search_query=q,
            path=base,
            text=raw,
            reason="v3_contextual_search",
            source="discovery_agent",
        )

    def resolve_folder(self, query: str) -> tuple[str, str, int, str] | None:
        q = self._norm(query)
        if not q:
            return None

        variants = self._folder_query_variants(q)

        # 1) Buscar en índice local.
        best: tuple[str, str, int, str] | None = None
        for variant in variants:
            try:
                matches = self.folder_index.search(variant, limit=8, auto_index=True)
            except Exception:
                matches = []

            for m in matches:
                if self._bad_path(m.path):
                    continue
                score = int(m.score)
                # Bonos para coincidencias exactas compactas.
                if self._compact(Path(m.path).name) == self._compact(variant):
                    score += 500
                if self._compact(variant) in self._compact(Path(m.path).name):
                    score += 180
                candidate = (m.path, Path(m.path).name, score, f"index:{m.reason}")
                if best is None or candidate[2] > best[2]:
                    best = candidate

        if best and best[2] >= 70:
            return best

        # 2) Escaneo ligero de emergencia si el índice no lo encontró.
        scanned = self._scan_exact_folder(variants)
        if scanned:
            return scanned

        return best

    def _scan_exact_folder(self, variants: list[str]) -> tuple[str, str, int, str] | None:
        wanted = {self._compact(v) for v in variants if v}
        roots = self._scan_roots()
        skip = self._skip_names()
        best: tuple[str, str, int, str] | None = None
        max_dirs = 50000
        seen = 0

        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            stack = [root]
            while stack and seen < max_dirs:
                current = stack.pop()
                seen += 1
                try:
                    entries = list(current.iterdir())
                except Exception:
                    continue
                for child in entries:
                    try:
                        if not child.is_dir():
                            continue
                    except Exception:
                        continue
                    if child.name in skip or child.name.startswith("."):
                        continue
                    if self._bad_path(str(child)):
                        continue
                    cname = self._compact(child.name)
                    if cname in wanted:
                        score = 950 - min(len(child.parts), 50)
                        candidate = (str(child), child.name, score, "scan_exact")
                        if best is None or candidate[2] > best[2]:
                            best = candidate
                    stack.append(child)
        return best

    def _folder_query_variants(self, q: str) -> list[str]:
        q = self._norm(q)
        variants = [q]
        compact = self._compact(q)

        # Servidor 1 / servidor uno / serobidor 1 / server1.
        if re.search(r"\b(servidor|server|serobidor|sevidor|servidor)\s*(1|uno)\b", q) or compact in {"servidor1", "server1", "serobidor1"}:
            variants += ["servidor1", "servidor 1", "Servidor1", "server1", "server 1"]
        if re.search(r"\b(servidor|server|serobidor|sevidor|servidor)\s*(2|dos)\b", q) or compact in {"servidor2", "server2", "serobidor2"}:
            variants += ["servidor2", "servidor 2", "Servidor2", "server2", "server 2"]

        # Si el usuario dice "apps playstore", conservar también compacto.
        if " " in q:
            variants.append(compact)

        out: list[str] = []
        seen: set[str] = set()
        for v in variants:
            vv = self._norm(v)
            if vv and vv not in seen:
                seen.add(vv)
                out.append(vv)
        return out

    def _extract_folder_query(self, t: str) -> str:
        q = self._norm(t)
        replacements = {
            "acarpita": "carpeta",
            "carpita": "carpeta",
            "serobidor": "servidor",
            "sevidor": "servidor",
            "servidor uno": "servidor 1",
            "servidor dos": "servidor 2",
        }
        for a, b in replacements.items():
            q = q.replace(a, b)

        remove = [
            "abre la carpeta del", "abre la carpeta de", "abre carpeta del", "abre carpeta de",
            "abra la carpeta del", "abra la carpeta de", "abra carpeta del", "abra carpeta de",
            "abres la carpeta del", "abres la carpeta de", "abres carpeta del", "abres carpeta de",
            "abrir la carpeta del", "abrir la carpeta de", "que abras la carpeta del", "que abras la carpeta de",
            "muestra la carpeta del", "muestra la carpeta de", "carpeta del", "carpeta de",
            "directorio del", "directorio de", "folder del", "folder de",
            "abre", "abra", "abres", "abrir", "abras", "muestra", "ensename", "enséñame",
            "carpeta", "directorio", "folder",
        ]
        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(self._norm(phrase), " ")
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _extract_query_between_search_and_open(self, t: str) -> str:
        q = t
        q = self._remove_wake_noise(q)
        # Deja solo lo que está después de busca/buscar y antes de abre/abrir.
        m = re.search(r"(?:busca|buscar|buscame|búscame|encuentra)\s+(.*?)(?:\s+y\s+abre|\s+abre|\s+y\s+abrir|\s+abrir)", q)
        if m:
            q = m.group(1)
        else:
            return ""
        q = self._cleanup_search_query(q)
        return q

    def _extract_context_search_query(self, t: str) -> str:
        q = self._remove_wake_noise(t)
        q = re.sub(r".*?(busca|buscar|buscame|búscame|encuentra)\s+", "", q)
        q = re.sub(r"\s+(y\s+)?(abre|abrir|abres|abra)\s+.*$", "", q)
        q = self._cleanup_search_query(q)
        return q

    def _cleanup_search_query(self, q: str) -> str:
        q = self._norm(q)
        remove = [
            "ahi", "ahí", "alli", "allí", "en esa carpeta", "dentro de esa carpeta",
            "en la carpeta actual", "dentro", "archivo", "archivos", "carpeta", "carpetas",
            "resultado", "resultados", "primer", "primero", "segundo", "tercero",
            "el", "la", "los", "las", "de", "del", "en",
        ]
        for phrase in sorted(remove, key=len, reverse=True):
            q = re.sub(rf"\b{re.escape(self._norm(phrase))}\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _result_index(self, t: str) -> int | None:
        if self._looks_like_server_folder(t):
            return None
        words = set(t.split())
        mapping = {
            "primero": 1, "primer": 1, "uno": 1, "1": 1,
            "segundo": 2, "dos": 2, "2": 2,
            "tercero": 3, "tres": 3, "3": 3,
            "cuarto": 4, "cuatro": 4, "4": 4,
            "quinto": 5, "cinco": 5, "5": 5,
        }
        for k, v in mapping.items():
            if k in words:
                return v
        if "ese" in words or "esa" in words:
            return 1
        return None

    def _mentions_result_index(self, t: str) -> bool:
        return self._result_index(t) is not None or "primer resultado" in t or "primero" in t

    def _looks_like_server_folder(self, t: str) -> bool:
        compact = self._compact(t)
        return (
            "servidor 1" in t or "servidor 2" in t or "servidor uno" in t or "servidor dos" in t
            or "server 1" in t or "server 2" in t
            or "servidor1" in compact or "servidor2" in compact
            or "server1" in compact or "server2" in compact
            or "serobidor1" in compact or "serobidor2" in compact
        )

    def _has_open_word(self, t: str) -> bool:
        return any(w in t.split() for w in ["abre", "abra", "abres", "abrir", "abras", "abreme", "ábreme"]) or "abre" in t

    def _has_search_word(self, t: str) -> bool:
        return any(w in t for w in ["busca", "buscar", "buscame", "búscame", "encuentra"])

    def _remove_wake_noise(self, t: str) -> str:
        q = self._norm(t)
        for phrase in ["hey jarvis", "oye jarvis", "y jarvis", "jarvis"]:
            q = q.replace(phrase, " ")
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _bad_path(self, path: str) -> bool:
        p = str(path)
        bad = [
            "/.Trash-0/", "/Trash/", "/.git/", "/node_modules/", "/__pycache__/",
            "/.cache/", "/.local/share/jarvis/", "/site-packages/", "/dist-packages/",
            "/venv/", "/.venv/", "/env/", "/BackupsJarvis/", "/backup_manual_",
        ]
        return any(x in p for x in bad)

    def _skip_names(self) -> set[str]:
        return {
            ".git", "node_modules", "__pycache__", ".cache", ".local", ".config",
            "venv", ".venv", "env", ".Trash-0", "Trash", "site-packages", "dist-packages",
        }

    def _scan_roots(self) -> list[Path]:
        home = Path.home()
        roots = [
            home / "Escritorio", home / "Desktop", home / "Descargas", home / "Downloads",
            home / "Documentos", home / "Documents", home / "Proyectos", home / "Projects",
            Path("/mnt"), Path("/media"),
        ]
        out: list[Path] = []
        seen: set[str] = set()
        for r in roots:
            try:
                rr = r.expanduser().resolve()
            except Exception:
                continue
            if str(rr) not in seen and rr.exists() and rr.is_dir():
                seen.add(str(rr))
                out.append(rr)
        return out

    def _norm(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\s:/._-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _compact(self, text: str) -> str:
        return re.sub(r"[^a-z0-9ñ]+", "", self._norm(text))
