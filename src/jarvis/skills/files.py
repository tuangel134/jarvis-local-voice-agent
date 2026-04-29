from __future__ import annotations

import subprocess
import re
from pathlib import Path
from typing import Any

from jarvis.brain.intent_model import Intent
from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.context_store import ContextStore
from jarvis.skills.base import Skill


class FilesSkill(Skill):
    name = "files"
    description = "Abre carpetas, abre archivos, busca archivos y abre resultados guardados."

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {"open_folder", "open_file", "search_file", "open_result"}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == "open_folder":
            return self._open_folder(entities)
        if intent.name == "open_file":
            return self._open_file(entities)
        if intent.name == "search_file":
            return self._search_file(entities)
        if intent.name == "open_result":
            return self._open_result(entities)
        return {"ok": False, "error": "Intención de archivos no soportada."}

    # Métodos públicos útiles para futuro ToolExecutor.
    def open_folder(self, path: str) -> bool:
        return bool(self._open_folder({"path": path}).get("ok"))

    def open_file(self, path: str) -> bool:
        return bool(self._open_file({"path": path}).get("ok"))

    def search_files(self, query: str, base: str | None = None) -> list[dict[str, str]]:
        result = self._search_file({"query": query, "path": base or ""})
        matches = result.get("matches", []) or []
        out: list[dict[str, str]] = []
        for m in matches:
            p = Path(str(m)).expanduser()
            out.append({"name": p.name, "path": str(p), "kind": "folder" if p.is_dir() else "file"})
        return out

    def resolve_folder(self, query: str) -> str:
        q = str(query or "").strip().lower()
        compact = q.replace(" ", "")

        if "servidor1" in compact or "servidoruno" in compact or "servidor 1" in q:
            return "/home/angel/Escritorio/Servidor1"
        if "servidor2" in compact or "servidordos" in compact or "servidor 2" in q:
            return "/home/angel/Escritorio/Servidor2"

        p = Path(str(query or "")).expanduser()
        if p.exists() and p.is_dir():
            return str(p)

        # Memoria e índice, si existen.
        try:
            from jarvis.brain.memory_store import MemoryStore
            mem = MemoryStore(self.config)
            found = mem.resolve_folder(query)
            if found:
                return str(found)
        except Exception:
            pass

        try:
            from jarvis.brain.folder_index import FolderIndex
            idx = FolderIndex(self.config)
            match = idx.best(query, min_score=40)
            if match:
                return str(match.path)
        except Exception:
            pass

        return ""

    def scan_folders(self) -> int:
        try:
            from jarvis.brain.folder_index import FolderIndex
            idx = FolderIndex(self.config)
            return int(idx.index_default_roots(rebuild=True))
        except Exception:
            return 0

    def _open_folder(self, entities: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(entities.get("path", "") or entities.get("base_path", "") or "").strip()
        target = str(entities.get("target", "") or "").strip()

        if not raw_path:
            return {"ok": False, "error": "No detecté qué carpeta abrir."}

        path = Path(raw_path).expanduser()

        if not path.exists():
            return {"ok": False, "error": f"No existe la carpeta: {path}"}
        if not path.is_dir():
            return {"ok": False, "error": f"No es una carpeta: {path}"}

        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ContextStore(self.config).set_last_folder(str(path), target or path.name)
            return {"ok": True, "message": f"Abriendo {target or path.name}.", "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": f"No pude abrir la carpeta: {exc}"}

    def _open_file(self, entities: dict[str, Any]) -> dict[str, Any]:
        raw_path = str(entities.get("path", "") or "").strip()
        target = str(entities.get("target", "") or "").strip()

        if not raw_path:
            return {"ok": False, "error": "No detecté qué archivo abrir."}

        path = Path(raw_path).expanduser()

        if not path.exists():
            return {"ok": False, "error": f"No existe: {path}"}
        if path.is_dir():
            return self._open_folder({"path": str(path), "target": target or path.name})

        try:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ContextStore(self.config).set_last_file(str(path), target or path.name)
            return {"ok": True, "message": f"Abriendo {target or path.name}.", "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": f"No pude abrir el archivo: {exc}"}

    def _open_result(self, entities: dict[str, Any]) -> dict[str, Any]:
        try:
            index = int(entities.get("index", 1) or 1)
        except Exception:
            index = 1
        if index < 1:
            index = 1

        ctx = ContextStore(self.config)
        path = ctx.get_search_result(index)
        if not path:
            return {"ok": False, "error": f"No tengo resultado número {index}."}

        p = Path(path).expanduser()
        if p.is_dir():
            return self._open_folder({"path": str(p), "target": p.name})
        return self._open_file({"path": str(p), "target": p.name})

    def _search_file(self, entities: dict[str, Any]) -> dict[str, Any]:
        query = self._clean_query(str(entities.get("query", "") or ""))
        base_path = str(entities.get("path", "") or entities.get("base", "") or entities.get("base_path", "") or "").strip()
        open_base = bool(entities.get("open_base"))
        open_first = bool(entities.get("open_first"))

        try:
            open_index = int(entities.get("open_index", 1) or 1)
        except Exception:
            open_index = 1
        if open_index < 1:
            open_index = 1

        if not query:
            return {"ok": False, "error": "No detecté qué archivo buscar."}

        ctx = ContextStore(self.config)
        if base_path:
            base = Path(base_path).expanduser()
        else:
            last = ctx.get_last_folder()
            base = Path(last).expanduser() if last else Path.home()

        if not base.exists() or not base.is_dir():
            base = Path.home()

        opened_base_msg = ""
        if open_base:
            opened = self._open_folder({"path": str(base), "target": base.name})
            if opened.get("ok"):
                opened_base_msg = f"Abrí {base.name}. "

        matches: list[Path] = []
        q = query.lower().strip()

        try:
            for p in base.rglob("*"):
                if len(matches) >= 300:
                    break
                try:
                    if self._skip_path(p):
                        continue
                    if q in p.name.lower():
                        matches.append(p)
                except Exception:
                    continue
        except Exception as exc:
            return {"ok": False, "error": f"No pude buscar archivos: {exc}"}

        if not matches:
            ctx.set_search_results(query=query, base_path=str(base), results=[])
            return {
                "ok": True,
                "message": opened_base_msg + f"No encontré resultados para {query} en {base.name}.",
                "matches": [],
                "base_path": str(base),
            }

        sorted_matches = self._rank_matches(matches, q)
        ctx.set_search_results(query=query, base_path=str(base), results=[str(p) for p in sorted_matches])

        if open_first:
            selected = sorted_matches[open_index - 1] if open_index <= len(sorted_matches) else None
            if not selected:
                return {
                    "ok": False,
                    "error": f"Encontré {len(sorted_matches)} resultado(s), pero no existe el número {open_index}.",
                    "matches": [str(p) for p in sorted_matches[:20]],
                    "base_path": str(base),
                }
            opened = self._open_folder({"path": str(selected), "target": selected.name}) if selected.is_dir() else self._open_file({"path": str(selected), "target": selected.name})
            msg = opened_base_msg + f"Encontré {len(sorted_matches)} resultado(s) para {query}. Abriendo {selected.name}."
            return {
                "ok": bool(opened.get("ok")),
                "message": msg if opened.get("ok") else opened.get("error", "No pude abrir el resultado."),
                "matches": [str(p) for p in sorted_matches[:20]],
                "base_path": str(base),
                "opened": str(selected),
            }

        first = sorted_matches[0]
        kind = "carpeta" if first.is_dir() else "archivo"
        return {
            "ok": True,
            "message": opened_base_msg + f"Encontré {len(sorted_matches)} resultado(s). El primero es {first.name}, una {kind}.",
            "matches": [str(p) for p in sorted_matches[:20]],
            "base_path": str(base),
        }

    def _skip_path(self, p: Path) -> bool:
        bad_parts = {
            ".Trash-0", ".trash", "Trash", "node_modules", ".git", "__pycache__",
            ".cache", "cache", "tmp", "temp", "BackupsJarvis",
        }
        lower_parts = {part.lower() for part in p.parts}
        if any(b.lower() in lower_parts for b in bad_parts):
            return True
        text = str(p).lower()
        return any(x in text for x in ["/.trash", "/node_modules/", "/.git/", "/__pycache__/", "/backupsjarvis/"])


    def _clean_query(self, value: str) -> str:
        """Limpia basura común de STT: puntos/comas finales y espacios raros.

        Ejemplos:
        - "media." -> "media"
        - "package.json." -> "package.json"
        - "¡media!" -> "media"
        """
        q = str(value or "").strip().lower()
        q = re.sub(r"^[\s\.,;:¡!¿\?\(\)\[\]\"']+", "", q)
        q = re.sub(r"[\s\.,;:¡!¿\?\(\)\[\]\"']+$", "", q)
        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _rank_matches(self, matches: list[Path], query: str) -> list[Path]:
        q = query.lower().strip()

        def score(p: Path) -> tuple[int, str]:
            name = p.name.lower()
            s = 0
            if p.is_dir():
                s += 80
            if name == q:
                s += 400
            if name.startswith(q):
                s += 200
            if q in name:
                s += 100
            try:
                s -= min(len(p.parts), 80)
            except Exception:
                pass
            return (-s, str(p).lower())

        return sorted(matches, key=score)

# ---------------------------------------------------------------------------
# Jarvis v3.1.6 fixed: limpieza final de query en FilesSkill.
# Aunque el intent llegue con query="media.", la búsqueda usará "media".
# ---------------------------------------------------------------------------
def _jarvis_v31_6_clean_file_query(value):
    import re
    if value is None:
        return ""
    q = str(value).strip().lower()
    q = re.sub(r'^[\s"\'“”‘’¡¿]+', '', q)
    q = re.sub(r'[\s"\'“”‘’.,;:!?]+$', '', q)
    q = re.sub(r'\s+', ' ', q).strip()
    return q


try:
    if not getattr(FilesSkill, "_jarvis_v31_6_query_cleanup", False):
        _jarvis_v31_6_old_search_file = FilesSkill._search_file

        def _jarvis_v31_6_search_file(self, entities):
            entities = dict(entities or {})
            entities["query"] = _jarvis_v31_6_clean_file_query(entities.get("query", ""))
            return _jarvis_v31_6_old_search_file(self, entities)

        FilesSkill._search_file = _jarvis_v31_6_search_file
        FilesSkill._jarvis_v31_6_query_cleanup = True
except Exception:
    # Si cambia la clase en una versión futura, no romper import.
    pass

# ---------------------------------------------------------------------------
# v3.4.8 compatibility: voice query cleanup + safe xdg-open for paths with spaces
# ---------------------------------------------------------------------------
try:
    import re as _jarvis_re
    import subprocess as _jarvis_subprocess
    from pathlib import Path as _JarvisPath

    def _jarvis_v34_8_clean_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jarvis_re.sub(r"\s+", " ", q).strip()

        corrections = {
            "a a b": "aab",
            "a a ve": "aab",
            "aave": "aab",
            "aap": "aab",
            "abb": "aab",
            "aab.": "aab",
        }
        if q in corrections:
            return corrections[q]

        q = _jarvis_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jarvis_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jarvis_re.sub(r"\b(aap|abb|aave)\b", "aab", q)
        q = _jarvis_re.sub(r"\s+", " ", q).strip()
        return q

    def _jarvis_v34_8_label(path_value):
        try:
            p = _JarvisPath(str(path_value or "")).expanduser()
            return p.name or p.parent.name or str(p)
        except Exception:
            return str(path_value or "")

    def _jarvis_v34_8_safe_open(path_value):
        p = _JarvisPath(str(path_value or "")).expanduser()
        if not p.exists():
            return False
        _jarvis_subprocess.Popen(
            ["xdg-open", str(p)],
            stdout=_jarvis_subprocess.DEVNULL,
            stderr=_jarvis_subprocess.DEVNULL,
            start_new_session=True,
        )
        return True

    if "FilesSkill" in globals() and not getattr(FilesSkill.execute, "_jarvis_v34_8_wrapped", False):
        _jarvis_v34_8_orig_execute = FilesSkill.execute

        def _jarvis_v34_8_execute(self, intent):
            name = getattr(intent, "name", "")
            entities = getattr(intent, "entities", None)

            if isinstance(entities, dict):
                if "query" in entities:
                    entities["query"] = _jarvis_v34_8_clean_query(entities.get("query"))
                if "search_query" in entities:
                    entities["search_query"] = _jarvis_v34_8_clean_query(entities.get("search_query"))

                # Abrir carpetas con espacios usando argv list, no shell string.
                if name == "open_folder":
                    path = entities.get("path") or entities.get("folder")
                    if path and " " in str(path) and _jarvis_v34_8_safe_open(path):
                        return f"Abriendo {_jarvis_v34_8_label(path)}."

                manual_open_label = ""
                if name == "search_file" and entities.get("open_base"):
                    base_path = entities.get("base_path") or entities.get("path")
                    if base_path and _jarvis_v34_8_safe_open(base_path):
                        manual_open_label = _jarvis_v34_8_label(base_path)
                        # Evita que la implementación vieja abra mal la ruta con espacios.
                        entities["open_base"] = False
                        entities["_jarvis_v34_8_open_base_label"] = manual_open_label

                response = _jarvis_v34_8_orig_execute(self, intent)

                if isinstance(response, str):
                    base_path = entities.get("base_path") or entities.get("path")
                    label = entities.get("_jarvis_v34_8_open_base_label") or _jarvis_v34_8_label(base_path)
                    home_name = _JarvisPath.home().name

                    if label:
                        response = _jarvis_re.sub(rf"\bAbrí\s+{_jarvis_re.escape(home_name)}\b", f"Abrí {label}", response)
                        response = _jarvis_re.sub(rf"\ben\s+{_jarvis_re.escape(home_name)}\b", f"en {label}", response)

                    if manual_open_label and not response.lower().startswith("abrí "):
                        response = f"Abrí {manual_open_label}. {response}"

                return response

            return _jarvis_v34_8_orig_execute(self, intent)

        _jarvis_v34_8_execute._jarvis_v34_8_wrapped = True
        FilesSkill.execute = _jarvis_v34_8_execute
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.9 compatibility: safe open labels for alias paths with spaces
# ---------------------------------------------------------------------------
try:
    import re as _jv349_files_re
    import subprocess as _jv349_subprocess
    from pathlib import Path as _Jv349Path

    def _jv349_files_clean_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv349_files_re.sub(r"\s+", " ", q).strip()
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
        q = _jv349_files_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv349_files_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jv349_files_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        return _jv349_files_re.sub(r"\s+", " ", q).strip()

    def _jv349_label(path_value):
        try:
            p = _Jv349Path(str(path_value or "")).expanduser()
            return p.name or p.parent.name or str(p)
        except Exception:
            return str(path_value or "")

    def _jv349_open(path_value):
        p = _Jv349Path(str(path_value or "")).expanduser()
        if not p.exists():
            return False
        _jv349_subprocess.Popen(
            ["xdg-open", str(p)],
            stdout=_jv349_subprocess.DEVNULL,
            stderr=_jv349_subprocess.DEVNULL,
            start_new_session=True,
        )
        return True

    if "FilesSkill" in globals() and not getattr(FilesSkill.execute, "_jv349_wrapped", False):
        _jv349_orig_execute = FilesSkill.execute

        def _jv349_execute(self, intent):
            name = getattr(intent, "name", "")
            entities = getattr(intent, "entities", None)

            manual_open_label = ""
            base_label = ""

            if isinstance(entities, dict):
                for key in ("query", "search_query"):
                    if key in entities:
                        entities[key] = _jv349_files_clean_query(entities.get(key))

                base_path = entities.get("base_path") or entities.get("path")
                if base_path:
                    base_label = _jv349_label(base_path)

                if name == "open_folder":
                    path = entities.get("path") or entities.get("folder")
                    if path and _jv349_open(path):
                        return f"Abriendo {_jv349_label(path)}."

                if name == "search_file" and entities.get("open_base"):
                    if base_path and _jv349_open(base_path):
                        manual_open_label = _jv349_label(base_path)
                        # Avoid old internal open that may open /home/angel when path has spaces.
                        entities["open_base"] = False

            response = _jv349_orig_execute(self, intent)

            if isinstance(response, str) and isinstance(entities, dict):
                home_name = _Jv349Path.home().name
                label = manual_open_label or base_label
                if label:
                    response = _jv349_files_re.sub(rf"\bAbrí\s+{_jv349_files_re.escape(home_name)}\b", f"Abrí {label}", response)
                    response = _jv349_files_re.sub(rf"\ben\s+{_jv349_files_re.escape(home_name)}\b", f"en {label}", response)

                if manual_open_label and not response.lower().startswith("abrí "):
                    response = f"Abrí {manual_open_label}. {response}"

            return response

        _jv349_execute._jv349_wrapped = True
        FilesSkill.execute = _jv349_execute
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.10 compatibility: build artifact search ranking + safe base opening
# ---------------------------------------------------------------------------
try:
    import json as _jv3410_json
    import os as _jv3410_os
    import re as _jv3410_re
    import subprocess as _jv3410_subprocess
    import time as _jv3410_time
    from pathlib import Path as _Jv3410Path

    def _jv3410_clean_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv3410_re.sub(r"\s+", " ", q).strip()
        corrections = {
            "a a b": "aab",
            "a a ve": "aab",
            "aave": "aab",
            "aap": "aab",
            "abb": "aab",
            "aav": "aab",
            "ab": "aab",
            "a p k": "apk",
            "a pe ka": "apk",
        }
        if q in corrections:
            return corrections[q]
        q = _jv3410_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv3410_re.sub(r"\ba\s*p\s*k\b", "apk", q)
        q = _jv3410_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        return _jv3410_re.sub(r"\s+", " ", q).strip()

    def _jv3410_label(path_value):
        try:
            p = _Jv3410Path(str(path_value or "")).expanduser()
            return p.name or p.parent.name or str(p)
        except Exception:
            return str(path_value or "")

    def _jv3410_trunc_name(name, max_len=42):
        s = str(name or "")
        if len(s) <= max_len:
            return s
        p = _Jv3410Path(s)
        suffix = p.suffix
        stem = p.stem
        keep = max(12, max_len - len(suffix) - 3)
        return stem[:keep] + "..." + suffix

    def _jv3410_safe_open(path_value):
        p = _Jv3410Path(str(path_value or "")).expanduser()
        if not p.exists():
            return False
        _jv3410_subprocess.Popen(
            ["xdg-open", str(p)],
            stdout=_jv3410_subprocess.DEVNULL,
            stderr=_jv3410_subprocess.DEVNULL,
            start_new_session=True,
        )
        return True

    def _jv3410_should_skip_dir(dirname):
        d = str(dirname or "").lower()
        skip = {
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            ".gradle",
            ".cache",
            "cache",
            "__pycache__",
            ".trash",
            "trash",
            "tmp",
            "temp",
        }
        return d in skip or d.endswith(".cache")

    def _jv3410_score_path(path_obj, query):
        s = str(path_obj).lower()
        score = 0

        # Prefer real artifacts.
        if query == "aab" and path_obj.suffix.lower() == ".aab":
            score += 10000
        if query == "apk" and path_obj.suffix.lower() == ".apk":
            score += 10000

        preferred_terms = [
            "release",
            "production",
            "prod",
            "eas",
            "artifact",
            "artifacts",
            "android",
            "build",
            "dist",
            "playstore",
            "app",
        ]
        for i, term in enumerate(preferred_terms):
            if term in s:
                score += 500 - i * 10

        # Avoid junk-looking hash/cache paths.
        bad_terms = [
            ".cache",
            "node_modules",
            ".gradle/caches",
            "/cache/",
            "/tmp/",
            "/temp/",
            ".git",
        ]
        for term in bad_terms:
            if term in s:
                score -= 3000

        # Penalize very long hash-looking names.
        name = path_obj.name.lower()
        if len(name) > 48 and _jv3410_re.fullmatch(r"[a-f0-9._-]+", name):
            score -= 2500

        try:
            score += int(path_obj.stat().st_mtime) // 1000000
        except Exception:
            pass

        return score

    def _jv3410_search_artifacts(base_path, query, limit=80):
        base = _Jv3410Path(str(base_path or "")).expanduser()
        if not base.exists():
            return []

        q = _jv3410_clean_query(query)
        ext = None
        if q in {"aab", ".aab"}:
            ext = ".aab"
            q = "aab"
        elif q in {"apk", ".apk"}:
            ext = ".apk"
            q = "apk"

        results = []
        start = _jv3410_time.monotonic()

        # First pass: exact extension artifacts only.
        if ext:
            try:
                for p in base.rglob(f"*{ext}"):
                    if _jv3410_time.monotonic() - start > 20:
                        break
                    if not p.exists() or not p.is_file():
                        continue
                    if any(_jv3410_should_skip_dir(part) for part in p.parts):
                        continue
                    results.append(p)
                    if len(results) >= limit * 3:
                        break
            except Exception:
                pass

        # Fallback pass: contains query in name, but still avoid junk.
        if not results:
            try:
                for root, dirs, files in _jv3410_os.walk(str(base)):
                    dirs[:] = [d for d in dirs if not _jv3410_should_skip_dir(d)]

                    if _jv3410_time.monotonic() - start > 20:
                        break

                    for filename in files:
                        if q not in filename.lower():
                            continue
                        p = _Jv3410Path(root) / filename
                        if any(_jv3410_should_skip_dir(part) for part in p.parts):
                            continue
                        results.append(p)
                        if len(results) >= limit * 3:
                            break
                    if len(results) >= limit * 3:
                        break
            except Exception:
                pass

        # Unique + ranked.
        unique = {}
        for p in results:
            unique[str(p)] = p

        ranked = sorted(
            unique.values(),
            key=lambda p: (_jv3410_score_path(p, q), str(p).lower()),
            reverse=True,
        )
        return ranked[:limit]

    def _jv3410_save_results(base_path, query, results):
        try:
            ctx_path = _Jv3410Path.home() / ".local/share/jarvis/context.json"
            ctx_path.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if ctx_path.exists():
                try:
                    data = _jv3410_json.loads(ctx_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}

            items = [
                {
                    "path": str(p),
                    "name": p.name,
                    "is_dir": p.is_dir(),
                    "type": "folder" if p.is_dir() else "file",
                }
                for p in results[:50]
            ]

            # Several key names for compatibility with older open_result logic.
            data["last_folder"] = str(base_path)
            data["last_search_query"] = str(query)
            data["last_search_results"] = items
            data["search_results"] = items
            data["last_results"] = items
            data["results"] = items

            ctx_path.write_text(_jv3410_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _jv3410_handle_artifact_search(intent):
        entities = getattr(intent, "entities", {}) or {}
        q = _jv3410_clean_query(entities.get("query") or entities.get("search_query") or "")
        base_path = entities.get("base_path") or entities.get("path") or entities.get("folder") or str(_Jv3410Path.home())
        base = _Jv3410Path(str(base_path)).expanduser()
        label = _jv3410_label(base)
        open_base = bool(entities.get("open_base"))
        open_first = bool(entities.get("open_first"))
        open_index = int(entities.get("open_index") or 1)

        if open_base:
            _jv3410_safe_open(base)

        results = _jv3410_search_artifacts(base, q, limit=80)
        _jv3410_save_results(base, q, results)

        prefix = f"Abrí {label}. " if open_base else ""

        artifact_word = "archivo"
        if q in {"aab", "apk"}:
            artifact_word = f"archivo .{q}"

        if not results:
            return f"{prefix}No encontré {artifact_word}s en {label}."

        first = results[max(0, min(open_index - 1, len(results) - 1))]
        first_name = _jv3410_trunc_name(first.name)

        if open_first:
            _jv3410_safe_open(first)
            return f"{prefix}Encontré {len(results)} {artifact_word}(s) en {label}. Abriendo {first_name}."

        if len(results) > 20:
            return f"{prefix}Encontré {len(results)} {artifact_word}(s) en {label}. El primero es {first_name}."

        return f"{prefix}Encontré {len(results)} {artifact_word}(s) en {label}. El primero es {first_name}."

    if "FilesSkill" in globals() and not getattr(FilesSkill.execute, "_jv3410_wrapped", False):
        _jv3410_orig_execute = FilesSkill.execute

        def _jv3410_execute(self, intent):
            name = getattr(intent, "name", "")
            entities = getattr(intent, "entities", None)

            if isinstance(entities, dict):
                for key in ("query", "search_query"):
                    if key in entities:
                        entities[key] = _jv3410_clean_query(entities.get(key))

                q = _jv3410_clean_query(entities.get("query") or entities.get("search_query") or "")
                base_path = entities.get("base_path") or entities.get("path") or ""

                # Use robust artifact search for build artifacts and alias build folders.
                if name == "search_file" and (
                    q in {"aab", "apk"} or "apps playstore" in str(base_path).lower()
                ):
                    return _jv3410_handle_artifact_search(intent)

                if name == "open_folder":
                    path = entities.get("path") or entities.get("folder")
                    if path and _jv3410_safe_open(path):
                        return f"Abriendo {_jv3410_label(path)}."

            return _jv3410_orig_execute(self, intent)

        _jv3410_execute._jv3410_wrapped = True
        FilesSkill.execute = _jv3410_execute

except Exception:
    pass



# ---------------------------------------------------------------------------
# v4.1.1.9 phase 1C: typed file actions expansion
# ---------------------------------------------------------------------------
try:
    import os as _v4119_os
    import re as _v4119_re
    import shutil as _v4119_shutil
    from pathlib import Path as _V4119Path

    _V4119_EXTRA_ACTIONS = (
        ActionSpec(
            name='open_folder',
            namespace='files',
            description='Abre una carpeta local.',
            intents=('open_folder',),
            examples=('abre Descargas',),
            risk_level=RiskLevel.SAFE,
            backend='xdg-open',
        ),
        ActionSpec(
            name='open_file',
            namespace='files',
            description='Abre un archivo local.',
            intents=('open_file',),
            examples=('abre el archivo reporte.pdf',),
            risk_level=RiskLevel.SAFE,
            backend='xdg-open',
        ),
        ActionSpec(
            name='search',
            namespace='files',
            description='Busca archivos o carpetas por nombre.',
            intents=('search_file',),
            examples=('busca factura',),
            risk_level=RiskLevel.SAFE,
            backend='Path.rglob',
        ),
        ActionSpec(
            name='open_result',
            namespace='files',
            description='Abre uno de los resultados guardados de una búsqueda anterior.',
            intents=('open_result',),
            examples=('abre el resultado 2',),
            risk_level=RiskLevel.SAFE,
            backend='ContextStore search results',
        ),
        ActionSpec(
            name='list_directory',
            namespace='files',
            description='Lista el contenido de una carpeta.',
            intents=('list_directory',),
            examples=('lista archivos de Descargas',),
            risk_level=RiskLevel.SAFE,
            backend='Path.iterdir',
        ),
        ActionSpec(
            name='create_folder',
            namespace='files',
            description='Crea una carpeta local.',
            intents=('create_folder',),
            examples=('crea una carpeta pruebas',),
            risk_level=RiskLevel.MODERATE,
            backend='Path.mkdir',
        ),
        ActionSpec(
            name='rename',
            namespace='files',
            description='Renombra un archivo o carpeta local.',
            intents=('rename_path',),
            examples=('renombra reporte.txt a reporte-final.txt',),
            risk_level=RiskLevel.MODERATE,
            backend='Path.rename',
        ),
        ActionSpec(
            name='copy',
            namespace='files',
            description='Copia un archivo o carpeta a otro destino.',
            intents=('copy_path',),
            examples=('copia foto.jpg a Descargas',),
            risk_level=RiskLevel.MODERATE,
            backend='shutil.copy2|copytree',
        ),
        ActionSpec(
            name='move',
            namespace='files',
            description='Mueve un archivo o carpeta a otro destino.',
            intents=('move_path',),
            examples=('mueve reporte.pdf a Documentos',),
            risk_level=RiskLevel.MODERATE,
            backend='shutil.move',
        ),
        ActionSpec(
            name='delete',
            namespace='files',
            description='Mueve un archivo o carpeta a la papelera local.',
            intents=('delete_path',),
            examples=('borra reporte-viejo.txt',),
            risk_level=RiskLevel.SENSITIVE,
            backend='move to ~/.local/share/Trash/files',
            requires_confirmation=True,
        ),
    )

    _V4119_ALIAS_DIRS = {
        'descargas': _V4119Path.home() / 'Descargas',
        'downloads': _V4119Path.home() / 'Descargas',
        'documentos': _V4119Path.home() / 'Documentos',
        'documents': _V4119Path.home() / 'Documentos',
        'escritorio': _V4119Path.home() / 'Escritorio',
        'desktop': _V4119Path.home() / 'Escritorio',
        'imágenes': _V4119Path.home() / 'Imágenes',
        'imagenes': _V4119Path.home() / 'Imágenes',
        'pictures': _V4119Path.home() / 'Imágenes',
        'música': _V4119Path.home() / 'Música',
        'musica': _V4119Path.home() / 'Música',
        'music': _V4119Path.home() / 'Música',
        'videos': _V4119Path.home() / 'Videos',
        'vídeos': _V4119Path.home() / 'Videos',
        'home': _V4119Path.home(),
        'inicio': _V4119Path.home(),
    }

    def _v4119_pick_base(self):
        try:
            ctx = ContextStore(self.config)
            last = ctx.get_last_folder()
            if last:
                p = _V4119Path(str(last)).expanduser()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass
        return _V4119Path.home()

    def _v4119_coerce_path(self, raw, prefer_dir=False, must_exist=True, allow_search=True):
        value = str(raw or '').strip().strip("\"'")
        if not value:
            return None
        low = value.lower()
        if low in _V4119_ALIAS_DIRS:
            p = _V4119_ALIAS_DIRS[low]
            return p if (not must_exist or p.exists()) else None

        p = _V4119Path(value).expanduser()
        if p.exists():
            if prefer_dir and not p.is_dir():
                return None
            return p
        if value.startswith('~/') or value.startswith('/'):
            return None if must_exist else p
        if allow_search:
            base = _v4119_pick_base(self)
            candidates = []
            try:
                for child in base.rglob('*'):
                    name = child.name.lower()
                    if low == name or low in name:
                        if prefer_dir and not child.is_dir():
                            continue
                        candidates.append(child)
                    if len(candidates) >= 50:
                        break
            except Exception:
                pass
            if candidates:
                candidates.sort(key=lambda c: (0 if c.name.lower() == low else 1, len(str(c))))
                return candidates[0]
        return None if must_exist else (_v4119_pick_base(self) / value)

    def _v4119_unique_destination(dest):
        if not dest.exists():
            return dest
        stem = dest.stem
        suffix = dest.suffix
        parent = dest.parent
        for idx in range(2, 1000):
            candidate = parent / f'{stem}-{idx}{suffix}'
            if not candidate.exists():
                return candidate
        return parent / f'{stem}-overflow{suffix}'

    def _v4119_list_directory(self, entities):
        target = _v4119_coerce_path(self, entities.get('path') or entities.get('target') or entities.get('directory') or '', prefer_dir=True)
        if target is None:
            target = _v4119_pick_base(self)
        if not target.exists() or not target.is_dir():
            return {'ok': False, 'error': 'No encontré la carpeta a listar.'}
        try:
            items = sorted(list(target.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception as exc:
            return {'ok': False, 'error': f'No pude listar la carpeta: {exc}'}
        preview = [p.name + ('/' if p.is_dir() else '') for p in items[:12]]
        msg = f'{target.name}: ' + (', '.join(preview) if preview else 'sin elementos visibles.')
        try:
            ContextStore(self.config).set_last_folder(str(target), target.name)
        except Exception:
            pass
        return {'ok': True, 'message': msg, 'path': str(target), 'items': [str(p) for p in items[:50]]}

    def _v4119_create_folder(self, entities):
        name = str(entities.get('name') or entities.get('folder_name') or entities.get('target') or '').strip()
        base = str(entities.get('base_path') or entities.get('path') or '').strip()
        if not name:
            return {'ok': False, 'error': 'No detecté el nombre de la carpeta.'}
        if '/' in name or name.startswith('~'):
            new_dir = _V4119Path(name).expanduser()
        else:
            base_dir = _v4119_coerce_path(self, base, prefer_dir=True) if base else _v4119_pick_base(self)
            if base_dir is None:
                base_dir = _v4119_pick_base(self)
            new_dir = base_dir / name
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            try:
                ContextStore(self.config).set_last_folder(str(new_dir), new_dir.name)
            except Exception:
                pass
            return {'ok': True, 'message': f'Carpeta creada: {new_dir.name}.', 'path': str(new_dir)}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude crear la carpeta: {exc}'}

    def _v4119_rename_path(self, entities):
        src = _v4119_coerce_path(self, entities.get('source') or entities.get('path') or entities.get('target') or '')
        new_name = str(entities.get('new_name') or entities.get('destination_name') or entities.get('name') or '').strip()
        if src is None:
            return {'ok': False, 'error': 'No encontré el archivo o carpeta a renombrar.'}
        if not new_name:
            return {'ok': False, 'error': 'No detecté el nombre nuevo.'}
        dest = src.with_name(new_name)
        dest = _v4119_unique_destination(dest) if dest.exists() and dest != src else dest
        try:
            src.rename(dest)
            return {'ok': True, 'message': f'Renombrado a {dest.name}.', 'source': str(src), 'path': str(dest)}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude renombrar: {exc}'}

    def _v4119_copy_path(self, entities):
        src = _v4119_coerce_path(self, entities.get('source') or entities.get('path') or entities.get('target') or '')
        dest_dir = _v4119_coerce_path(self, entities.get('destination') or entities.get('destination_dir') or entities.get('to') or '', prefer_dir=True)
        if src is None:
            return {'ok': False, 'error': 'No encontré el origen para copiar.'}
        if dest_dir is None:
            dest_dir = _v4119_pick_base(self)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _v4119_unique_destination(dest_dir / src.name)
        try:
            if src.is_dir():
                _v4119_shutil.copytree(src, dest)
            else:
                _v4119_shutil.copy2(src, dest)
            return {'ok': True, 'message': f'Copiado a {dest}.', 'source': str(src), 'path': str(dest)}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude copiar: {exc}'}

    def _v4119_move_path(self, entities):
        src = _v4119_coerce_path(self, entities.get('source') or entities.get('path') or entities.get('target') or '')
        dest_dir = _v4119_coerce_path(self, entities.get('destination') or entities.get('destination_dir') or entities.get('to') or '', prefer_dir=True)
        if src is None:
            return {'ok': False, 'error': 'No encontré el origen para mover.'}
        if dest_dir is None:
            dest_dir = _v4119_pick_base(self)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = _v4119_unique_destination(dest_dir / src.name)
        try:
            out = _v4119_shutil.move(str(src), str(dest))
            return {'ok': True, 'message': f'Movido a {dest_dir}.', 'source': str(src), 'path': str(out)}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude mover: {exc}'}

    def _v4119_delete_path(self, entities):
        src = _v4119_coerce_path(self, entities.get('source') or entities.get('path') or entities.get('target') or '')
        if src is None:
            return {'ok': False, 'error': 'No encontré el archivo o carpeta a borrar.'}
        trash = _V4119Path.home() / '.local/share/Trash/files'
        try:
            trash.mkdir(parents=True, exist_ok=True)
            dest = _v4119_unique_destination(trash / src.name)
            out = _v4119_shutil.move(str(src), str(dest))
            return {'ok': True, 'message': f'Enviado a la papelera: {src.name}.', 'source': str(src), 'trash_path': str(out)}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude enviar a la papelera: {exc}'}

    FilesSkill.ACTIONS = _V4119_EXTRA_ACTIONS
    _v4119_orig_can_handle = FilesSkill.can_handle
    _v4119_orig_run = FilesSkill.run

    def _v4119_files_can_handle(self, intent):
        return _v4119_orig_can_handle(self, intent) or intent.name in {
            'list_directory', 'create_folder', 'rename_path', 'copy_path', 'move_path', 'delete_path'
        }

    def _v4119_files_run(self, intent, entities, context):
        if intent.name == 'list_directory':
            return _v4119_list_directory(self, entities)
        if intent.name == 'create_folder':
            return _v4119_create_folder(self, entities)
        if intent.name == 'rename_path':
            return _v4119_rename_path(self, entities)
        if intent.name == 'copy_path':
            return _v4119_copy_path(self, entities)
        if intent.name == 'move_path':
            return _v4119_move_path(self, entities)
        if intent.name == 'delete_path':
            return _v4119_delete_path(self, entities)
        return _v4119_orig_run(self, intent, entities, context)

    FilesSkill.can_handle = _v4119_files_can_handle
    FilesSkill.run = _v4119_files_run
except Exception:
    pass
