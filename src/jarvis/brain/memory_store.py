from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class MemoryItem:
    key: str
    value: str
    type: str = "generic"
    source: str = "user"
    note: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "type": self.type,
            "source": self.source,
            "note": self.note,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemoryStore:
    """
    Memoria local SQLite para Jarvis.

    Tipos recomendados:
    - folder: alias de carpeta
    - url: alias de URL
    - service: alias de servicio
    - preference: preferencia del usuario
    - app: alias de app
    - generic: recuerdo general
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        memory_cfg = self.config.get("memory", {}) or {}

        db_path = memory_cfg.get("db_path", "~/.local/share/jarvis/memory.db")
        self.db_path = Path(str(db_path)).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'generic',
                    source TEXT NOT NULL DEFAULT 'user',
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)")
            con.commit()

    def remember(
        self,
        key: str,
        value: str,
        type: str = "generic",
        source: str = "user",
        note: str = "",
    ) -> MemoryItem:
        key = self._clean_key(key)
        value = str(value or "").strip()
        type = self._clean_type(type)
        source = str(source or "user").strip() or "user"
        note = str(note or "").strip()

        if not key:
            raise ValueError("La clave de memoria está vacía.")

        if not value:
            raise ValueError("El valor de memoria está vacío.")

        now = time.time()

        with sqlite3.connect(self.db_path) as con:
            old = con.execute(
                "SELECT created_at FROM memories WHERE key = ?",
                (key,),
            ).fetchone()

            created_at = float(old[0]) if old else now

            con.execute(
                """
                INSERT INTO memories(key, value, type, source, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    type=excluded.type,
                    source=excluded.source,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (key, value, type, source, note, created_at, now),
            )
            con.commit()

        return MemoryItem(key, value, type, source, note, created_at, now)

    def forget(self, key_or_query: str) -> int:
        q = self._norm(key_or_query)
        deleted = 0

        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT key FROM memories").fetchall()

            for (key,) in rows:
                if self._norm(key) == q or q in self._norm(key) or self._norm(key) in q:
                    con.execute("DELETE FROM memories WHERE key = ?", (key,))
                    deleted += 1

            con.commit()

        return deleted

    def get(self, key: str) -> MemoryItem | None:
        key_clean = self._clean_key(key)

        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                "SELECT key, value, type, source, note, created_at, updated_at FROM memories WHERE key = ?",
                (key_clean,),
            ).fetchone()

        return self._row_to_item(row)

    def list(self, type: str | None = None) -> list[MemoryItem]:
        with sqlite3.connect(self.db_path) as con:
            if type:
                rows = con.execute(
                    "SELECT key, value, type, source, note, created_at, updated_at FROM memories WHERE type = ? ORDER BY updated_at DESC",
                    (self._clean_type(type),),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT key, value, type, source, note, created_at, updated_at FROM memories ORDER BY updated_at DESC"
                ).fetchall()

        return [item for row in rows if (item := self._row_to_item(row))]

    def find_best(self, query: str, type: str | None = None) -> MemoryItem | None:
        q = self._norm(query)

        if not q:
            return None

        candidates = self.list(type=type)

        stopwords = {
            "abre", "abrir", "abras", "abreme", "ábreme",
            "muestra", "ensename", "enséñame",
            "mi", "mis", "la", "el", "los", "las",
            "de", "del", "en", "a", "al", "que",
            "carpeta", "carpetas", "directorio", "folder",
            "quiero", "ver"
        }

        def meaningful_words(s: str) -> set[str]:
            return {
                w for w in self._norm(s).split()
                if len(w) > 2 and w not in stopwords
            }

        q_words = meaningful_words(q)

        # Si no hay palabras útiles, no usar memoria fuzzy.
        if not q_words:
            return None

        best: tuple[int, MemoryItem] | None = None

        for item in candidates:
            key_n = self._norm(item.key)
            value_n = self._norm(item.value)

            k_words = meaningful_words(key_n)
            v_words = meaningful_words(value_n)

            # Requisito: debe compartir al menos una palabra significativa.
            shared_key = q_words & k_words
            shared_value = q_words & v_words

            if not shared_key and not shared_value:
                continue

            score = 0

            # Coincidencia exacta o frase completa.
            if key_n == q:
                score += 100

            if key_n in q:
                score += 80

            if q in key_n:
                score += 60

            # Palabras importantes compartidas.
            score += len(shared_key) * 25
            score += len(shared_value) * 10

            # Penalización: si el recuerdo es de carpeta, no permitir que solo
            # coincida por palabras genéricas. Ejemplo: "carpeta de documentos"
            # NO debe agarrar "carpeta de descargas".
            if item.type == "folder":
                strong_folder_words = {
                    "descargas", "downloads",
                    "documentos", "documents",
                    "escritorio", "desktop",
                    "videos",
                    "imagenes", "imágenes",
                    "musica", "música",
                    "build", "builds", "buil", "buyos", "buidos", "bild",
                    "apps", "playstore", "play", "store"
                }

                q_strong = q_words & strong_folder_words
                k_strong = k_words & strong_folder_words
                v_strong = v_words & strong_folder_words

                # Si el usuario menciona una carpeta fuerte diferente y el recuerdo no la comparte,
                # saltar ese recuerdo.
                if q_strong and not ((q_strong & k_strong) or (q_strong & v_strong)):
                    continue

            if score > 0 and (best is None or score > best[0]):
                best = (score, item)

        return best[1] if best else None


    def resolve_folder(self, query: str) -> str | None:
        item = self.find_best(query, type="folder")

        if item:
            return self._resolve_path_text(item.value)

        return None

    def resolve_url(self, query: str) -> str | None:
        item = self.find_best(query, type="url")

        if item:
            return item.value

        return None

    def resolve_service(self, query: str) -> str | None:
        item = self.find_best(query, type="service")

        if item:
            return item.value

        return None

    def get_preference(self, key: str, default: str = "") -> str:
        item = self.get(f"preferencia {key}") or self.get(key)

        if item:
            return item.value

        return default

    def remember_from_text(self, raw: str) -> MemoryItem | None:
        """
        Interpreta frases naturales como:

        - recuerda que mi carpeta de builds está en Descargas Apps playstore
        - recuerda que mi servidor de películas es jellyfin
        - recuerda que prefiero youtube para música
        - recuerda que mi panel de apps es play console
        - recuerda que mi navegador preferido es brave
        """

        text = str(raw or "").strip()
        t = self._norm(text)

        if not t.startswith("recuerda que "):
            return None

        content = text.strip()[len("recuerda que "):].strip()
        c = self._norm(content)

        # Preferencia musical.
        if "prefiero" in c and ("musica" in c or "música" in c):
            platform = ""
            if "youtube music" in c:
                platform = "youtube_music"
            elif "youtube" in c:
                platform = "youtube"
            elif "tidal" in c:
                platform = "tidal"
            elif "spotify" in c:
                platform = "spotify"

            if platform:
                return self.remember(
                    "preferencia plataforma musical",
                    platform,
                    type="preference",
                    note=content,
                )

        # Carpeta.
        folder_match = re.search(
            r"(?:mi\s+)?carpeta\s+de\s+(.+?)\s+(?:esta|está|es|queda|queda en|esta en|está en)\s+(.+)$",
            c,
        )

        if folder_match:
            name = folder_match.group(1).strip()
            value_raw = content.split()[-1]

        # Regex más robusto usando texto normalizado completo.
        folder_match = re.search(
            r"(?:mi\s+)?carpeta\s+de\s+(.+?)\s+(?:esta|está|es|queda|esta en|está en|queda en)\s+(.+)$",
            c,
        )

        if folder_match:
            name = folder_match.group(1).strip()
            value = folder_match.group(2).strip()
            path = self._resolve_path_text(value)

            return self.remember(
                f"carpeta de {name}",
                path,
                type="folder",
                note=content,
            )

        # Servicio.
        service_match = re.search(
            r"(?:mi\s+)?servidor\s+de\s+(.+?)\s+(?:es|se llama|usa|corre en)\s+(.+)$",
            c,
        )

        if service_match:
            name = service_match.group(1).strip()
            service = service_match.group(2).strip().split()[0]

            return self.remember(
                f"servidor de {name}",
                service,
                type="service",
                note=content,
            )

        # URL/panel.
        url_match = re.search(
            r"(?:mi\s+)?(.+?)\s+(?:es|esta en|está en|abre en)\s+(.+)$",
            c,
        )

        if url_match:
            name = url_match.group(1).strip()
            value = url_match.group(2).strip()
            resolved = self._resolve_known_url(value)

            if resolved:
                return self.remember(
                    name,
                    resolved,
                    type="url",
                    note=content,
                )

        # Navegador preferido.
        if "navegador" in c and ("preferido" in c or "prefiero" in c):
            value = ""
            if "brave" in c:
                value = "brave-browser"
            elif "chrome" in c:
                value = "google-chrome"
            elif "chromium" in c:
                value = "chromium"
            elif "firefox" in c:
                value = "firefox"

            if value:
                return self.remember(
                    "preferencia navegador",
                    value,
                    type="preference",
                    note=content,
                )

        # Forma genérica:
        # recuerda que X es Y
        generic = re.search(r"(.+?)\s+(?:es|esta en|está en|se llama)\s+(.+)$", c)

        if generic:
            key = generic.group(1).strip()
            value = generic.group(2).strip()

            return self.remember(
                key,
                value,
                type="generic",
                note=content,
            )

        return self.remember(
            content,
            "true",
            type="generic",
            note=content,
        )

    def _resolve_known_url(self, text: str) -> str | None:
        t = self._norm(text)

        mapping = {
            "google play console": "https://play.google.com/console",
            "play console": "https://play.google.com/console",
            "consola de google play": "https://play.google.com/console",
            "firebase": "https://console.firebase.google.com",
            "revenuecat": "https://app.revenuecat.com",
            "expo": "https://expo.dev",
            "groq": "https://console.groq.com",
            "github": "https://github.com",
            "youtube": "https://www.youtube.com",
            "youtube music": "https://music.youtube.com",
            "tidal": "https://tidal.com",
            "spotify": "https://open.spotify.com",
            "chatgpt": "https://chatgpt.com",
            "gmail": "https://mail.google.com",
            "drive": "https://drive.google.com",
            "whatsapp": "https://web.whatsapp.com",
        }

        for key, value in sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True):
            if key in t:
                return value

        if re.match(r"^[\\w.-]+\\.[a-z]{2,}(/.*)?$", text.strip()) and not text.startswith(("http://", "https://")):
            return "https://" + text.strip()

        if text.startswith(("http://", "https://")):
            return text.strip()

        return None

    def _resolve_path_text(self, value: str) -> str:
        raw = str(value or "").strip()
        t = self._norm(raw)

        if raw.startswith("~/") or raw.startswith("/"):
            return str(Path(raw).expanduser())

        base_map = {
            "descargas": Path.home() / "Descargas",
            "downloads": Path.home() / "Downloads",
            "documentos": Path.home() / "Documentos",
            "documents": Path.home() / "Documents",
            "escritorio": Path.home() / "Escritorio",
            "desktop": Path.home() / "Desktop",
            "videos": Path.home() / "Videos",
            "imagenes": Path.home() / "Imágenes",
            "imágenes": Path.home() / "Imágenes",
            "musica": Path.home() / "Música",
            "música": Path.home() / "Música",
            "home": Path.home(),
            "inicio": Path.home(),
        }

        for key, base in base_map.items():
            if t == key:
                return str(base)

            if t.startswith(key + " "):
                # Mantener el resto más o menos como lo dijo el usuario.
                rest = raw.split(maxsplit=1)[1] if len(raw.split(maxsplit=1)) > 1 else ""
                return str(base / rest)

        return str(Path.home() / raw)

    def _row_to_item(self, row: tuple[Any, ...] | None) -> MemoryItem | None:
        if not row:
            return None

        return MemoryItem(
            key=row[0],
            value=row[1],
            type=row[2],
            source=row[3],
            note=row[4],
            created_at=float(row[5]),
            updated_at=float(row[6]),
        )

    def _clean_key(self, key: str) -> str:
        key = str(key or "").strip().lower()
        key = re.sub(r"\\s+", " ", key)
        return key

    def _clean_type(self, type: str) -> str:
        type = str(type or "generic").strip().lower()
        type = re.sub(r"[^a-z0-9_-]+", "_", type)
        return type or "generic"

    def _norm(self, text: str) -> str:
        text = str(text or "").strip().lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(c for c in text if not unicodedata.combining(c))
        text = re.sub(r"[^a-z0-9ñ\\s:/._-]+", " ", text)
        text = re.sub(r"\\s+", " ", text)
        return text.strip()
