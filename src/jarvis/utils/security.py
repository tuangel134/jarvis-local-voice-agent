from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

from jarvis.utils.text import normalize


class SecurityDecision:
    def __init__(self, allowed: bool, reason: str = '', sanitized: list[str] | None = None):
        self.allowed = allowed
        self.reason = reason
        self.sanitized = sanitized or []

    def __bool__(self) -> bool:
        return self.allowed


def is_url_allowed(url: str, config: dict[str, Any]) -> bool:
    allowed = config.get('security', {}).get('allowed_urls', [])
    if not allowed:
        return True
    return any(url.startswith(x) for x in allowed) or url.startswith('http://localhost') or url.startswith('https://localhost')


def is_path_under_home(path: str | Path) -> bool:
    try:
        p = Path(path).expanduser().resolve()
        home = Path.home().resolve()
        return p == home or home in p.parents
    except Exception:
        return False


def command_contains_danger(command: str, config: dict[str, Any]) -> str | None:
    n = normalize(command)
    for pattern in config.get('security', {}).get('dangerous_patterns', []):
        if normalize(pattern) in n:
            return pattern
    suspicious_regexes = [
        r'\brm\s+(-[a-zA-Z]*r[a-zA-Z]*f|-rf|-fr)\b',
        r'\bsudo\b',
        r'\bdd\s+',
        r'\bmkfs\b',
        r'\bshutdown\b',
        r'\breboot\b',
        r':\s*\(\s*\)\s*\{',
        r'\|\s*(sh|bash)\b',
        r'>\s*/dev/sd[a-z]',
    ]
    for rx in suspicious_regexes:
        if re.search(rx, command, flags=re.IGNORECASE):
            return rx
    return None


def validate_shell_command(command: str, config: dict[str, Any]) -> SecurityDecision:
    command = command.strip()
    if not command:
        return SecurityDecision(False, 'Comando vacío.')
    if not config.get('security', {}).get('allow_shell_commands', True):
        return SecurityDecision(False, 'La ejecución de comandos está desactivada en config.yaml.')
    danger = command_contains_danger(command, config)
    if danger:
        return SecurityDecision(False, f'Patrón peligroso detectado: {danger}')
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return SecurityDecision(False, f'Comando mal formado: {exc}')
    if not parts:
        return SecurityDecision(False, 'Comando vacío.')
    allowed = set(config.get('security', {}).get('allowed_shell_commands', []))
    binary = Path(parts[0]).name
    if binary not in allowed:
        return SecurityDecision(False, f'Comando no permitido: {binary}')

    # Reglas extra por comando.
    if binary == 'systemctl':
        if len(parts) < 3 or parts[1] not in {'is-active', 'status'}:
            return SecurityDecision(False, 'Solo se permite systemctl is-active/status SERVICIO.')
    if binary == 'xdg-open':
        if len(parts) != 2:
            return SecurityDecision(False, 'xdg-open requiere una sola ruta o URL.')
        target = parts[1]
        if target.startswith(('http://', 'https://')):
            if not is_url_allowed(target, config):
                return SecurityDecision(False, 'URL no permitida por allowlist.')
        elif not is_path_under_home(target):
            return SecurityDecision(False, 'Solo se permiten rutas dentro de tu HOME.')
    if binary == 'find':
        if len(parts) < 2 or not is_path_under_home(parts[1]):
            return SecurityDecision(False, 'find solo se permite dentro de tu HOME.')
    if binary == 'cat':
        if len(parts) != 2 or not is_path_under_home(parts[1]):
            return SecurityDecision(False, 'cat solo se permite para un archivo dentro de tu HOME.')
    return SecurityDecision(True, 'Permitido.', parts)


def app_allowed(app: str, config: dict[str, Any]) -> bool:
    allowed = set(config.get('security', {}).get('allowed_apps', []))
    return Path(app).name in allowed
