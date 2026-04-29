from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import platform
import shutil
import subprocess
import time

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_model import Intent
from jarvis.skills.base import Skill


class SystemSkill(Skill):
    name = 'system'
    description = 'Hora, fecha y estado ampliado del sistema.'
    ACTIONS = (
        ActionSpec(
            name='time',
            namespace='system',
            description='Consulta la hora local actual.',
            intents=('get_time',),
            examples=('qué hora es',),
            risk_level=RiskLevel.SAFE,
            backend='datetime.now',
        ),
        ActionSpec(
            name='date',
            namespace='system',
            description='Consulta la fecha local actual.',
            intents=('get_date',),
            examples=('qué fecha es hoy',),
            risk_level=RiskLevel.SAFE,
            backend='datetime.now',
        ),
        ActionSpec(
            name='status',
            namespace='system',
            description='Resume CPU, RAM y disco del sistema local.',
            intents=('system_status',),
            examples=('cómo está el sistema', 'estado del sistema'),
            risk_level=RiskLevel.SAFE,
            backend='psutil|/proc|shutil',
        ),
        ActionSpec(
            name='cpu_status',
            namespace='system',
            description='Consulta el uso actual de CPU.',
            intents=('system_cpu_status',),
            examples=('uso de cpu', 'cómo va la cpu'),
            risk_level=RiskLevel.SAFE,
            backend='psutil|top|/proc/stat',
        ),
        ActionSpec(
            name='memory_status',
            namespace='system',
            description='Consulta el uso actual de memoria RAM.',
            intents=('system_memory_status',),
            examples=('cuánta ram estoy usando',),
            risk_level=RiskLevel.SAFE,
            backend='psutil|/proc/meminfo',
        ),
        ActionSpec(
            name='disk_status',
            namespace='system',
            description='Consulta el uso actual del disco.',
            intents=('system_disk_status',),
            examples=('espacio en disco',),
            risk_level=RiskLevel.SAFE,
            backend='psutil|shutil.disk_usage',
        ),
        ActionSpec(
            name='hostname',
            namespace='system',
            description='Consulta el nombre del equipo.',
            intents=('system_hostname',),
            examples=('nombre del equipo',),
            risk_level=RiskLevel.SAFE,
            backend='platform.node|hostname',
        ),
        ActionSpec(
            name='uptime',
            namespace='system',
            description='Consulta cuánto tiempo lleva encendido el equipo.',
            intents=('system_uptime',),
            examples=('cuánto lleva encendida la pc',),
            risk_level=RiskLevel.SAFE,
            backend='psutil.boot_time|/proc/uptime',
        ),
        ActionSpec(
            name='battery_status',
            namespace='system',
            description='Consulta el estado de la batería si existe.',
            intents=('system_battery_status',),
            examples=('cómo está la batería',),
            risk_level=RiskLevel.SAFE,
            backend='psutil.sensors_battery|/sys/class/power_supply',
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'get_time',
            'get_date',
            'system_status',
            'system_cpu_status',
            'system_memory_status',
            'system_disk_status',
            'system_hostname',
            'system_uptime',
            'system_battery_status',
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now()
        if intent.name == 'get_time':
            value = now.strftime('%H:%M')
            return {'ok': True, 'message': f'Son las {value}.', 'time': value}
        if intent.name == 'get_date':
            value = now.strftime('%d/%m/%Y')
            return {'ok': True, 'message': f'Hoy es {value}.', 'date': value}
        if intent.name == 'system_cpu_status':
            cpu = _cpu_percent()
            return {'ok': True, 'message': f'CPU al {cpu:.1f} por ciento.', 'cpu_percent': cpu}
        if intent.name == 'system_memory_status':
            mem = _memory_snapshot()
            pct = mem.get('percent', 0.0)
            return {'ok': True, 'message': f'RAM al {pct:.1f} por ciento.', 'memory': mem}
        if intent.name == 'system_disk_status':
            path = str(entities.get('path', '/') or '/').strip() or '/'
            disk = _disk_snapshot(path)
            pct = disk.get('percent', 0.0)
            return {'ok': True, 'message': f'Disco al {pct:.1f} por ciento en {disk.get("path", path)}.', 'disk': disk}
        if intent.name == 'system_hostname':
            host = _hostname()
            return {'ok': True, 'message': f'El equipo se llama {host}.', 'hostname': host}
        if intent.name == 'system_uptime':
            seconds = _uptime_seconds()
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return {
                'ok': True,
                'message': f'Llevo encendido {hours} horas y {minutes} minutos.',
                'uptime_seconds': seconds,
                'hours': hours,
                'minutes': minutes,
            }
        if intent.name == 'system_battery_status':
            battery = _battery_snapshot()
            if battery is None:
                return {'ok': False, 'error': 'No encontré batería en este equipo.'}
            pct = battery.get('percent', 0.0)
            plugged = 'conectada' if battery.get('plugged') else 'sin conectar'
            return {'ok': True, 'message': f'Batería al {pct:.1f} por ciento, {plugged}.', 'battery': battery}

        stats = _system_status_payload()
        return {
            'ok': True,
            'message': f"CPU al {stats['cpu_percent']:.1f} por ciento. Memoria usada {stats['memory']['percent']:.1f} por ciento. Disco raíz usado {stats['disk']['percent']:.1f} por ciento.",
            'stats': stats,
        }


def _run_command(cmd: list[str]) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5, check=False)
        if proc.returncode == 0:
            out = (proc.stdout or '').strip()
            return out or None
    except Exception:
        return None
    return None


def _hostname() -> str:
    return platform.node() or (_run_command(['hostname']) or 'desconocido')


def _cpu_percent() -> float:
    if psutil is not None:
        try:
            return float(psutil.cpu_percent(interval=0.2))
        except Exception:
            pass
    top_line = _run_command(['sh', '-lc', "LANG=C top -bn1 | grep 'Cpu(s)' | head -n1"])
    if top_line and ' id,' in top_line:
        try:
            idle_fragment = top_line.split(' id,', 1)[0].rsplit(' ', 1)[-1]
            idle = float(idle_fragment.replace(',', '.'))
            return round(max(0.0, 100.0 - idle), 1)
        except Exception:
            pass
    try:
        raw = Path('/proc/stat').read_text(encoding='utf-8', errors='ignore').splitlines()
        first = raw[0].split()
        nums = [int(x) for x in first[1:8]]
        idle = nums[3] + nums[4]
        total = sum(nums)
        busy = max(0, total - idle)
        if total <= 0:
            return 0.0
        return round((busy / total) * 100.0, 1)
    except Exception:
        return 0.0


def _memory_snapshot() -> dict[str, Any]:
    if psutil is not None:
        try:
            mem = psutil.virtual_memory()
            return {
                'total_mb': round(mem.total / (1024 * 1024)),
                'used_mb': round(mem.used / (1024 * 1024)),
                'available_mb': round(mem.available / (1024 * 1024)),
                'percent': float(mem.percent),
                'source': 'psutil',
            }
        except Exception:
            pass
    try:
        raw = Path('/proc/meminfo').read_text(encoding='utf-8', errors='ignore')
        values: dict[str, int] = {}
        for line in raw.splitlines():
            if ':' not in line:
                continue
            key, rest = line.split(':', 1)
            token = rest.strip().split()[0]
            if token.isdigit():
                values[key] = int(token)
        total = values.get('MemTotal', 0)
        available = values.get('MemAvailable', values.get('MemFree', 0))
        used = max(0, total - available)
        percent = round((used / total) * 100.0, 1) if total else 0.0
        return {
            'total_mb': round(total / 1024),
            'used_mb': round(used / 1024),
            'available_mb': round(available / 1024),
            'percent': percent,
            'source': 'procfs',
        }
    except Exception:
        return {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'percent': 0.0, 'source': 'unknown'}


def _disk_snapshot(path: str = '/') -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        total = usage.total
        used = usage.used
        free = usage.free
        percent = round((used / total) * 100.0, 1) if total else 0.0
        return {
            'path': path,
            'total_gb': round(total / (1024 ** 3), 1),
            'used_gb': round(used / (1024 ** 3), 1),
            'free_gb': round(free / (1024 ** 3), 1),
            'percent': percent,
            'source': 'shutil',
        }
    except Exception:
        return {'path': path, 'total_gb': 0.0, 'used_gb': 0.0, 'free_gb': 0.0, 'percent': 0.0, 'source': 'unknown'}


def _uptime_seconds() -> int:
    if psutil is not None:
        try:
            return max(0, int(time.time() - psutil.boot_time()))
        except Exception:
            pass
    raw = _run_command(['cat', '/proc/uptime'])
    if raw:
        try:
            return int(float(raw.split()[0]))
        except Exception:
            return 0
    return 0


def _battery_snapshot() -> dict[str, Any] | None:
    if psutil is not None:
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                return {
                    'percent': round(float(battery.percent), 1),
                    'plugged': bool(battery.power_plugged),
                    'source': 'psutil',
                }
        except Exception:
            pass
    power_supply = Path('/sys/class/power_supply')
    if power_supply.exists():
        try:
            for child in power_supply.iterdir():
                capacity = child / 'capacity'
                status = child / 'status'
                if capacity.exists():
                    pct = float(capacity.read_text(encoding='utf-8', errors='ignore').strip())
                    st = status.read_text(encoding='utf-8', errors='ignore').strip() if status.exists() else ''
                    return {'percent': pct, 'plugged': st.lower() in {'charging', 'full'}, 'source': 'sysfs'}
        except Exception:
            pass
    return None


def _system_status_payload() -> dict[str, Any]:
    return {
        'hostname': _hostname(),
        'cpu_percent': _cpu_percent(),
        'memory': _memory_snapshot(),
        'disk': _disk_snapshot('/'),
        'battery': _battery_snapshot(),
        'psutil_available': psutil is not None,
    }
