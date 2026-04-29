from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_model import Intent
from jarvis.skills.base import Skill


class DevicesSkill(Skill):
    name = 'devices'
    description = 'Lista y cambia dispositivos de audio, cámaras y USB en Linux.'
    ACTIONS = (
        ActionSpec(
            name='audio_status',
            namespace='devices',
            description='Resumen de entradas y salidas de audio detectadas.',
            intents=('devices_audio_status',),
            examples=('estado de audio', 'dispositivos de audio'),
            risk_level=RiskLevel.SAFE,
            backend='pactl|wpctl|arecord|aplay',
        ),
        ActionSpec(
            name='list_microphones',
            namespace='devices',
            description='Lista micrófonos o entradas de audio.',
            intents=('devices_list_microphones',),
            examples=('lista micrófonos', 'qué micrófonos hay'),
            risk_level=RiskLevel.SAFE,
            backend='pactl list short sources|arecord -l',
        ),
        ActionSpec(
            name='list_speakers',
            namespace='devices',
            description='Lista salidas o bocinas detectadas.',
            intents=('devices_list_speakers',),
            examples=('lista salidas de audio', 'qué bocinas hay'),
            risk_level=RiskLevel.SAFE,
            backend='pactl list short sinks|aplay -l',
        ),
        ActionSpec(
            name='set_default_input',
            namespace='devices',
            description='Cambia el dispositivo de entrada de audio por nombre.',
            intents=('devices_set_default_input',),
            examples=('usa este micrófono', 'cambia la entrada de audio'),
            risk_level=RiskLevel.MODERATE,
            backend='pactl set-default-source|wpctl set-default',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='set_default_output',
            namespace='devices',
            description='Cambia la salida de audio por nombre.',
            intents=('devices_set_default_output',),
            examples=('usa estas bocinas', 'cambia la salida de audio'),
            risk_level=RiskLevel.MODERATE,
            backend='pactl set-default-sink|wpctl set-default',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='list_cameras',
            namespace='devices',
            description='Lista cámaras o dispositivos de video detectados.',
            intents=('devices_list_cameras',),
            examples=('lista cámaras', 'qué cámaras hay'),
            risk_level=RiskLevel.SAFE,
            backend='v4l2-ctl --list-devices|/dev/video*',
        ),
        ActionSpec(
            name='list_usb',
            namespace='devices',
            description='Lista dispositivos USB conectados.',
            intents=('devices_list_usb',),
            examples=('lista usb', 'qué usb están conectados'),
            risk_level=RiskLevel.SAFE,
            backend='lsusb|sysfs',
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'devices_audio_status',
            'devices_list_microphones',
            'devices_list_speakers',
            'devices_set_default_input',
            'devices_set_default_output',
            'devices_list_cameras',
            'devices_list_usb',
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'devices_audio_status':
            return self._audio_status()
        if intent.name == 'devices_list_microphones':
            return self._list_audio_devices(kind='input')
        if intent.name == 'devices_list_speakers':
            return self._list_audio_devices(kind='output')
        if intent.name == 'devices_set_default_input':
            return self._set_default_audio_device(entities.get('device') or entities.get('name'), kind='input')
        if intent.name == 'devices_set_default_output':
            return self._set_default_audio_device(entities.get('device') or entities.get('name'), kind='output')
        if intent.name == 'devices_list_cameras':
            return self._list_cameras()
        if intent.name == 'devices_list_usb':
            return self._list_usb()
        return {'ok': False, 'error': f'Acción no soportada por devices: {intent.name}'}

    def _audio_status(self) -> dict[str, Any]:
        inputs = _list_audio_inputs()
        outputs = _list_audio_outputs()
        if not inputs and not outputs:
            return {'ok': False, 'error': 'No pude detectar dispositivos de audio.'}
        msg_parts = []
        if inputs:
            msg_parts.append('entradas: ' + ', '.join(item['name'] for item in inputs[:4]))
        if outputs:
            msg_parts.append('salidas: ' + ', '.join(item['name'] for item in outputs[:4]))
        return {
            'ok': True,
            'message': 'Audio detectado, ' + '; '.join(msg_parts) + '.',
            'inputs': inputs,
            'outputs': outputs,
        }

    def _list_audio_devices(self, kind: str) -> dict[str, Any]:
        items = _list_audio_inputs() if kind == 'input' else _list_audio_outputs()
        if not items:
            human = 'micrófonos' if kind == 'input' else 'salidas de audio'
            return {'ok': False, 'error': f'No pude detectar {human}.'}
        preview = ', '.join(item['name'] for item in items[:8])
        label = 'Micrófonos' if kind == 'input' else 'Salidas de audio'
        return {'ok': True, 'message': f'{label}: {preview}.', 'devices': items}

    def _set_default_audio_device(self, target: str | None, kind: str) -> dict[str, Any]:
        if not target:
            return {'ok': False, 'error': 'Necesito el nombre del dispositivo a usar.'}
        items = _list_audio_inputs() if kind == 'input' else _list_audio_outputs()
        match = _match_audio_device(items, target)
        if not match:
            human = 'entrada' if kind == 'input' else 'salida'
            return {'ok': False, 'error': f'No encontré una {human} de audio que coincida con {target}.'}
        device_id = match.get('id')
        if not device_id:
            return {'ok': False, 'error': 'Encontré el dispositivo, pero no pude resolver su identificador interno.'}
        if _set_default_with_pactl(device_id, kind) or _set_default_with_wpctl(device_id):
            human = 'entrada' if kind == 'input' else 'salida'
            return {'ok': True, 'message': f'Cambié la {human} de audio a {match["name"]}.', 'device': match}
        return {'ok': False, 'error': 'No pude cambiar el dispositivo por defecto con los backends disponibles.'}

    def _list_cameras(self) -> dict[str, Any]:
        cameras = _list_cameras()
        if not cameras:
            return {'ok': False, 'error': 'No detecté cámaras en este equipo.'}
        preview = ', '.join(item['name'] for item in cameras[:6])
        return {'ok': True, 'message': f'Cámaras detectadas: {preview}.', 'cameras': cameras}

    def _list_usb(self) -> dict[str, Any]:
        devices = _list_usb_devices()
        if not devices:
            return {'ok': False, 'error': 'No pude detectar dispositivos USB.'}
        preview = ', '.join(item['name'] for item in devices[:8])
        return {'ok': True, 'message': f'USB detectados: {preview}.', 'devices': devices}



def _run(cmd: list[str], timeout: float = 6.0) -> str | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode == 0:
            out = (proc.stdout or '').strip()
            return out or None
    except Exception:
        return None
    return None


def _list_audio_inputs() -> list[dict[str, Any]]:
    items = _parse_pactl_short('sources')
    if items:
        return items
    return _parse_arecord_devices()


def _list_audio_outputs() -> list[dict[str, Any]]:
    items = _parse_pactl_short('sinks')
    if items:
        return items
    return _parse_aplay_devices()


def _parse_pactl_short(kind: str) -> list[dict[str, Any]]:
    pactl = shutil.which('pactl')
    if not pactl:
        return []
    raw = _run([pactl, 'list', 'short', kind], timeout=8)
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for line in raw.splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        result.append({'id': parts[0].strip(), 'name': parts[1].strip(), 'backend': 'pactl'})
    return result


def _parse_arecord_devices() -> list[dict[str, Any]]:
    arecord = shutil.which('arecord')
    if not arecord:
        return []
    raw = _run([arecord, '-l'], timeout=8)
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('card '):
            result.append({'id': line, 'name': line, 'backend': 'arecord'})
    return result


def _parse_aplay_devices() -> list[dict[str, Any]]:
    aplay = shutil.which('aplay')
    if not aplay:
        return []
    raw = _run([aplay, '-l'], timeout=8)
    if not raw:
        return []
    result: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('card '):
            result.append({'id': line, 'name': line, 'backend': 'aplay'})
    return result


def _match_audio_device(items: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    norm = target.strip().lower()
    for item in items:
        if norm == str(item.get('name', '')).lower():
            return item
    for item in items:
        if norm in str(item.get('name', '')).lower():
            return item
    return None


def _set_default_with_pactl(device_id: str, kind: str) -> bool:
    pactl = shutil.which('pactl')
    if not pactl:
        return False
    cmd = [pactl, 'set-default-source' if kind == 'input' else 'set-default-sink', str(device_id)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def _set_default_with_wpctl(device_id: str) -> bool:
    wpctl = shutil.which('wpctl')
    if not wpctl:
        return False
    try:
        proc = subprocess.run([wpctl, 'set-default', str(device_id)], capture_output=True, text=True, timeout=8, check=False)
        return proc.returncode == 0
    except Exception:
        return False


def _list_cameras() -> list[dict[str, Any]]:
    v4l2 = shutil.which('v4l2-ctl')
    if v4l2:
        raw = _run([v4l2, '--list-devices'], timeout=8)
        if raw:
            entries: list[dict[str, Any]] = []
            current_name = None
            for line in raw.splitlines():
                if not line.startswith('\t') and line.strip():
                    current_name = line.strip().rstrip(':')
                elif line.startswith('\t/dev/video') and current_name:
                    entries.append({'name': current_name, 'path': line.strip(), 'backend': 'v4l2-ctl'})
            if entries:
                return entries
    result = []
    for path in sorted(Path('/dev').glob('video*')):
        result.append({'name': path.name, 'path': str(path), 'backend': 'devfs'})
    return result


def _list_usb_devices() -> list[dict[str, Any]]:
    lsusb = shutil.which('lsusb')
    if lsusb:
        raw = _run([lsusb], timeout=8)
        if raw:
            devices = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                devices.append({'name': line, 'backend': 'lsusb'})
            if devices:
                return devices
    sysfs = Path('/sys/bus/usb/devices')
    devices = []
    try:
        if sysfs.exists():
            for child in sorted(sysfs.iterdir()):
                product = child / 'product'
                manufacturer = child / 'manufacturer'
                if product.exists():
                    name = product.read_text(encoding='utf-8', errors='ignore').strip()
                    if manufacturer.exists():
                        maker = manufacturer.read_text(encoding='utf-8', errors='ignore').strip()
                        if maker:
                            name = f'{maker} {name}'
                    if name:
                        devices.append({'name': name, 'backend': 'sysfs'})
    except Exception:
        return devices
    return devices
