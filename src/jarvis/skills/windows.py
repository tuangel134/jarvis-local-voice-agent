from __future__ import annotations

import shutil
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill


class WindowsSkill(Skill):
    name = 'windows'
    description = 'Controla la ventana activa y workspaces del escritorio Linux.'

    ACTIONS = (
        ActionSpec(
            name='close_active',
            namespace='windows',
            description='Cierra la ventana activa.',
            intents=('window_close',),
            examples=('cierra la ventana',),
            risk_level=RiskLevel.MODERATE,
            backend='xdotool windowclose / wmctrl -ic',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='minimize_active',
            namespace='windows',
            description='Minimiza la ventana activa.',
            intents=('window_minimize',),
            examples=('minimiza la ventana',),
            risk_level=RiskLevel.SAFE,
            backend='xdotool windowminimize / wmctrl hidden',
        ),
        ActionSpec(
            name='maximize_active',
            namespace='windows',
            description='Maximiza la ventana activa.',
            intents=('window_maximize',),
            examples=('maximiza la ventana',),
            risk_level=RiskLevel.SAFE,
            backend='wmctrl maximized_vert/maximized_horz',
        ),
        ActionSpec(
            name='fullscreen_active',
            namespace='windows',
            description='Pone en pantalla completa la ventana activa.',
            intents=('window_fullscreen',),
            examples=('pantalla completa', 'pon la ventana en fullscreen'),
            risk_level=RiskLevel.SAFE,
            backend='wmctrl toggle fullscreen / xdotool F11',
        ),
        ActionSpec(
            name='switch_workspace',
            namespace='windows',
            description='Cambia al workspace indicado.',
            intents=('window_switch_workspace',),
            examples=('cambia al escritorio 2',),
            risk_level=RiskLevel.SAFE,
            backend='wmctrl -s',
        ),
        ActionSpec(
            name='tile_left',
            namespace='windows',
            description='Acomoda la ventana activa a la mitad izquierda.',
            intents=('window_tile_left',),
            examples=('mosaico izquierda',),
            risk_level=RiskLevel.SAFE,
            backend='xdotool windowmove/windowsize',
        ),
        ActionSpec(
            name='tile_right',
            namespace='windows',
            description='Acomoda la ventana activa a la mitad derecha.',
            intents=('window_tile_right',),
            examples=('mosaico derecha',),
            risk_level=RiskLevel.SAFE,
            backend='xdotool windowmove/windowsize',
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'window_close', 'window_minimize', 'window_maximize', 'window_fullscreen',
            'window_switch_workspace', 'window_tile_left', 'window_tile_right'
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'window_close':
            return self._close_active()
        if intent.name == 'window_minimize':
            return self._minimize_active()
        if intent.name == 'window_maximize':
            return self._maximize_active()
        if intent.name == 'window_fullscreen':
            return self._fullscreen_active()
        if intent.name == 'window_switch_workspace':
            return self._switch_workspace(entities)
        if intent.name == 'window_tile_left':
            return self._tile_active('left')
        if intent.name == 'window_tile_right':
            return self._tile_active('right')
        return {'ok': False, 'error': f'Acción no soportada por windows: {intent.name}'}

    def _close_active(self) -> dict[str, Any]:
        xdotool = shutil.which('xdotool')
        if xdotool:
            proc = subprocess.run([xdotool, 'getactivewindow', 'windowclose'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': 'Cerrando la ventana activa.'}
        return {'ok': False, 'error': 'No pude cerrar la ventana activa. Necesito xdotool o un entorno compatible.'}

    def _minimize_active(self) -> dict[str, Any]:
        xdotool = shutil.which('xdotool')
        if xdotool:
            proc = subprocess.run([xdotool, 'getactivewindow', 'windowminimize'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': 'Minimizando la ventana activa.'}
        wmctrl = shutil.which('wmctrl')
        if wmctrl:
            proc = subprocess.run([wmctrl, '-r', ':ACTIVE:', '-b', 'add,hidden'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': 'Minimizando la ventana activa.'}
        return {'ok': False, 'error': 'No pude minimizar la ventana activa. Falta wmctrl o xdotool.'}

    def _maximize_active(self) -> dict[str, Any]:
        wmctrl = shutil.which('wmctrl')
        if wmctrl:
            for flag in ('remove,maximized_vert,maximized_horz', 'add,maximized_vert,maximized_horz'):
                subprocess.run([wmctrl, '-r', ':ACTIVE:', '-b', flag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            return {'ok': True, 'message': 'Maximizando la ventana activa.'}
        return {'ok': False, 'error': 'No pude maximizar la ventana activa. Falta wmctrl.'}

    def _fullscreen_active(self) -> dict[str, Any]:
        wmctrl = shutil.which('wmctrl')
        if wmctrl:
            proc = subprocess.run([wmctrl, '-r', ':ACTIVE:', '-b', 'toggle,fullscreen'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': 'Alternando pantalla completa.'}
        xdotool = shutil.which('xdotool')
        if xdotool:
            proc = subprocess.run([xdotool, 'key', 'F11'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            if proc.returncode == 0:
                return {'ok': True, 'message': 'Intentando pantalla completa con F11.'}
        return {'ok': False, 'error': 'No pude cambiar la ventana a pantalla completa.'}

    def _switch_workspace(self, entities: dict[str, Any]) -> dict[str, Any]:
        wmctrl = shutil.which('wmctrl')
        if not wmctrl:
            return {'ok': False, 'error': 'No puedo cambiar de workspace sin wmctrl.'}
        workspace = entities.get('workspace')
        try:
            number = int(workspace)
        except Exception:
            return {'ok': False, 'error': 'No detecté el número de escritorio.'}
        if number < 1:
            return {'ok': False, 'error': 'El escritorio debe ser 1 o mayor.'}
        proc = subprocess.run([wmctrl, '-s', str(number - 1)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        if proc.returncode == 0:
            return {'ok': True, 'message': f'Cambiando al escritorio {number}.', 'workspace': number}
        return {'ok': False, 'error': f'No pude cambiar al escritorio {number}.'}

    def _tile_active(self, side: str) -> dict[str, Any]:
        xdotool = shutil.which('xdotool')
        if not xdotool:
            return {'ok': False, 'error': 'No puedo acomodar ventanas sin xdotool.'}
        try:
            win_id = subprocess.run([xdotool, 'getactivewindow'], capture_output=True, text=True, timeout=3, check=False)
            wid = (win_id.stdout or '').strip()
            if not wid:
                return {'ok': False, 'error': 'No detecté una ventana activa.'}
            geom = subprocess.run([xdotool, 'getdisplaygeometry'], capture_output=True, text=True, timeout=3, check=False)
            parts = (geom.stdout or '').strip().split()
            if len(parts) != 2:
                return {'ok': False, 'error': 'No pude obtener la geometría de la pantalla.'}
            width = int(parts[0])
            height = int(parts[1])
            half = max(640, width // 2)
            xpos = 0 if side == 'left' else max(0, width - half)
            subprocess.run([xdotool, 'windowsize', wid, str(half), str(height)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
            proc = subprocess.run([xdotool, 'windowmove', wid, str(xpos), '0'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4, check=False)
            if proc.returncode == 0:
                side_text = 'izquierda' if side == 'left' else 'derecha'
                return {'ok': True, 'message': f'Acomodando la ventana a la {side_text}.', 'side': side}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude acomodar la ventana: {exc}'}
        return {'ok': False, 'error': 'No pude acomodar la ventana activa.'}
