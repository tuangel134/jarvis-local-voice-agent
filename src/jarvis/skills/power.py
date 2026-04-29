from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_model import Intent
from jarvis.skills.base import Skill


class PowerSkill(Skill):
    name = 'power'
    description = 'Controla sesión, suspensión y energía del equipo Linux.'
    ACTIONS = (
        ActionSpec(
            name='lock_screen',
            namespace='power',
            description='Bloquea la sesión o pantalla actual.',
            intents=('power_lock_screen',),
            examples=('bloquea la pantalla', 'bloquea la sesión'),
            risk_level=RiskLevel.MODERATE,
            backend='loginctl lock-session|xdg-screensaver lock',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='suspend',
            namespace='power',
            description='Suspende el equipo.',
            intents=('power_suspend',),
            examples=('suspende la pc', 'suspende el equipo'),
            risk_level=RiskLevel.SENSITIVE,
            backend='systemctl suspend|loginctl suspend',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='logout',
            namespace='power',
            description='Cierra la sesión gráfica actual.',
            intents=('power_logout',),
            examples=('cierra sesión', 'logout'),
            risk_level=RiskLevel.SENSITIVE,
            backend='loginctl terminate-session|gnome-session-quit',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='reboot',
            namespace='power',
            description='Reinicia el equipo.',
            intents=('power_reboot',),
            examples=('reinicia la pc', 'reinicia el equipo'),
            risk_level=RiskLevel.DANGEROUS,
            backend='systemctl reboot',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='shutdown',
            namespace='power',
            description='Apaga el equipo.',
            intents=('power_shutdown',),
            examples=('apaga la pc', 'apaga el equipo'),
            risk_level=RiskLevel.DANGEROUS,
            backend='systemctl poweroff',
            requires_confirmation=True,
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'power_lock_screen',
            'power_suspend',
            'power_logout',
            'power_reboot',
            'power_shutdown',
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'power_lock_screen':
            return self._lock_screen()
        if intent.name == 'power_suspend':
            return self._do_power('suspend', 'Suspendiendo el equipo.')
        if intent.name == 'power_reboot':
            return self._do_power('reboot', 'Reiniciando el equipo.')
        if intent.name == 'power_shutdown':
            return self._do_power('poweroff', 'Apagando el equipo.')
        if intent.name == 'power_logout':
            return self._logout()
        return {'ok': False, 'error': f'Acción no soportada por power: {intent.name}'}

    def _lock_screen(self) -> dict[str, Any]:
        loginctl = shutil.which('loginctl')
        session = os.environ.get('XDG_SESSION_ID', '').strip()
        if loginctl:
            commands = []
            if session:
                commands.append([loginctl, 'lock-session', session])
            commands.append([loginctl, 'lock-sessions'])
            for cmd in commands:
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6, check=False)
                    if proc.returncode == 0:
                        return {'ok': True, 'message': 'Bloqueando la sesión.'}
                except Exception:
                    pass
        xdg = shutil.which('xdg-screensaver')
        if xdg:
            try:
                proc = subprocess.run([xdg, 'lock'], capture_output=True, text=True, timeout=6, check=False)
                if proc.returncode == 0:
                    return {'ok': True, 'message': 'Bloqueando la pantalla.'}
            except Exception:
                pass
        return {'ok': False, 'error': 'No pude bloquear la pantalla. Necesito loginctl o xdg-screensaver.'}

    def _logout(self) -> dict[str, Any]:
        loginctl = shutil.which('loginctl')
        session = os.environ.get('XDG_SESSION_ID', '').strip()
        if loginctl and session:
            try:
                proc = subprocess.run([loginctl, 'terminate-session', session], capture_output=True, text=True, timeout=8, check=False)
                if proc.returncode == 0:
                    return {'ok': True, 'message': 'Cerrando la sesión actual.'}
            except Exception:
                pass
        candidates = [
            ['gnome-session-quit', '--logout', '--no-prompt'],
            ['qdbus', 'org.kde.Shutdown', '/Shutdown', 'logout'],
            ['mate-session-save', '--logout-dialog'],
        ]
        for cmd in candidates:
            if not shutil.which(cmd[0]):
                continue
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
                if proc.returncode == 0:
                    return {'ok': True, 'message': 'Cerrando la sesión actual.'}
            except Exception:
                pass
        return {'ok': False, 'error': 'No pude cerrar la sesión actual con los backends disponibles.'}

    def _do_power(self, action: str, success_message: str) -> dict[str, Any]:
        loginctl = shutil.which('loginctl')
        systemctl = shutil.which('systemctl')
        commands = []
        if action == 'suspend':
            if systemctl:
                commands.append([systemctl, 'suspend'])
            if loginctl:
                commands.append([loginctl, 'suspend'])
        elif action == 'reboot':
            if systemctl:
                commands.append([systemctl, 'reboot'])
            if loginctl:
                commands.append([loginctl, 'reboot'])
        elif action == 'poweroff':
            if systemctl:
                commands.append([systemctl, 'poweroff'])
            if loginctl:
                commands.append([loginctl, 'poweroff'])
        for cmd in commands:
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
                if proc.returncode == 0:
                    return {'ok': True, 'message': success_message}
            except Exception:
                pass
        return {'ok': False, 'error': f'No pude ejecutar {action} con systemctl/loginctl.'}
