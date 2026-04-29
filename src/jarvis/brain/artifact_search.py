from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


BUILD_VARIANTS = {
    "build", "builds", "buil", "buils", "buid", "buidas",
    "buells", "buels", "boils", "boil", "boiled", "bools", "bool",
    "bills", "bilz", "biles", "builes", "bields", "bield",
    "bild", "bilds", "builts", "blinds",
}

AAB_VARIANTS = {
    "aab", ".aab", "a a b", "a a ve", "aave", "a ap", "a a p",
    "aap", "abb", "aav", "ab", "a abe", "a ab", "a b",
}

APK_VARIANTS = {
    "apk", ".apk", "a p k", "a pe ka", "a p ka", "ap k", "a pk",
}


def _entities(intent: Any) -> dict:
    ent = getattr(intent, "entities", None)
    return ent if isinstance(ent, dict) else {}


def clean_artifact_query(value: Any) -> str:
    q = str(value or "").strip().lower()
    q = q.strip(" .,:;!?¡¿\"'“”‘’`")
    q = re.sub(r"\s+", " ", q).strip()

    if q in AAB_VARIANTS:
        return "aab"
    if q in APK_VARIANTS:
        return "apk"

    q = re.sub(r"\ba\s+a\s+b\b", "aab", q)
    q = re.sub(r"\ba\s+a\s+p\b", "aab", q)
    q = re.sub(r"\ba\s+ap\b", "aab", q)
    q = re.sub(r"\ba\s*ap\b", "aab", q)
    q = re.sub(r"\ba\s*p\s*k\b", "apk", q)
    q = re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)

    q = re.sub(r"\s+", " ", q).strip()
    if q in AAB_VARIANTS:
        return "aab"
    if q in APK_VARIANTS:
        return "apk"
    return q


def _raw_text(intent: Any) -> str:
    ent = _entities(intent)
    return str(getattr(intent, "raw_text", "") or ent.get("raw_text", "") or getattr(intent, "text", "") or "")


def _text_mentions_builds(text: Any) -> bool:
    t = str(text or "").lower()
    words = set(re.findall(r"[a-záéíóúñ]+", t))
    return bool(words & BUILD_VARIANTS)


def _text_mentions_artifact(text: Any) -> str:
    t = str(text or "").lower()
    if any(v in t for v in AAB_VARIANTS):
        return "aab"
    if any(v in t for v in APK_VARIANTS):
        return "apk"
    # patterns with spaces
    if re.search(r"\ba\s+a\s+b\b|\ba\s+ap\b|\ba\s+a\s+p\b", t):
        return "aab"
    if re.search(r"\ba\s+p\s+k\b", t):
        return "apk"
    return ""


def can_handle_artifact_search(intent: Any) -> bool:
    if getattr(intent, "name", "") != "search_file":
        return False

    ent = _entities(intent)
    query = clean_artifact_query(ent.get("query") or ent.get("search_query") or "")
    raw_q = _text_mentions_artifact(_raw_text(intent))

    final_q = query if query in {"aab", "apk"} else raw_q
    if final_q not in {"aab", "apk"}:
        return False

    ent["query"] = final_q
    return True


def _label(path_value: Any) -> str:
    try:
        p = Path(str(path_value or "")).expanduser()
        return p.name or p.parent.name or str(p)
    except Exception:
        return str(path_value or "")


