from __future__ import annotations

from pathlib import Path
from typing import Any


def expand_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    return Path(str(value)).expanduser().resolve()


def ensure_dir(path: str | Path) -> Path:
    p = expand_path(path)
    assert p is not None
    p.mkdir(parents=True, exist_ok=True)
    return p


def deep_get(data: dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = data
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def home() -> Path:
    return Path.home()


def config_dir() -> Path:
    return ensure_dir('~/.config/jarvis')


def data_dir() -> Path:
    return ensure_dir('~/.local/share/jarvis')


def logs_dir() -> Path:
    return ensure_dir(data_dir() / 'logs')


def tmp_dir() -> Path:
    return ensure_dir(data_dir() / 'tmp')
