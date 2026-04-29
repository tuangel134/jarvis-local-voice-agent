from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_model import Intent
from jarvis.skills.base import Skill


class DisplaySkill(Skill):
    name = 'display'
    description = 'Consulta y controla brillo, pantalla y monitores en Linux.'
    ACTIONS = (
        ActionSpec(
            name='status',
            namespace='display',
            description='Resume brillo y monitores activos.',
            intents=('display_status',),
            examples=('estado de pantalla', 'como esta la pantalla'),
            risk_level=RiskLevel.SAFE,
            backend='xrandr|brightnessctl',
        ),
        ActionSpec(
            name='list_monitors',
            namespace='display',
            description='Lista monitores conectados.',
            intents=('display_list_monitors',),
            examples=('lista monitores', 'que monitores hay'),
            risk_level=RiskLevel.SAFE,
            backend='xrandr --query',
        ),
        ActionSpec(
            name='brightness_up',
            namespace='display',
            description='Sube el brillo de la pantalla.',
            intents=('display_brightness_up',),
            examples=('sube brillo', 'mas brillo'),
            risk_level=RiskLevel.MODERATE,
            backend='brightnessctl set +10%|xbacklight -inc',
        ),
        ActionSpec(
            name='brightness_down',
            namespace='display',
            description='Baja el brillo de la pantalla.',
            intents=('display_brightness_down',),
            examples=('baja brillo', 'menos brillo'),
            risk_level=RiskLevel.MODERATE,
            backend='brightnessctl set 10%-|xbacklight -dec',
        ),
        ActionSpec(
            name='brightness_set',
            namespace='display',
            description='Ajusta el brillo a un porcentaje dado.',
            intents=('display_brightness_set',),
            examples=('brillo al 50', 'pon el brillo a 30'),
            risk_level=RiskLevel.MODERATE,
            backend='brightnessctl set 50%',
        ),
        ActionSpec(
            name='screen_off',
            namespace='display',
            description='Apaga o duerme la pantalla.',
            intents=('display_screen_off',),
            examples=('apaga la pantalla', 'duerme la pantalla'),
            risk_level=RiskLevel.MODERATE,
            backend='xset dpms force off',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='mirror',
            namespace='display',
            description='Duplica la pantalla principal en un monitor externo.',
            intents=('display_mirror',),
            examples=('duplica pantallas', 'modo espejo'),
            risk_level=RiskLevel.MODERATE,
            backend='xrandr --same-as',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='extend',
            namespace='display',
            description='Extiende el escritorio a un monitor externo.',
            intents=('display_extend',),
            examples=('extiende pantallas', 'usa monitor extendido'),
            risk_level=RiskLevel.MODERATE,
            backend='xrandr --right-of',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='external_only',
            namespace='display',
            description='Usa solo el monitor externo y apaga el interno.',
            intents=('display_external_only',),
            examples=('solo monitor externo', 'usa solo pantalla externa'),
            risk_level=RiskLevel.MODERATE,
            backend='xrandr --off',
            requires_confirmation=True,
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'display_status',
            'display_list_monitors',
            'display_brightness_up',
            'display_brightness_down',
            'display_brightness_set',
            'display_screen_off',
            'display_mirror',
            'display_extend',
            'display_external_only',
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'display_status':
            return self._status()
        if intent.name == 'display_list_monitors':
            return self._list_monitors()
        if intent.name == 'display_brightness_up':
            return self._brightness_delta(+10)
        if intent.name == 'display_brightness_down':
            return self._brightness_delta(-10)
        if intent.name == 'display_brightness_set':
            return self._brightness_set(entities.get('percent'))
        if intent.name == 'display_screen_off':
            return self._screen_off()
        if intent.name == 'display_mirror':
            return self._monitor_mode('mirror')
        if intent.name == 'display_extend':
            return self._monitor_mode('extend')
        if intent.name == 'display_external_only':
            return self._monitor_mode('external_only')
        return {'ok': False, 'error': f'Acción no soportada por display: {intent.name}'}

    def _status(self) -> dict[str, Any]:
        monitors = _list_monitors()
        brightness = _read_brightness_percent()
        if not monitors and brightness is None:
            return {'ok': False, 'error': 'No pude leer estado de pantalla ni monitores.'}
        monitor_names = ', '.join(item['name'] for item in monitors[:4]) if monitors else 'sin monitores detectados'
        bright_txt = 'desconocido' if brightness is None else f'{brightness}%'
        return {
            'ok': True,
            'message': f'Pantalla: brillo {bright_txt}, monitores {monitor_names}.',
            'brightness_percent': brightness,
            'monitors': monitors,
        }

    def _list_monitors(self) -> dict[str, Any]:
        monitors = _list_monitors()
        if not monitors:
            return {'ok': False, 'error': 'No detecté monitores con los backends disponibles.'}
        preview = ', '.join(item['name'] for item in monitors[:6])
        return {'ok': True, 'message': f'Monitores detectados: {preview}.', 'monitors': monitors}

    def _brightness_delta(self, delta: int) -> dict[str, Any]:
        if _brightnessctl_delta(delta) or _xbacklight_delta(delta):
            new_pct = _read_brightness_percent()
            pct_txt = 'desconocido' if new_pct is None else f'{new_pct}%'
            return {'ok': True, 'message': f'Brillo ajustado. Valor actual {pct_txt}.', 'brightness_percent': new_pct}
        return {'ok': False, 'error': 'No pude ajustar el brillo. Necesito brightnessctl o xbacklight.'}

    def _brightness_set(self, percent: Any) -> dict[str, Any]:
        try:
            value = int(percent)
        except Exception:
            return {'ok': False, 'error': 'Necesito un porcentaje de brillo válido.'}
        value = max(1, min(100, value))
        if _brightnessctl_set(value) or _xbacklight_set(value):
            return {'ok': True, 'message': f'Brillo al {value} por ciento.', 'brightness_percent': value}
        return {'ok': False, 'error': 'No pude fijar el brillo con los backends disponibles.'}

    def _screen_off(self) -> dict[str, Any]:
        xset = shutil.which('xset')
        if xset:
            try:
                proc = subprocess.run([xset, 'dpms', 'force', 'off'], capture_output=True, text=True, timeout=6, check=False)
                if proc.returncode == 0:
                    return {'ok': True, 'message': 'Apagando la pantalla.'}
            except Exception:
                pass
        return {'ok': False, 'error': 'No pude apagar la pantalla. Necesito xset.'}

    def _monitor_mode(self, mode: str) -> dict[str, Any]:
        pair = _choose_monitor_pair()
        if not pair:
            return {'ok': False, 'error': 'Necesito al menos un monitor interno y uno externo para cambiar el modo.'}
        internal, external = pair
        xrandr = shutil.which('xrandr')
        if not xrandr:
            return {'ok': False, 'error': 'No puedo cambiar el modo de monitores sin xrandr.'}
        if mode == 'mirror':
            cmd = [xrandr, '--output', external, '--auto', '--same-as', internal]
            success = 'Modo espejo activado.'
        elif mode == 'extend':
            cmd = [xrandr, '--output', external, '--auto', '--right-of', internal]
            success = 'Modo extendido activado.'
        elif mode == 'external_only':
            cmd = [xrandr, '--output', external, '--auto', '--output', internal, '--off']
            success = 'Usando solo el monitor externo.'
        else:
            return {'ok': False, 'error': f'Modo de monitor no soportado: {mode}'}
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': success, 'internal': internal, 'external': external}
            err = (proc.stderr or proc.stdout or 'xrandr devolvió error').strip()
            return {'ok': False, 'error': err}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude cambiar el modo de monitor: {exc}'}



def _run(cmd: list[str], timeout: float = 6.0) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode == 0:
            out = (proc.stdout or '').strip()
            return out or None
    except Exception:
        return None
    return None


def _list_monitors() -> list[dict[str, Any]]:
    xrandr = shutil.which('xrandr')
    if not xrandr:
        return []
    raw = _run([xrandr, '--query'], timeout=8)
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if ' connected' not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        name = parts[0].strip()
        primary = ' primary ' in f' {line} '
        internal = name.startswith(('eDP', 'LVDS', 'DSI'))
        result.append({'name': name, 'primary': primary, 'internal': internal, 'backend': 'xrandr'})
    return result


def _choose_monitor_pair() -> tuple[str, str] | None:
    monitors = _list_monitors()
    internal = None
    external = None
    for item in monitors:
        if item.get('internal') and internal is None:
            internal = item['name']
        if not item.get('internal') and external is None:
            external = item['name']
    if internal and external:
        return internal, external
    return None


def _read_brightness_percent() -> int | None:
    brightnessctl = shutil.which('brightnessctl')
    if brightnessctl:
        raw = _run([brightnessctl, '-m'], timeout=6)
        if raw:
            try:
                parts = raw.split(',')
                pct = parts[3].strip().rstrip('%')
                return int(float(pct))
            except Exception:
                pass
    xbacklight = shutil.which('xbacklight')
    if xbacklight:
        raw = _run([xbacklight, '-get'], timeout=6)
        if raw:
            try:
                return int(round(float(raw.strip())))
            except Exception:
                pass
    return None


def _brightnessctl_delta(delta: int) -> bool:
    brightnessctl = shutil.which('brightnessctl')
    if not brightnessctl:
        return False
    arg = f'{abs(delta)}%+'
    if delta < 0:
        arg = f'{abs(delta)}%-'
    try:
        proc = subprocess.run([brightnessctl, 'set', arg], capture_output=True, text=True, timeout=6, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def _brightnessctl_set(value: int) -> bool:
    brightnessctl = shutil.which('brightnessctl')
    if not brightnessctl:
        return False
    try:
        proc = subprocess.run([brightnessctl, 'set', f'{value}%'], capture_output=True, text=True, timeout=6, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def _xbacklight_delta(delta: int) -> bool:
    xbacklight = shutil.which('xbacklight')
    if not xbacklight:
        return False
    cmd = [xbacklight, '-inc' if delta > 0 else '-dec', str(abs(delta))]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def _xbacklight_set(value: int) -> bool:
    xbacklight = shutil.which('xbacklight')
    if not xbacklight:
        return False
    try:
        proc = subprocess.run([xbacklight, '-set', str(value)], capture_output=True, text=True, timeout=6, check=False)
        return proc.returncode == 0
    except Exception:
        return False