def _safe_open(path_value: Any) -> bool:
    try:
        p = Path(str(path_value or "")).expanduser()
        if not p.exists():
            return False
        subprocess.Popen(
            ["xdg-open", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def _skip_dir(dirname: str) -> bool:
    d = str(dirname or "").lower()
    if d in {
        ".git", ".hg", ".svn", "node_modules", ".gradle", ".cache", "cache",
        "__pycache__", ".trash", "trash", "tmp", "temp"
    }:
        return True
    return d.endswith(".cache")


def _score(path: Path, ext: str) -> int:
    s = str(path).lower()
    score = 0

    if path.suffix.lower() == ext:
        score += 100_000

    preferred = [
        "release", "production", "prod", "eas", "artifact", "artifacts",
        "android", "build", "dist", "playstore", "app"
    ]
    for i, term in enumerate(preferred):
        if term in s:
            score += 1000 - i * 20

    bad = [".cache", "node_modules", ".gradle/caches", "/cache/", "/tmp/", "/temp/", ".git"]
    for term in bad:
        if term in s:
            score -= 20_000

    try:
        score += int(path.stat().st_mtime // 1000)
    except Exception:
        pass

    return score


def _find_artifacts(base_path: Any, query: str, limit: int = 80) -> list[Path]:
    base = Path(str(base_path or "")).expanduser()
    if not base.exists():
        return []

    query = clean_artifact_query(query)
    ext = ".aab" if query == "aab" else ".apk" if query == "apk" else ""
    if not ext:
        return []

    found: dict[str, Path] = {}
    start = time.monotonic()

    try:
        for root, dirs, files in os.walk(str(base)):
            dirs[:] = [d for d in dirs if not _skip_dir(d)]

            if time.monotonic() - start > 20:
                break

            for filename in files:
                p = Path(root) / filename
                if p.suffix.lower() != ext:
                    continue
                if any(_skip_dir(part) for part in p.parts):
                    continue
                found[str(p)] = p
                if len(found) >= limit * 3:
                    break

            if len(found) >= limit * 3:
                break
    except Exception:
        return []

    ranked = sorted(found.values(), key=lambda p: (_score(p, ext), str(p).lower()), reverse=True)
    return ranked[:limit]


def _trunc(name: str, max_len: int = 52) -> str:
    s = str(name or "")
    if len(s) <= max_len:
        return s
    p = Path(s)
    suffix = p.suffix
    stem = p.stem
    keep = max(16, max_len - len(suffix) - 3)
    return stem[:keep] + "..." + suffix


def _save_context(base_path: Any, query: str, results: list[Path]) -> None:
    try:
        ctx_path = Path.home() / ".local/share/jarvis/context.json"
        ctx_path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if ctx_path.exists():
            try:
                data = json.loads(ctx_path.read_text(encoding="utf-8"))
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

        data["last_folder"] = str(Path(str(base_path)).expanduser())
        data["last_search_query"] = clean_artifact_query(query)
        data["last_search_results"] = items
        data["search_results"] = items
        data["last_results"] = items
        data["results"] = items

        ctx_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _maybe_recover_builds_alias(intent: Any, base_path: Any) -> str:
    ent = _entities(intent)
    raw = _raw_text(intent)

    try:
        base = Path(str(base_path or "")).expanduser()
    except Exception:
        base = Path.home()

    fallback_bases = {
        str(Path.home()),
        str(Path.home() / "Descargas"),
        str(Path.home() / "Downloads"),
    }

    # If STT said builds-ish and planner fell back to home/downloads, use learned alias.
    if str(base) in fallback_bases and _text_mentions_builds(raw):
        try:
            from jarvis.brain.event_journal import EventJournal
            alias_path = EventJournal().resolve_alias("builds")
            if alias_path:
                ent["path"] = alias_path
                ent["base_path"] = alias_path
                ent["open_base"] = True
                return alias_path
        except Exception:
            pass

    return str(base)


def execute_artifact_search(intent: Any) -> str:
    ent = _entities(intent)
    query = clean_artifact_query(ent.get("query") or ent.get("search_query") or _text_mentions_artifact(_raw_text(intent)))
    ent["query"] = query

    base_path = ent.get("base_path") or ent.get("path") or ent.get("folder") or str(Path.home())
    base_path = _maybe_recover_builds_alias(intent, base_path)

    base = Path(str(base_path)).expanduser()
    label = _label(base)

    open_base = bool(ent.get("open_base"))
    open_first = bool(ent.get("open_first"))
    open_index = int(ent.get("open_index") or 1)

    if open_base:
        _safe_open(base)

    results = _find_artifacts(base, query)
    _save_context(base, query, results)

    ext = f".{query}"
    prefix = f"Abrí {label}. " if open_base else ""

    if not results:
        return f"{prefix}No encontré archivos {ext} en {label}."

    idx = max(0, min(open_index - 1, len(results) - 1))
    first = results[idx]
    first_name = _trunc(first.name)

    if open_first:
        _safe_open(first)
        return f"{prefix}Encontré {len(results)} archivo(s) {ext} en {label}. Abriendo {first_name}."

    return f"{prefix}Encontré {len(results)} archivo(s) {ext} en {label}. El primero es {first_name}."
