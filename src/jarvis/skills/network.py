from __future__ import annotations

import shutil
import socket
import subprocess
from typing import Any

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.intent_model import Intent
from jarvis.skills.base import Skill


class NetworkSkill(Skill):
    name = 'network'
    description = 'Consulta y controla red, Wi-Fi y Bluetooth en Linux.'
    ACTIONS = (
        ActionSpec(
            name='status',
            namespace='network',
            description='Resume el estado general de la red local.',
            intents=('network_status',),
            examples=('estado de red', 'cómo está la red'),
            risk_level=RiskLevel.SAFE,
            backend='nmcli|ip|rfkill|socket',
        ),
        ActionSpec(
            name='ip_address',
            namespace='network',
            description='Muestra direcciones IP locales detectadas.',
            intents=('network_ip',),
            examples=('cuál es mi ip', 'qué ip tengo'),
            risk_level=RiskLevel.SAFE,
            backend='hostname -I|ip -4 addr',
        ),
        ActionSpec(
            name='internet_test',
            namespace='network',
            description='Prueba conectividad básica saliente.',
            intents=('network_test_internet',),
            examples=('hay internet', 'prueba internet'),
            risk_level=RiskLevel.SAFE,
            backend='socket.create_connection',
        ),
        ActionSpec(
            name='list_wifi',
            namespace='network',
            description='Lista redes Wi-Fi visibles.',
            intents=('network_list_wifi',),
            examples=('lista redes wifi', 'muestra redes wifi'),
            risk_level=RiskLevel.SAFE,
            backend='nmcli dev wifi list',
        ),
        ActionSpec(
            name='wifi_on',
            namespace='network',
            description='Enciende la radio Wi-Fi.',
            intents=('network_wifi_on',),
            examples=('enciende wifi', 'activa wifi'),
            risk_level=RiskLevel.MODERATE,
            backend='nmcli radio wifi on|rfkill unblock wifi',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='wifi_off',
            namespace='network',
            description='Apaga la radio Wi-Fi.',
            intents=('network_wifi_off',),
            examples=('apaga wifi', 'desactiva wifi'),
            risk_level=RiskLevel.MODERATE,
            backend='nmcli radio wifi off|rfkill block wifi',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='bluetooth_on',
            namespace='network',
            description='Enciende Bluetooth.',
            intents=('network_bluetooth_on',),
            examples=('enciende bluetooth', 'activa bluetooth'),
            risk_level=RiskLevel.MODERATE,
            backend='bluetoothctl power on|rfkill unblock bluetooth',
            requires_confirmation=True,
        ),
        ActionSpec(
            name='bluetooth_off',
            namespace='network',
            description='Apaga Bluetooth.',
            intents=('network_bluetooth_off',),
            examples=('apaga bluetooth', 'desactiva bluetooth'),
            risk_level=RiskLevel.MODERATE,
            backend='bluetoothctl power off|rfkill block bluetooth',
            requires_confirmation=True,
        ),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {
            'network_status',
            'network_ip',
            'network_test_internet',
            'network_list_wifi',
            'network_wifi_on',
            'network_wifi_off',
            'network_bluetooth_on',
            'network_bluetooth_off',
        }

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if intent.name == 'network_status':
            return self._status()
        if intent.name == 'network_ip':
            return self._ip_address()
        if intent.name == 'network_test_internet':
            return self._internet_test()
        if intent.name == 'network_list_wifi':
            return self._list_wifi()
        if intent.name == 'network_wifi_on':
            return self._toggle_wifi(True)
        if intent.name == 'network_wifi_off':
            return self._toggle_wifi(False)
        if intent.name == 'network_bluetooth_on':
            return self._toggle_bluetooth(True)
        if intent.name == 'network_bluetooth_off':
            return self._toggle_bluetooth(False)
        return {'ok': False, 'error': f'Acción no soportada por network: {intent.name}'}

    def _status(self) -> dict[str, Any]:
        payload = {
            'ip_addresses': _detect_ip_addresses(),
            'wifi_enabled': _wifi_enabled(),
            'bluetooth_enabled': _bluetooth_enabled(),
            'internet_ok': _internet_ok(),
            'nmcli': bool(shutil.which('nmcli')),
        }
        net_line = _nmcli(['general', 'status'])
        if net_line:
            payload['nmcli_general'] = net_line
        wifi_txt = 'encendido' if payload['wifi_enabled'] else 'apagado'
        bt_txt = 'encendido' if payload['bluetooth_enabled'] else 'apagado'
        net_txt = 'sí' if payload['internet_ok'] else 'no'
        ips = ', '.join(payload['ip_addresses'][:3]) if payload['ip_addresses'] else 'sin IP detectada'
        return {
            'ok': True,
            'message': f'Red: Wi-Fi {wifi_txt}, Bluetooth {bt_txt}, internet {net_txt}, IP {ips}.',
            'network': payload,
        }

    def _ip_address(self) -> dict[str, Any]:
        ips = _detect_ip_addresses()
        if not ips:
            return {'ok': False, 'error': 'No pude detectar una dirección IP local.'}
        return {'ok': True, 'message': 'IPs detectadas: ' + ', '.join(ips[:4]) + '.', 'ip_addresses': ips}

    def _internet_test(self) -> dict[str, Any]:
        ok = _internet_ok()
        if ok:
            return {'ok': True, 'message': 'Sí hay conectividad básica a internet.', 'internet_ok': True}
        return {'ok': False, 'error': 'No pude confirmar conectividad a internet.', 'internet_ok': False}

    def _list_wifi(self) -> dict[str, Any]:
        nmcli = shutil.which('nmcli')
        if not nmcli:
            return {'ok': False, 'error': 'No puedo listar redes Wi-Fi sin nmcli.'}
        try:
            proc = subprocess.run(
                [nmcli, '-t', '-f', 'IN-USE,SSID,SIGNAL,SECURITY', 'device', 'wifi', 'list'],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if proc.returncode != 0:
                return {'ok': False, 'error': (proc.stderr or proc.stdout or 'nmcli devolvió error').strip()}
            networks = []
            seen = set()
            for line in (proc.stdout or '').splitlines():
                parts = line.split(':')
                if len(parts) < 4:
                    continue
                in_use, ssid, signal, security = parts[0], parts[1].strip(), parts[2].strip(), ':'.join(parts[3:]).strip()
                if not ssid:
                    continue
                key = ssid.lower()
                if key in seen:
                    continue
                seen.add(key)
                networks.append({
                    'ssid': ssid,
                    'in_use': in_use.strip() == '*',
                    'signal': signal,
                    'security': security or 'open',
                })
            if not networks:
                return {'ok': False, 'error': 'No detecté redes Wi-Fi visibles.'}
            preview = []
            for item in networks[:8]:
                mark = ' *' if item['in_use'] else ''
                preview.append(f"{item['ssid']} ({item['signal']}%{mark})")
            return {'ok': True, 'message': 'Redes Wi-Fi: ' + ', '.join(preview) + '.', 'networks': networks}
        except Exception as exc:
            return {'ok': False, 'error': f'No pude listar redes Wi-Fi: {exc}'}

    def _toggle_wifi(self, enabled: bool) -> dict[str, Any]:
        desired = 'on' if enabled else 'off'
        nmcli = shutil.which('nmcli')
        if nmcli:
            try:
                proc = subprocess.run([nmcli, 'radio', 'wifi', desired], capture_output=True, text=True, timeout=6, check=False)
                if proc.returncode == 0:
                    msg = 'Wi-Fi encendido.' if enabled else 'Wi-Fi apagado.'
                    return {'ok': True, 'message': msg, 'wifi_enabled': enabled}
            except Exception:
                pass
        rfkill = shutil.which('rfkill')
        if rfkill:
            try:
                action = 'unblock' if enabled else 'block'
                proc = subprocess.run([rfkill, action, 'wifi'], capture_output=True, text=True, timeout=6, check=False)
                if proc.returncode == 0:
                    msg = 'Wi-Fi encendido.' if enabled else 'Wi-Fi apagado.'
                    return {'ok': True, 'message': msg, 'wifi_enabled': enabled}
            except Exception:
                pass
        return {'ok': False, 'error': 'No pude cambiar el estado del Wi-Fi. Necesito nmcli o rfkill.'}

    def _toggle_bluetooth(self, enabled: bool) -> dict[str, Any]:
        bluetoothctl = shutil.which('bluetoothctl')
        if bluetoothctl:
            try:
                proc = subprocess.run([bluetoothctl, 'power', 'on' if enabled else 'off'], capture_output=True, text=True, timeout=8, check=False)
                if proc.returncode == 0:
                    msg = 'Bluetooth encendido.' if enabled else 'Bluetooth apagado.'
                    return {'ok': True, 'message': msg, 'bluetooth_enabled': enabled}
            except Exception:
                pass
        rfkill = shutil.which('rfkill')
        if rfkill:
            try:
                action = 'unblock' if enabled else 'block'
                proc = subprocess.run([rfkill, action, 'bluetooth'], capture_output=True, text=True, timeout=6, check=False)
                if proc.returncode == 0:
                    msg = 'Bluetooth encendido.' if enabled else 'Bluetooth apagado.'
                    return {'ok': True, 'message': msg, 'bluetooth_enabled': enabled}
            except Exception:
                pass
        return {'ok': False, 'error': 'No pude cambiar el estado de Bluetooth. Necesito bluetoothctl o rfkill.'}


def _nmcli(args: list[str]) -> str | None:
    nmcli = shutil.which('nmcli')
    if not nmcli:
        return None
    try:
        proc = subprocess.run([nmcli] + args, capture_output=True, text=True, timeout=6, check=False)
        if proc.returncode == 0:
            out = (proc.stdout or '').strip()
            return out or None
    except Exception:
        return None
    return None


def _detect_ip_addresses() -> list[str]:
    out: list[str] = []
    try:
        proc = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=2, check=False)
        if proc.returncode == 0:
            for token in (proc.stdout or '').split():
                token = token.strip()
                if token and ':' not in token and token not in out:
                    out.append(token)
    except Exception:
        pass
    if out:
        return out
    ip_bin = shutil.which('ip')
    if ip_bin:
        try:
            proc = subprocess.run([ip_bin, '-4', '-o', 'addr', 'show', 'scope', 'global'], capture_output=True, text=True, timeout=4, check=False)
            if proc.returncode == 0:
                for line in (proc.stdout or '').splitlines():
                    parts = line.split()
                    if 'inet' in parts:
                        idx = parts.index('inet')
                        if idx + 1 < len(parts):
                            ip = parts[idx + 1].split('/')[0].strip()
                            if ip and ip not in out:
                                out.append(ip)
        except Exception:
            pass
    return out


def _internet_ok() -> bool:
    targets = [('1.1.1.1', 53), ('8.8.8.8', 53)]
    for host, port in targets:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except Exception:
            continue
    return False


def _wifi_enabled() -> bool:
    line = _nmcli(['radio', 'wifi'])
    if line:
        return line.strip().lower() in {'enabled', 'habilitado'}
    rfkill = shutil.which('rfkill')
    if rfkill:
        try:
            proc = subprocess.run([rfkill, 'list', 'wifi'], capture_output=True, text=True, timeout=4, check=False)
            text = (proc.stdout or '').lower()
            if 'soft blocked: yes' in text or 'hard blocked: yes' in text:
                return False
            if 'soft blocked: no' in text or 'hard blocked: no' in text:
                return True
        except Exception:
            pass
    return False


def _bluetooth_enabled() -> bool:
    bluetoothctl = shutil.which('bluetoothctl')
    if bluetoothctl:
        try:
            proc = subprocess.run([bluetoothctl, 'show'], capture_output=True, text=True, timeout=6, check=False)
            text = (proc.stdout or '').lower()
            if 'powered: yes' in text:
                return True
            if 'powered: no' in text:
                return False
        except Exception:
            pass
    rfkill = shutil.which('rfkill')
    if rfkill:
        try:
            proc = subprocess.run([rfkill, 'list', 'bluetooth'], capture_output=True, text=True, timeout=4, check=False)
            text = (proc.stdout or '').lower()
            if 'soft blocked: yes' in text or 'hard blocked: yes' in text:
                return False
            if 'soft blocked: no' in text or 'hard blocked: no' in text:
                return True
        except Exception:
            pass
    return False
