from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jarvis.utils.paths import ensure_dir


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


class JarvisState:
    def __init__(self, path: str | Path = '~/.local/share/jarvis/state.json'):
        self.path = Path(path).expanduser()
        ensure_dir(self.path.parent)
        if not self.path.exists():
            self.write({'enabled': False, 'pid': None, 'last_enabled_at': None, 'last_disabled_at': None})

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            return {'enabled': False, 'pid': None, 'last_enabled_at': None, 'last_disabled_at': None}

    def write(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.path)

    def set_enabled(self, enabled: bool) -> None:
        data = self.read()
        data['enabled'] = bool(enabled)
        if enabled:
            data['last_enabled_at'] = now_iso()
        else:
            data['last_disabled_at'] = now_iso()
        self.write(data)

    def is_enabled(self) -> bool:
        return bool(self.read().get('enabled'))

    def set_pid(self, pid: int | None = None) -> None:
        data = self.read()
        data['pid'] = int(pid or os.getpid())
        self.write(data)
