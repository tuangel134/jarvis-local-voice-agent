from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any

from jarvis.brain.action_schema import SemanticAction
from jarvis.brain.intent_model import Intent


class ActionValidator:
    """
    Convierte SemanticAction -> Intent clásico compatible con el executor actual.

    Aquí se valida seguridad básica:
    - acciones permitidas
    - URLs permitidas por prefijo/dominio
    - apps permitidas por allowlist
    - folders limitados al HOME salvo mapeos conocidos
    - shell peligroso bloqueado
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config or {}

    def to_intent(self, action: SemanticAction, raw_text: str = "") -> Intent:
        act = action.normalized_action()
        confidence = float(action.confidence or 0.0)
        raw = raw_text or action.text or ""

        if confidence < self._threshold() and act not in {"chat", "unknown"}:
            return Intent("chat", 0.45, {"text": raw, "reason": "low_confidence"}, raw)

        if act == "play_music":
            return self._play_music_to_intent(action, raw)

        if act in {"stop_music", "pause_music", "resume_music"}:
            return Intent(act, confidence, {}, raw)

        if act == "open_url":
            url = self._resolve_url(action)
            if not url:
                return Intent("chat", 0.40, {"text": raw, "reason": "url_not_resolved"}, raw)

            if not self._is_url_allowed(url):
                return Intent("chat", 0.40, {"text": raw, "reason": f"url_not_allowed:{url}"}, raw)

            return Intent(
                "open_url",
                confidence,
                {
                    "url": url,
                    "target": action.url_name or action.url or action.text,
                    "platform": action.platform,
                    "query": action.query,
                },
                raw,
            )

        if act == "open_app":
            app = self._resolve_app(action.app_name or action.text or action.query)
            if not app:
                return Intent("chat", 0.40, {"text": raw, "reason": "app_not_resolved"}, raw)

            if not self._is_app_allowed(app):
                return Intent("chat", 0.40, {"text": raw, "reason": f"app_not_allowed:{app}"}, raw)

            return Intent("open_app", confidence, {"app": app, "target": action.app_name}, raw)

        # v27_server_validator: prioridad absoluta para carpetas Servidor1/Servidor2.
        raw_l = (raw or "").lower()
        action_text_l = (getattr(action, "text", "") or "").lower()
        folder_l = (getattr(action, "folder", "") or "").lower()
        path_l = (getattr(action, "path", "") or "").lower()
        joined_l = " ".join([raw_l, action_text_l, folder_l, path_l]).replace("  ", " ")
        compact_l = joined_l.replace(" ", "")

        if (
            "servidor 1" in joined_l
            or "servidor1" in compact_l
            or "serobidor 1" in joined_l
            or "serobidor1" in compact_l
            or "server 1" in joined_l
            or "server1" in compact_l
        ):
            return Intent("open_folder", confidence, {"path": "/home/angel/Escritorio/Servidor1", "target": "Servidor1"}, raw)

        if (
            "servidor 2" in joined_l
            or "servidor2" in compact_l
            or "serobidor 2" in joined_l
            or "serobidor2" in compact_l
            or "server 2" in joined_l
            or "server2" in compact_l
        ):
            return Intent("open_folder", confidence, {"path": "/home/angel/Escritorio/Servidor2", "target": "Servidor2"}, raw)

        if act == "open_folder":
            folder = self._resolve_folder(action.path or action.folder or action.text)
            if not folder:
                return Intent("chat", 0.40, {"text": raw, "reason": "folder_not_resolved"}, raw)

            return Intent("open_folder", confidence, {"path": str(folder), "target": action.folder or action.path}, raw)

        if act in {"get_time", "get_date", "system_status"}:
            return Intent(act, confidence, {}, raw)

        if act == "service_status":
            service = self._resolve_service(action.service or action.text)
            return Intent("service_status", confidence, {"service": service}, raw)

        if act == "create_note":
            content = action.note or action.text or raw
            return Intent("create_note", confidence, {"content": content, "text": content}, raw)

        if act == "read_note":
            return Intent("read_note", confidence, {}, raw)

        if act == "open_file":
            path = action.path or action.url or action.text or raw
            return Intent("open_file", confidence, {"path": path, "target": action.folder or action.note or path}, raw)

        if act == "search_file":
            query = action.search_query or action.query or action.text or raw
            entities = {"query": query}
            if action.path:
                entities["path"] = action.path
            if action.command in {"open_first_result", "open_result_1"}:
                entities["auto_open_index"] = 1
            return Intent("search_file", confidence, entities, raw)

        if act == "create_reminder":
            text = action.text or action.note or raw
            return Intent("create_reminder", confidence, {"text": text}, raw)

        if act == "list_reminders":
            return Intent("list_reminders", confidence, {}, raw)

        if act == "safe_shell":
            command = action.command or raw
            if self._is_dangerous_command(command):
                return Intent("chat", 0.30, {"text": raw, "reason": "dangerous_command_blocked"}, raw)
            return Intent("safe_shell", confidence, {"command": command}, raw)

        if act == "heavy_reasoning":
            return Intent("heavy_reasoning", confidence, {"text": action.text or raw}, raw)

        if act == "chat":
            return Intent("chat", confidence or 0.6, {"text": action.text or raw}, raw)

        return Intent("unknown", confidence, {"text": raw}, raw)

    def _threshold(self) -> float:
        return float(self.config.get("brain", {}).get("confidence_threshold", 0.62))

    def _play_music_to_intent(self, action: SemanticAction, raw: str) -> Intent:
        query = action.query or action.text or raw
        platform = (action.platform or "youtube_music").strip().lower().replace(" ", "_")

        if platform in {"youtube", "yt", "you_tube", "yutube"}:
            url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
            target = "youtube"
        elif platform in {"tidal"}:
            url = "https://tidal.com/search?q=" + urllib.parse.quote_plus(query)
            target = "tidal"
        elif platform in {"spotify"}:
            url = "https://open.spotify.com/search/" + urllib.parse.quote_plus(query)
            target = "spotify"
        else:
            url = "https://music.youtube.com/search?q=" + urllib.parse.quote_plus(query)
            target = "youtube music"
            platform = "youtube_music"

        return Intent(
            "open_url",
            action.confidence,
            {
                "url": url,
                "target": target,
                "query": query,
                "platform": platform,
                "autoplay": True,
            },
            raw,
        )

    def _resolve_url(self, action: SemanticAction) -> str | None:
        url = (action.url or "").strip()

        if url:
            if re.match(r"^[\\w.-]+\\.[a-z]{2,}(/.*)?$", url) and not url.startswith(("http://", "https://")):
                url = "https://" + url
            return url

        name = (action.url_name or action.text or "").strip().lower()
        aliases = self.config.get("security", {}).get("url_aliases", {}) or {}

        # Mapeos críticos primero. Esto evita que "google play console"
        # caiga en "google" normal.
        critical = {
            "google play console": "https://play.google.com/console",
            "play console": "https://play.google.com/console",
            "consola de google play": "https://play.google.com/console",
            "consola play": "https://play.google.com/console",
            "panel de apps": "https://play.google.com/console",
            "firebase": "https://console.firebase.google.com",
            "revenuecat": "https://app.revenuecat.com",
            "expo": "https://expo.dev",
            "groq": "https://console.groq.com",
            "youtube music": "https://music.youtube.com",
            "youtube": "https://www.youtube.com",
            "tidal": "https://tidal.com",
            "spotify": "https://open.spotify.com",
            "chatgpt": "https://chatgpt.com",
            "github": "https://github.com",
            "hugging face": "https://huggingface.co",
            "huggingface": "https://huggingface.co",
            "gmail": "https://mail.google.com",
            "drive": "https://drive.google.com",
            "calendar": "https://calendar.google.com",
            "whatsapp": "https://web.whatsapp.com",
            "telegram": "https://web.telegram.org",
            "google": "https://www.google.com",
        }

        # 1. Coincidencia exacta crítica.
        if name in critical:
            return critical[name]

        # 2. Coincidencia crítica por frase, priorizando frases largas.
        for key in sorted(critical.keys(), key=len, reverse=True):
            if key in name:
                return critical[key]

        # 3. Alias exactos de config.
        for alias, value in aliases.items():
            alias_l = str(alias).strip().lower()
            if alias_l == name:
                return str(value)

        # 4. Alias parciales de config, priorizando alias largos.
        for alias, value in sorted(aliases.items(), key=lambda kv: len(str(kv[0])), reverse=True):
            alias_l = str(alias).strip().lower()
            if alias_l and (alias_l in name or name in alias_l):
                return str(value)

        return None


    def _is_url_allowed(self, url: str) -> bool:
        allowed = self.config.get("security", {}).get("allowed_urls", []) or []
        if not allowed:
            return True

        for base in allowed:
            base = str(base).rstrip("/")
            if url.startswith(base):
                return True

        # Permitir subrutas de dominios comunes aunque allowed_urls tenga dominio base.
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()

        for base in allowed:
            parsed_base = urllib.parse.urlparse(str(base))
            base_host = parsed_base.netloc.lower()
            if host and base_host and host == base_host:
                return True

        return False

    def _resolve_app(self, name: str) -> str | None:
        text = str(name or "").strip().lower()
        aliases = self.config.get("security", {}).get("app_aliases", {}) or {}

        if isinstance(aliases, dict):
            for alias, target in aliases.items():
                alias_l = str(alias).lower()

                if isinstance(target, str):
                    if alias_l in text or text in alias_l:
                        return target

                if isinstance(target, list):
                    app = str(alias)
                    for item in target:
                        item_l = str(item).lower()
                        if item_l in text or text in item_l:
                            return app

        common = {
            "calculadora": "gnome-calculator",
            "calculator": "gnome-calculator",
            "terminal": "gnome-terminal",
            "consola": "gnome-terminal",
            "archivos": "nautilus",
            "explorador": "nautilus",
            "carpetas": "nautilus",
            "vscode": "code",
            "visual studio code": "code",
            "cursor": "cursor",
            "vlc": "vlc",
            "monitor del sistema": "gnome-system-monitor",
            "obs": "obs",
            "discord": "discord",
            "telegram": "telegram-desktop",
            "spotify": "spotify",
            "steam": "steam",
            "gimp": "gimp",
            "blender": "blender",
            "libreoffice": "libreoffice",
        }

        for key, app in common.items():
            if key in text:
                return app

        return text if text else None

    def _is_app_allowed(self, app: str) -> bool:
        allowed = self.config.get("security", {}).get("allowed_apps", []) or []
        return app in allowed

    def _resolve_folder(self, folder: str) -> Path | None:
        text = str(folder or "").strip()
        t = text.lower()
        compact = re.sub(r"\s+", "", t)

        # PRIORIDAD ABSOLUTA: carpetas físicas Servidor1/Servidor2.
        # Esto evita que "abre la carpeta del servidor 1" acabe abriendo solo ~/Escritorio.
        if (
            "servidor 1" in t
            or "servidor1" in compact
            or "server 1" in t
            or "server1" in compact
            or "servidor uno" in t
        ):
            return Path("/home/angel/Escritorio/Servidor1").expanduser()

        if (
            "servidor 2" in t
            or "servidor2" in compact
            or "server 2" in t
            or "server2" in compact
            or "servidor dos" in t
        ):
            return Path("/home/angel/Escritorio/Servidor2").expanduser()

        # Si viene path directo desde memoria o SemanticAction.path, usarlo tal cual.
        if text.startswith("~/") or text.startswith("/"):
            p = Path(text).expanduser()
            try:
                home = Path.home().resolve()
                resolved = p.resolve()
                if resolved == home or home in resolved.parents:
                    return resolved
            except Exception:
                return p

        mapping = {
            "descargas": "~/Descargas",
            "download": "~/Descargas",
            "downloads": "~/Descargas",
            "documentos": "~/Documentos",
            "documents": "~/Documentos",
            "escritorio": "~/Escritorio",
            "desktop": "~/Escritorio",
            "videos": "~/Videos",
            "imagenes": "~/Imágenes",
            "imágenes": "~/Imágenes",
            "musica": "~/Música",
            "música": "~/Música",
            "home": "~",
            "inicio": "~",
            "carpeta personal": "~",

            "build": "~/Descargas/Apps playstore",
            "builds": "~/Descargas/Apps playstore",
            "buil": "~/Descargas/Apps playstore",
            "buyos": "~/Descargas/Apps playstore",
            "buidos": "~/Descargas/Apps playstore",
        }

        for key, path in mapping.items():
            if key in t:
                return Path(path).expanduser()

        return None


    def _resolve_service(self, service: str) -> str:
        text = str(service or "").strip().lower()
        aliases = self.config.get("security", {}).get("service_aliases", {}) or {}

        for alias, target in aliases.items():
            if str(alias).lower() in text:
                return str(target)

        if "pelicula" in text or "películas" in text or "peliculas" in text or "jellyfin" in text:
            return "jellyfin"
        if "fotos" in text or "immich" in text:
            return "immich"
        if "docker" in text:
            return "docker"
        if "ssh" in text:
            return "ssh"

        return text.split()[0] if text else "unknown"

    def _is_dangerous_command(self, command: str) -> bool:
        text = str(command or "").lower()
        patterns = self.config.get("security", {}).get("dangerous_patterns", []) or []

        for pattern in patterns:
            if str(pattern).lower() in text:
                return True

        extra = ["rm -rf", "sudo", "mkfs", "dd if=", "shutdown", "reboot", "chmod -r 777", ":(){", "/etc/", "/boot/", "/usr/"]
        return any(x in text for x in extra)

# ---------------------------------------------------------------------------
# v3.4.14 compatibility: normalize dictated artifact queries early
# ---------------------------------------------------------------------------
try:
    import re as _jv3414_re

    def _jv3414_clean_artifact_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        aab_variants = {
            "aab", ".aab",
            "a a b", "a a ve", "aave",
            "a ap", "a a p", "aap",
            "a ab", "a abe", "a b",
            "abb", "aav", "ab",
        }
        apk_variants = {
            "apk", ".apk",
            "a p k", "a pe ka", "a p ka", "ap k", "a pk",
        }

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        q = _jv3414_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+a\s+p\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ab\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*p\s*k\b", "apk", q)
        q = _jv3414_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        return q

    def _jv3414_clean_mapping(obj):
        if not isinstance(obj, dict):
            return obj
        for key in ("query", "search_query"):
            if key in obj:
                obj[key] = _jv3414_clean_artifact_query(obj.get(key))
        if isinstance(obj.get("params"), dict):
            _jv3414_clean_mapping(obj["params"])
        if isinstance(obj.get("entities"), dict):
            _jv3414_clean_mapping(obj["entities"])
        return obj

    def _jv3414_clean_any(obj):
        if obj is None:
            return obj

        if isinstance(obj, list):
            for i, item in enumerate(obj):
                obj[i] = _jv3414_clean_any(item)
            return obj

        if isinstance(obj, tuple):
            return tuple(_jv3414_clean_any(x) for x in obj)

        if isinstance(obj, dict):
            return _jv3414_clean_mapping(obj)

        # dataclass / normal objects used by Jarvis: Intent, SemanticAction, Plan, etc.
        for attr in ("query", "search_query"):
            if hasattr(obj, attr):
                try:
                    setattr(obj, attr, _jv3414_clean_artifact_query(getattr(obj, attr)))
                except Exception:
                    pass

        for attr in ("params", "entities"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, dict):
                        _jv3414_clean_mapping(val)
                except Exception:
                    pass

        for attr in ("steps", "planner_steps"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, list):
                        setattr(obj, attr, _jv3414_clean_any(val))
                except Exception:
                    pass

        return obj
except Exception:
    pass

try:
    if "ActionValidator" in globals() and not getattr(ActionValidator, "_jv3414_wrapped", False):
        for _name, _value in list(ActionValidator.__dict__.items()):
            if _name.startswith("__") or not callable(_value) or getattr(_value, "_jv3414_wrapped", False):
                continue

            def _jv3414_make_wrapper(orig):
                def _wrapped(self, *args, **kwargs):
                    return _jv3414_clean_any(orig(self, *args, **kwargs))
                _wrapped._jv3414_wrapped = True
                return _wrapped

            try:
                setattr(ActionValidator, _name, _jv3414_make_wrapper(_value))
            except Exception:
                pass

        ActionValidator._jv3414_wrapped = True
except Exception:
    pass

