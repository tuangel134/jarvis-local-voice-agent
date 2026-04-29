from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


class ContextStore:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.path = Path.home() / ".local/share/jarvis/context.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self, data: dict[str, Any]) -> None:
        data = dict(data or {})
        data["updated_at"] = time.time()
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self.save({})

    def set_last_folder(self, path: str, label: str = "") -> None:
        path = str(path or "").strip()
        if not path:
            return
        data = self.load()
        previous = data.get("last_folder")
        if previous and previous != path:
            data["previous_folder"] = previous
            data["previous_folder_label"] = data.get("last_folder_label", "")
        data["last_folder"] = path
        data["last_folder_label"] = label or Path(path).name
        data["last_action"] = "open_folder"
        data["last_entities"] = {"path": path, "target": label or Path(path).name}
        self.save(data)

    def get_last_folder(self) -> str:
        return str(self.load().get("last_folder", "") or "")

    def get_previous_folder(self) -> str:
        return str(self.load().get("previous_folder", "") or "")

    def set_last_file(self, path: str, label: str = "") -> None:
        path = str(path or "").strip()
        if not path:
            return
        data = self.load()
        data["last_file"] = path
        data["last_file_label"] = label or Path(path).name
        data["last_action"] = "open_file"
        data["last_entities"] = {"path": path, "target": label or Path(path).name}
        self.save(data)

    def get_last_file(self) -> str:
        return str(self.load().get("last_file", "") or "")

    def set_last_url(self, url: str, label: str = "") -> None:
        url = str(url or "").strip()
        if not url:
            return
        data = self.load()
        data["last_url"] = url
        data["last_url_label"] = label
        data["last_action"] = "open_url"
        data["last_entities"] = {"url": url, "target": label}
        self.save(data)

    def set_last_media(self, query: str, platform: str = "", pid: int | None = None) -> None:
        data = self.load()
        data["last_media"] = {"query": query, "platform": platform, "pid": pid}
        data["last_action"] = "play_music"
        data["last_entities"] = data["last_media"]
        self.save(data)

    def set_search_results(self, query: str, base_path: str, results: list[str]) -> None:
        clean_results = [str(r) for r in results if str(r).strip()]
        data = self.load()
        data["last_search"] = {
            "query": str(query or "").strip(),
            "base_path": str(base_path or "").strip(),
            "results": clean_results[:50],
            "count": len(clean_results),
            "created_at": time.time(),
        }
        data["last_action"] = "search_file"
        data["last_entities"] = {"query": query, "base_path": base_path, "count": len(clean_results)}
        self.save(data)

    def get_search_results(self) -> list[str]:
        search = self.load().get("last_search") or {}
        results = search.get("results") or []
        if not isinstance(results, list):
            return []
        return [str(r) for r in results if str(r).strip()]

    def get_search_result(self, index_1_based: int) -> str:
        results = self.get_search_results()
        try:
            idx = int(index_1_based) - 1
        except Exception:
            return ""
        if idx < 0 or idx >= len(results):
            return ""
        return results[idx]

    def describe_results(self, limit: int = 10) -> str:
        data = self.load()
        search = data.get("last_search") or {}
        results = self.get_search_results()
        if not results:
            return "No tengo resultados de búsqueda guardados."
        query = search.get("query", "")
        base = search.get("base_path", "")
        lines = []
        if query:
            lines.append(f"Última búsqueda: {query}")
        if base:
            lines.append(f"Buscado en: {base}")
        for i, result in enumerate(results[:limit], 1):
            p = Path(result)
            kind = "carpeta" if p.is_dir() else "archivo"
            lines.append(f"{i}. {p.name} ({kind}) — {result}")
        if len(results) > limit:
            lines.append(f"... y {len(results) - limit} resultado(s) más.")
        return "\n".join(lines)

    def describe(self) -> str:
        data = self.load()
        if not data:
            return "No hay contexto guardado."
        parts = []
        if data.get("last_folder"):
            parts.append(f"última carpeta: {data.get('last_folder')}")
        if data.get("previous_folder"):
            parts.append(f"carpeta anterior: {data.get('previous_folder')}")
        if data.get("last_file"):
            parts.append(f"último archivo: {data.get('last_file')}")
        if data.get("last_url"):
            parts.append(f"última URL: {data.get('last_url')}")
        search = data.get("last_search") or {}
        if search.get("query"):
            parts.append(f"última búsqueda: {search.get('query')} ({search.get('count', 0)} resultado(s))")
        media = data.get("last_media") or {}
        if media.get("query"):
            parts.append(f"última música: {media.get('query')} en {media.get('platform', '')}")
        if data.get("last_action"):
            parts.append(f"última acción: {data.get('last_action')}")
        if not parts:
            return "Hay contexto guardado, pero no contiene datos importantes."
        return "Contexto actual: " + "; ".join(parts)
