from __future__ import annotations

import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FolderMatch:
    path: str
    name: str
    score: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "name": self.name,
            "score": self.score,
            "reason": self.reason,
        }


class FolderIndex:
    """
    Índice local de carpetas para Jarvis.

    Escanea carpetas principales del usuario y guarda:
    - nombre de carpeta
    - ruta
    - nombre normalizado
    - ruta normalizada

    Luego busca coincidencias aproximadas.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        data_dir = Path.home() / ".local/share/jarvis"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = data_dir / "folder_index.db"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS folders (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    norm_name TEXT NOT NULL,
                    norm_path TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_folders_norm_name ON folders(norm_name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_folders_updated_at ON folders(updated_at)")
            con.commit()

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) FROM folders").fetchone()
            return int(row[0] or 0)

    def clear(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM folders")
            con.commit()

    def index_default_roots(self, rebuild: bool = False) -> int:
        if rebuild:
            self.clear()

        roots = self._default_roots()
        total = 0

        for root in roots:
            total += self.index_root(root)

        return total

    def index_root(self, root: str | Path, max_depth: int = 7, max_dirs: int = 30000) -> int:
        root_path = Path(root).expanduser()

        if not root_path.exists() or not root_path.is_dir():
            return 0

        skip_names = {
            ".git",
            ".cache",
            ".local",
            ".config",
            ".mozilla",
            ".steam",
            ".var",
            "node_modules",
            "__pycache__",
            ".gradle",
            ".expo",
            ".next",
            ".nuxt",
            ".venv",
            "venv",
            "env",
            "dist",
            "build",
            "coverage",
            "Trash",
        }

        now = time.time()
        rows: list[tuple[str, str, str, str, int, float]] = []

        root_depth = len(root_path.parts)

        def walk(path: Path) -> None:
            nonlocal rows

            if len(rows) >= max_dirs:
                return

            try:
                depth = len(path.parts) - root_depth
            except Exception:
                depth = 0

            if depth > max_depth:
                return

            try:
                entries = list(os.scandir(path))
            except Exception:
                return

            for entry in entries:
                if len(rows) >= max_dirs:
                    return

                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                except Exception:
                    continue

                name = entry.name

                if not name:
                    continue

                # No escanear ocultos pesados.
                if name.startswith(".") or name in skip_names:
                    continue

                child = Path(entry.path)

                try:
                    child_depth = len(child.parts) - root_depth
                except Exception:
                    child_depth = depth + 1

                path_str = str(child)
                norm_name = self._norm(name)
                norm_path = self._norm(path_str)

                rows.append((path_str, name, norm_name, norm_path, child_depth, now))

                walk(child)

        # Incluir raíz también.
        rows.append((
            str(root_path),
            root_path.name or str(root_path),
            self._norm(root_path.name or str(root_path)),
            self._norm(str(root_path)),
            0,
            now,
        ))

        walk(root_path)

        with sqlite3.connect(self.db_path) as con:
            con.executemany(
                """
                INSERT INTO folders(path, name, norm_name, norm_path, depth, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    norm_name=excluded.norm_name,
                    norm_path=excluded.norm_path,
                    depth=excluded.depth,
                    updated_at=excluded.updated_at
                """,
                rows,
            )
            con.commit()

        return len(rows)

    def search(self, query: str, limit: int = 8, auto_index: bool = True) -> list[FolderMatch]:
        if auto_index and self.count() == 0:
            self.index_default_roots(rebuild=True)

        q = self._clean_query(query)
        q_norm = self._norm(q)

        if not q_norm:
            return []

        q_words = self._meaningful_words(q_norm)

        if not q_words:
            return []

        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT path, name, norm_name, norm_path, depth FROM folders"
            ).fetchall()

        matches: list[FolderMatch] = []

        bad_path_parts = [
            "/site-packages/",
            "/dist-packages/",
            "/src/",
            "/__pycache__",
            "/.git/",
            "/node_modules/",
            "/venv/",
            "/.venv/",
            "/env/",
            "/adk-venv/",
            "/BackupsJarvis/",
            "/jarvis_backup_",
            "/.cache/",
            "/.local/",
            "/.config/",
        ]

        preferred_path_parts = [
            "/Descargas/",
            "/Documents/",
            "/Documentos/",
            "/Escritorio/",
            "/Desktop/",
            "/Projects/",
            "/Proyectos/",
        ]

        for path, name, norm_name, norm_path, depth in rows:
            path_str = str(path)
            score = 0
            reasons: list[str] = []

            n_words = self._meaningful_words(norm_name)
            p_words = self._meaningful_words(norm_path)

            shared_name = q_words & n_words
            shared_path = q_words & p_words
            shared_all = q_words & (n_words | p_words)

            # Si el usuario dijo varias palabras, exigir más coincidencia.
            # Ejemplo: "apps playstore" NO debe aceptar solo "apps".
            if len(q_words) >= 2 and len(shared_all) < min(2, len(q_words)):
                continue

            # Si no comparte nada útil, no aceptar.
            if not shared_name and not shared_path and q_norm not in norm_name and q_norm not in norm_path:
                continue

            if q_norm == norm_name:
                score += 250
                reasons.append("nombre exacto")

            if q_norm in norm_name:
                score += 180
                reasons.append("query en nombre")

            if norm_name in q_norm and len(norm_name) >= 3:
                score += 120
                reasons.append("nombre en query")

            if q_norm in norm_path:
                score += 110
                reasons.append("query en ruta")

            score += len(shared_name) * 70
            score += len(shared_path) * 25

            if shared_name:
                reasons.append("palabras en nombre:" + ",".join(sorted(shared_name)))

            if shared_path:
                reasons.append("palabras en ruta:" + ",".join(sorted(shared_path)))

            # Preferir rutas normales del usuario.
            if any(part in path_str for part in preferred_path_parts):
                score += 35
                reasons.append("ruta preferida")

            # Penalizar resultados técnicos internos.
            for bad in bad_path_parts:
                if bad in path_str:
                    score -= 220
                    reasons.append("penalizado:" + bad.strip("/"))
                    break

            # Penalizar backups para que no ganen sobre proyecto real.
            if "backup" in norm_path or "backups" in norm_path:
                score -= 160
                reasons.append("penalizado:backup")

            # Si el nombre exacto es paquete interno bajo src/site-packages, no debe ganar tan fácil.
            if ("/src/" in path_str or "/site-packages/" in path_str) and q_norm == norm_name:
                score -= 250
                reasons.append("penalizado:paquete interno exacto")

            # Preferir carpetas menos profundas si el score es similar.
            try:
                score -= min(int(depth), 25)
            except Exception:
                pass

            if score <= 0:
                continue

            matches.append(FolderMatch(
                path=path,
                name=name,
                score=score,
                reason="; ".join(reasons) or "coincidencia",
            ))

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]


    def best(self, query: str, min_score: int = 70) -> FolderMatch | None:
        matches = self.search(query, limit=1, auto_index=True)

        if not matches:
            return None

        best = matches[0]

        if best.score < min_score:
            return None

        return best

    def _default_roots(self) -> list[Path]:
        home = Path.home()

        roots = [
            home / "Descargas",
            home / "Downloads",
            home / "Documentos",
            home / "Documents",
            home / "Escritorio",
            home / "Desktop",
            home / "Videos",
            home / "Imágenes",
            home / "Pictures",
            home / "Música",
            home / "Music",
            home / "Proyectos",
            home / "Projects",
        ]

        # Roots extra definidos por el usuario.
        extra_roots = self.config.get("folder_index", {}).get("extra_roots", []) or []
        for extra in extra_roots:
            try:
                roots.append(Path(str(extra)).expanduser())
            except Exception:
                pass

        # También escanear HOME, pero con skips fuertes.
        roots.append(home)

        unique: list[Path] = []
        seen: set[str] = set()

        for r in roots:
            try:
                rp = str(r.expanduser())
            except Exception:
                continue

            if rp not in seen and r.exists() and r.is_dir():
                seen.add(rp)
                unique.append(r)

        return unique

    def _clean_query(self, query: str) -> str:
        q = str(query or "").strip().lower()

        remove = [
            "abre la carpeta de",
            "abre carpeta de",
            "abre la carpeta",
            "abre carpeta",
            "abrir carpeta de",
            "abrir carpeta",
            "que abras la carpeta de",
            "que abras la carpeta",
            "muestra la carpeta de",
            "muestra carpeta de",
            "ensename la carpeta de",
            "enséñame la carpeta de",
            "quiero ver la carpeta de",
            "carpeta de",
            "carpeta",
            "folder",
            "directorio",
        ]

        for phrase in sorted(remove, key=len, reverse=True):
            q = q.replace(phrase, " ")

        q = re.sub(r"\s+", " ", q).strip()
        return q

    def _meaningful_words(self, text: str) -> set[str]:
        stop = {
            "abre", "abrir", "abras", "abreme",
            "que", "mi", "mis", "la", "el", "los", "las",
            "de", "del", "en", "a", "al", "por", "para",
            "carpeta", "carpetas", "folder", "directorio",
            "quiero", "ver", "muestra", "ensename", "ensename",
            "home", "angel", "descargas", "homeangel",
        }

        return {
            w for w in self._norm(text).split()
            if len(w) > 2 and w not in stop
        }

    def _norm(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\s:/._-]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
