from __future__ import annotations

import shutil
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.text import normalize


class ServicesSkill(Skill):
    name = 'services'
    description = 'Consulta y controla servicios systemd permitidos de usuario o del sistema.'

    allowed_services = {
        'jellyfin': {'candidates': ['jellyfin'], 'scopes': ('system',)},
        'immich': {'candidates': ['immich-server', 'immich'], 'scopes': ('system',)},
        'docker': {'candidates': ['docker'], 'scopes': ('system',)},
        'ssh': {'candidates': ['ssh', 'sshd'], 'scopes': ('system',)},
        'sshd': {'candidates': ['sshd', 'ssh'], 'scopes': ('system',)},
        'jarvis': {'candidates': ['jarvis'], 'scopes': ('user',)},
    }

    ACTIONS = (
        ActionSpec(
            name='status',
            namespace='services',
            description='Consulta el estado de un servicio permitido de systemd.',
            intents=('service_status',),
            examples=('estado de jellyfin', 'como esta docker', 'estado de jarvis'),
            risk_level=RiskLevel.SAFE,
            backend='systemctl is-active / --user is-active',
        ),
        ActionSpec(
            name='start',
            namespace='services',
            description='Inicia un servicio permitido.',
            intents=('service_start',),
            examples=('inicia jarvis', 'arranca docker'),
            risk_level=RiskLevel.MODERATE,
            backend='systemctl start / --user start',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='stop',
            namespace='services',
            description='Detiene un servicio permitido.',
            intents=('service_stop',),
            examples=('deten docker', 'para jarvis'),
            risk_level=RiskLevel.SENSITIVE,
            backend='systemctl stop / --user stop',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='restart',
            namespace='services',
            description='Reinicia un servicio permitido.',
            intents=('service_restart',),
            examples=('reinicia jellyfin', 'reinicia jarvis'),
            risk_level=RiskLevel.MODERATE,
            backend='systemctl restart / --user restart',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='logs',
            namespace='services',
            description='Muestra un resumen corto de logs recientes de un servicio permitido.',
            intents=('service_logs',),
            examples=('logs de jarvis', 'muestra logs de docker'),
            risk_level=RiskLevel.SAFE,
            backend='journalctl -u / --user-unit',
        ),
        ActionSpec(
            name='list_failed',
            namespace='services',
            description='Lista servicios fallando en systemd del usuario y del sistema.',
            intents=('service_list_failed',),
            examples=('servicios fallando', 'que servicios fallaron'),
            risk_level=RiskLevel.SAFE,
            backend='systemctl --failed + systemctl --user --failed',
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {'service_status', 'service_start', 'service_stop', 'service_restart', 'service_logs', 'service_list_failed'}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'service_list_failed':
            return self._list_failed()

        alias = normalize(str(entities.get('service', ''))).split()[0]
        spec = self.allowed_services.get(alias)
        if not alias or spec is None:
            allowed = ', '.join(sorted(self.allowed_services))
            return {'ok': False, 'error': f'El servicio no está permitido. Opciones: {allowed}.'}

        candidates = list(spec.get('candidates', []))
        scopes = tuple(spec.get('scopes', ('system',)))

        if intent.name == 'service_status':
            return self._status(alias, candidates, scopes)
        if intent.name == 'service_start':
            return self._change_service('start', alias, candidates, scopes)
        if intent.name == 'service_stop':
            return self._change_service('stop', alias, candidates, scopes)
        if intent.name == 'service_restart':
            return self._change_service('restart', alias, candidates, scopes)
        if intent.name == 'service_logs':
            return self._logs(alias, candidates, scopes)
        return {'ok': False, 'error': f'Acción no soportada por services: {intent.name}'}

    def _status(self, alias: str, candidates: list[str], scopes: tuple[str, ...]) -> dict[str, Any]:
        statuses = []
        for scope in scopes:
            for candidate in candidates:
                proc = self._run_systemctl(['is-active', candidate], scope)
                status = (proc.stdout or proc.stderr or '').strip() or 'unknown'
                statuses.append((scope, candidate, status, proc.returncode))
                if proc.returncode == 0 and status == 'active':
                    return {
                        'ok': True,
                        'message': f'{alias.capitalize()} está activo ({scope}).',
                        'service': alias,
                        'status': 'active',
                        'scope': scope,
                        'candidate': candidate,
                    }
        detail = ', '.join(f'{cand}@{scope}: {status}' for scope, cand, status, _ in statuses[:6])
        return {
            'ok': True,
            'message': f'{alias.capitalize()} no aparece activo. {detail}.',
            'service': alias,
            'status': 'inactive',
            'checks': detail,
        }

    def _change_service(self, verb: str, alias: str, candidates: list[str], scopes: tuple[str, ...]) -> dict[str, Any]:
        verb_text = {
            'start': 'Iniciando',
            'stop': 'Deteniendo',
            'restart': 'Reiniciando',
        }[verb]
        errors = []
        for scope in scopes:
            for candidate in candidates:
                proc = self._run_systemctl([verb, candidate], scope)
                if proc.returncode == 0:
                    return {
                        'ok': True,
                        'message': f'{verb_text} {alias} ({scope}).',
                        'service': alias,
                        'scope': scope,
                        'candidate': candidate,
                        'operation': verb,
                    }
                error = (proc.stderr or proc.stdout or '').strip() or f'rc={proc.returncode}'
                errors.append(f'{candidate}@{scope}: {error}')
        return {
            'ok': False,
            'error': f'No pude {verb} {alias}. ' + '; '.join(errors[:4]),
            'service': alias,
            'operation': verb,
        }

    def _logs(self, alias: str, candidates: list[str], scopes: tuple[str, ...]) -> dict[str, Any]:
        for scope in scopes:
            for candidate in candidates:
                args = ['journalctl', '--no-pager', '-n', '12']
                if scope == 'user':
                    args.extend(['--user-unit', candidate])
                else:
                    args.extend(['-u', candidate])
                proc = subprocess.run(args, text=True, capture_output=True, timeout=6, check=False)
                if proc.returncode == 0 and (proc.stdout or '').strip():
                    lines = [line.strip() for line in (proc.stdout or '').splitlines() if line.strip()]
                    tail = lines[-3:] if lines else []
                    preview = ' | '.join(tail)[:320] if tail else 'sin líneas recientes'
                    return {
                        'ok': True,
                        'message': f'Logs recientes de {alias}: {preview}',
                        'service': alias,
                        'scope': scope,
                        'candidate': candidate,
                        'logs_preview': preview,
                    }
        return {'ok': False, 'error': f'No pude leer logs de {alias}.'}

    def _list_failed(self) -> dict[str, Any]:
        collected: list[str] = []
        for scope in ('user', 'system'):
            args = ['systemctl']
            if scope == 'user':
                args.append('--user')
            args.extend(['--failed', '--no-legend', '--no-pager'])
            try:
                proc = subprocess.run(args, text=True, capture_output=True, timeout=5, check=False)
                output = (proc.stdout or '').strip()
                if output:
                    for line in output.splitlines()[:10]:
                        first = line.split(None, 1)[0].strip()
                        if first and first not in collected:
                            collected.append(first)
            except Exception:
                continue
        if not collected:
            return {'ok': True, 'message': 'No veo servicios fallando en systemd.', 'failed': []}
        return {'ok': True, 'message': 'Servicios fallando: ' + ', '.join(collected[:10]) + '.', 'failed': collected}

    def _run_systemctl(self, sub_args: list[str], scope: str) -> subprocess.CompletedProcess:
        base = ['systemctl']
        if scope == 'user':
            base.append('--user')
        return subprocess.run(base + sub_args, text=True, capture_output=True, timeout=8, check=False)
