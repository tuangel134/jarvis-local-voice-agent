
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.security import app_allowed
from jarvis.utils.text import normalize


class AppsSkill(Skill):
    name = "apps"
    description = "Abre, cierra, enfoca y lista aplicaciones Linux permitidas."
    ACTIONS = (
        ActionSpec(
            name="open",
            namespace="apps",
            description="Abre una aplicación permitida mediante alias o binario permitido.",
            intents=("open_app",),
            examples=("abre firefox", "abre telegram", "abre vscode"),
            risk_level=RiskLevel.SAFE,
            backend="shutil.which + subprocess.Popen",
        ),
        ActionSpec(
            name="close",
            namespace="apps",
            description="Cierra una aplicación visible o termina su proceso con fallback seguro.",
            intents=("close_app",),
            examples=("cierra telegram", "cierra firefox"),
            risk_level=RiskLevel.MODERATE,
            backend="wmctrl/xdotool/pkill",
            requires_confirmation=True,
        ),
        ActionSpec(
            name="focus",
            namespace="apps",
            description="Enfoca una ventana ya abierta si el entorno lo permite.",
            intents=("focus_app",),
            examples=("enfoca telegram", "cambia a firefox"),
            risk_level=RiskLevel.SAFE,
            backend="wmctrl/xdotool",
        ),
        ActionSpec(
            name="list_open",
            namespace="apps",
            description="Lista aplicaciones o ventanas visibles actualmente.",
            intents=("list_apps",),
            examples=("qué apps están abiertas", "lista aplicaciones abiertas"),
            risk_level=RiskLevel.SAFE,
            backend="wmctrl/ps",
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {"open_app", "close_app", "focus_app", "list_apps"}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == "list_apps":
            names = self._list_open_apps()
            if not names:
                return {"ok": False, "error": "No pude listar aplicaciones abiertas."}
            return {"ok": True, "message": "Aplicaciones abiertas: " + ", ".join(names[:12]) + ".", "apps": names}

        requested = normalize(str(entities.get("app", "")))
        if not requested:
            return {"ok": False, "error": "No detecté qué aplicación usar."}

        candidates = self._candidate_apps(requested)
        if intent.name == "open_app":
            return self._open_candidates(candidates)
        if intent.name == "close_app":
            return self._close_candidates(candidates)
        if intent.name == "focus_app":
            return self._focus_candidates(candidates)
        return {"ok": False, "error": f"Acción no soportada por apps: {intent.name}"}

    def _open_candidates(self, candidates: list[str]) -> dict[str, Any]:
        blocked: list[str] = []
        missing: list[str] = []
        for app in candidates:
            app = app.strip()
            if not app:
                continue
            if not app_allowed(app, self.config):
                blocked.append(app)
                continue
            binary = shutil.which(app)
            if not binary:
                missing.append(app)
                continue
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "message": f"Abriendo {app}."}
        if blocked and not missing:
            return {"ok": False, "error": f"La aplicación no está en la lista permitida: {', '.join(blocked[:5])}."}
        if missing:
            return {"ok": False, "error": f"No encontré instalada ninguna opción: {', '.join(missing[:6])}."}
        return {"ok": False, "error": "No pude abrir esa aplicación."}

    def _close_candidates(self, candidates: list[str]) -> dict[str, Any]:
        blocked: list[str] = []
        tried: list[str] = []
        for app in candidates:
            app = app.strip()
            if not app:
                continue
            if not app_allowed(app, self.config):
                blocked.append(app)
                continue
            tried.append(app)
            if self._wmctrl_close(app) or self._pkill_app(app):
                return {"ok": True, "message": f"Cerrando {app}."}
        if blocked and not tried:
            return {"ok": False, "error": f"No puedo cerrar una app fuera de la lista permitida: {', '.join(blocked[:5])}."}
        return {"ok": False, "error": f"No encontré una ventana o proceso activo para: {', '.join(tried[:5]) or 'esa aplicación'}."}

    def _focus_candidates(self, candidates: list[str]) -> dict[str, Any]:
        blocked: list[str] = []
        tried: list[str] = []
        for app in candidates:
            app = app.strip()
            if not app:
                continue
            if not app_allowed(app, self.config):
                blocked.append(app)
                continue
            tried.append(app)
            if self._wmctrl_focus(app) or self._xdotool_focus(app):
                return {"ok": True, "message": f"Enfocando {app}."}
        if blocked and not tried:
            return {"ok": False, "error": f"No puedo enfocar una app fuera de la lista permitida: {', '.join(blocked[:5])}."}
        return {"ok": False, "error": f"No encontré una ventana visible para: {', '.join(tried[:5]) or 'esa aplicación'}."}

    def _candidate_apps(self, requested: str) -> list[str]:
        aliases_raw = self.config.get("security", {}).get("app_aliases", {}) or {}
        aliases = {normalize(str(k)): v for k, v in aliases_raw.items()}
        value = aliases.get(requested)
        if value is None:
            for key, val in aliases.items():
                if key and key in requested:
                    value = val
                    break
        if value is None:
            value = requested

        if isinstance(value, list):
            items = [str(x) for x in value]
        else:
            value = str(value)
            items = [x.strip() for x in value.split("|") if x.strip()] if "|" in value else [value]

        out: list[str] = []
        for item in items:
            item = str(item).strip()
            if not item:
                continue
            tokens = [tok for tok in item.split() if tok]
            if tokens:
                out.append(tokens[0])
            out.append(item)
        seen: set[str] = set()
        deduped: list[str] = []
        for item in out:
            key = item.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped or [requested]

    def _list_open_apps(self) -> list[str]:
        wmctrl = shutil.which("wmctrl")
        if wmctrl:
            try:
                proc = subprocess.run([wmctrl, "-lx"], capture_output=True, text=True, timeout=3, check=False)
                if proc.returncode == 0:
                    names: list[str] = []
                    for line in (proc.stdout or "").splitlines():
                        parts = line.split(None, 4)
                        if len(parts) >= 5:
                            klass = parts[3].split(".")[-1]
                            title = parts[4].strip()
                            label = klass or title
                            if title and title.lower() != klass.lower():
                                label = f"{klass} ({title[:40]})" if klass else title[:40]
                            names.append(label)
                    if names:
                        return names
            except Exception:
                pass
        try:
            proc = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True, timeout=3, check=False)
            if proc.returncode == 0:
                names = []
                seen: set[str] = set()
                for line in (proc.stdout or "").splitlines():
                    item = line.strip()
                    if not item or item.startswith("["):
                        continue
                    if item not in seen:
                        seen.add(item)
                        names.append(item)
                if names:
                    return names[:20]
        except Exception:
            pass
        return []

    def _wmctrl_focus(self, app: str) -> bool:
        wmctrl = shutil.which("wmctrl")
        if not wmctrl:
            return False
        for args in ([wmctrl, "-xa", app], [wmctrl, "-Fa", app]):
            try:
                proc = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
                if proc.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    def _xdotool_focus(self, app: str) -> bool:
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return False
        patterns = [app, app.replace("-", " "), app.title()]
        for pattern in patterns:
            try:
                proc = subprocess.run([xdotool, "search", "--onlyvisible", "--name", pattern], capture_output=True, text=True, timeout=2, check=False)
                ids = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
                if not ids:
                    continue
                activate = subprocess.run([xdotool, "windowactivate", ids[0]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
                if activate.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    def _wmctrl_close(self, app: str) -> bool:
        wmctrl = shutil.which("wmctrl")
        if not wmctrl:
            return False
        try:
            proc = subprocess.run([wmctrl, "-lx"], capture_output=True, text=True, timeout=3, check=False)
            if proc.returncode != 0:
                return False
            for line in (proc.stdout or "").splitlines():
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue
                window_id, _desktop, _host, klass, title = parts
                hay = f"{klass} {title}".lower()
                if app.lower() not in hay:
                    continue
                close_proc = subprocess.run([wmctrl, "-ic", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
                if close_proc.returncode == 0:
                    return True
        except Exception:
            return False
        return False

    def _pkill_app(self, app: str) -> bool:
        pkill = shutil.which("pkill")
        if not pkill:
            return False
        patterns = [app, app.split()[0], app.replace("-", " ")]
        for pattern in patterns:
            pattern = pattern.strip()
            if not pattern:
                continue
            try:
                proc = subprocess.run([pkill, "-f", pattern], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
                if proc.returncode == 0:
                    return True
            except Exception:
                pass
        return False
