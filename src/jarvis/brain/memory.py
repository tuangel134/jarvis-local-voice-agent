from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jarvis.utils.paths import ensure_dir


class Memory:
    def __init__(self, path: str | Path = '~/.local/share/jarvis/memory.json'):
        self.path = Path(path).expanduser()
        ensure_dir(self.path.parent)
        if not self.path.exists():
            self.path.write_text('{}', encoding='utf-8')

    def get(self, key: str, default: Any = None) -> Any:
        return self.read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        data = self.read()
        data[key] = value
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            return {}
