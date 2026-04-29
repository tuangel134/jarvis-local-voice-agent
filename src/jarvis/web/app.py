from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from jarvis.web.bridge import bridge

STATIC = Path(__file__).parent / 'static'
APP_TITLE = 'JARVIS Reactive UI'
clients: set[WebSocket] = set()
app = FastAPI(title=APP_TITLE)
app.mount('/static', StaticFiles(directory=str(STATIC)), name='static')

journal_task: asyncio.Task | None = None
speaker_task: asyncio.Task | None = None
idle_task: asyncio.Task | None = None


def _mode_name() -> str:
    if os.getenv('JARVIS_WEB_DEV_MODE', '0') == '1':
        return 'dev-bridge'
    return 'live-journal bridge'


@app.get('/')
def index() -> FileResponse:
    return FileResponse(STATIC / 'index.html')


@app.get('/api/status')
def status() -> dict[str, Any]:
    snap = bridge.snapshot()
    return {
        'name': APP_TITLE,
        'version': '0.2.0-web2',
        'state': snap['state'],
        'mode': _mode_name(),
        'orb_profile': 'jarvis-ironman-live',
        'intent': snap['intent'],
        'action': snap['action'],
        'subtitle': snap['subtitle'],
        'log_lines': len(snap['logs']),
        'ts': time.time(),
    }


@app.get('/api/logs')
def logs() -> dict[str, Any]:
    return {'logs': bridge.snapshot()['logs']}


@app.post('/api/chat')
async def chat(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get('text', '')).strip()
    await broadcast({'type': 'chat.user', 'text': text, 'ts': time.time()})
    await push_event({'type': 'state', 'state': 'thinking'})
    result = await bridge.handle_text(text)
    if result.get('intent'):
        bridge.set_intent(result['intent'])
    if result.get('action'):
        bridge.set_action(result['action'])
    bridge.set_subtitle(result.get('text', ''))
    await broadcast({
        'type': 'chat.assistant',
        'text': result.get('text', ''),
        'intent': result.get('intent', ''),
        'action': result.get('action', ''),
        'ts': time.time(),
    })
    await push_event({'type': 'subtitle', 'text': result.get('text', '')})
    await push_event({'type': 'state', 'state': result.get('state', 'speaking')})
    if result.get('state', 'speaking') == 'speaking':
        start_speaking_pulse(3.0)
    return result


@app.post('/api/event')
async def push_event(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload or {})
    event_type = str(payload.get('type', 'event'))
    if event_type == 'state':
        bridge.set_state(str(payload.get('state', 'idle')))
    elif event_type == 'audio_level':
        bridge.set_audio_level(float(payload.get('level', 0.0)))
    elif event_type == 'intent':
        bridge.set_intent(str(payload.get('intent', '')))
    elif event_type == 'action':
        bridge.set_action(str(payload.get('action', '')))
    elif event_type == 'subtitle':
        bridge.set_subtitle(str(payload.get('text', '')))
    elif event_type == 'log':
        bridge.add_log(str(payload.get('text', '')))
    payload.setdefault('ts', time.time())
    await broadcast(payload)
    return {'ok': True, 'accepted': event_type}


@app.post('/api/demo')
async def demo() -> dict[str, Any]:
    asyncio.create_task(run_demo_sequence())
    return {'ok': True}


async def run_demo_sequence() -> None:
    sequence = [
        ({'type': 'state', 'state': 'listening'}, 0.8),
        ({'type': 'log', 'text': 'Wake word detectada por demo bridge'}, 0.1),
        ({'type': 'state', 'state': 'thinking'}, 0.7),
        ({'type': 'intent', 'intent': 'presence'}, 0.1),
        ({'type': 'subtitle', 'text': 'Aquí estoy, señor.'}, 0.1),
        ({'type': 'state', 'state': 'speaking'}, 0.2),
    ]
    for message, delay in sequence:
        await push_event(message)
        await asyncio.sleep(delay)
    start_speaking_pulse(3.0)


async def broadcast(message: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    for ws in clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


@app.websocket('/ws')
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    clients.add(ws)
    snap = bridge.snapshot()
    await ws.send_json({
        'type': 'hello',
        'name': APP_TITLE,
        'state': snap['state'],
        'amp': snap['amp'],
        'intent': snap['intent'],
        'action': snap['action'],
        'subtitle': snap['subtitle'],
        'logs': snap['logs'],
        'mode': _mode_name(),
        'ts': time.time(),
    })
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get('type')
            if msg_type == 'chat':
                await chat({'text': data.get('text', '')})
            elif msg_type == 'ping':
                await ws.send_json({'type': 'pong', 'ts': time.time()})
            elif msg_type == 'demo':
                asyncio.create_task(run_demo_sequence())
            elif msg_type == 'state':
                await push_event({'type': 'state', 'state': data.get('state', 'idle')})
            elif msg_type == 'audio_level':
                await push_event({'type': 'audio_level', 'level': data.get('level', 0.0)})
            elif msg_type == 'log':
                await push_event({'type': 'log', 'text': data.get('text', '')})
    except WebSocketDisconnect:
        clients.discard(ws)


def _journal_lines(limit: int = 80) -> list[str]:
    try:
        proc = subprocess.run(
            ['journalctl', '--user', '-u', 'jarvis', '-n', str(limit), '-o', 'cat'],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if proc.returncode != 0:
            return [f'[web-ui] journalctl devolvió código {proc.returncode}: {proc.stderr.strip()}']
        return [line for line in proc.stdout.splitlines() if line.strip()]
    except Exception as exc:
        return [f'[web-ui] no pude cargar logs iniciales: {exc}']


def _maybe_extract(pattern: str, line: str) -> str:
    match = re.search(pattern, line, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ''


async def _handle_journal_line(line: str) -> None:
    bridge.add_log(line)
    await broadcast({'type': 'log', 'text': line, 'ts': time.time()})

    low = line.lower()

    if 'wake word detectada' in low or 'wakeword' in low and ('detect' in low or 'retry' in low):
        bridge.set_state('listening')
        bridge.set_subtitle('Jarvis escuchando…')
        await broadcast({'type': 'state', 'state': 'listening', 'ts': time.time()})
    elif any(key in low for key in ['transcrib', 'intent', 'clasif', 'thinking', 'planner']):
        bridge.set_state('thinking')
        await broadcast({'type': 'state', 'state': 'thinking', 'ts': time.time()})
    elif any(key in low for key in ['kokoro', 'tts', 'reproduciendo', 'voice', 'hablando']):
        bridge.set_state('speaking')
        await broadcast({'type': 'state', 'state': 'speaking', 'ts': time.time()})
        start_speaking_pulse(3.2)
    elif any(key in low for key in ['esperando wake', 'jarvis listo', 'listo para escuchar']):
        bridge.set_state('idle')
        await broadcast({'type': 'state', 'state': 'idle', 'ts': time.time()})

    if 'echo guard' in low:
        bridge.set_subtitle('Echo Guard activo')
        await broadcast({'type': 'subtitle', 'text': 'Echo Guard activo', 'ts': time.time()})

    subtitle = _maybe_extract(r'(?:respuesta|reply)\s*[:=]\s*(.+)$', line)
    if subtitle:
        bridge.set_subtitle(subtitle)
        await broadcast({'type': 'subtitle', 'text': subtitle, 'ts': time.time()})
        bridge.set_state('speaking')
        await broadcast({'type': 'state', 'state': 'speaking', 'ts': time.time()})
        start_speaking_pulse(max(2.5, min(7.0, len(subtitle) * 0.055)))

    intent = _maybe_extract(r'(?:intent|match)\s*[:=]\s*([a-zA-Z0-9_.-]+)', line)
    if intent:
        bridge.set_intent(intent)
        await broadcast({'type': 'intent', 'intent': intent, 'ts': time.time()})

    action = _maybe_extract(r'(?:action)\s*[:=]\s*([a-zA-Z0-9_.-]+)', line)
    if action:
        bridge.set_action(action)
        await broadcast({'type': 'action', 'action': action, 'ts': time.time()})


async def _journal_loop() -> None:
    while True:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                'journalctl', '--user', '-u', 'jarvis', '-n', '0', '-f', '-o', 'cat',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await _handle_journal_line(line.decode(errors='ignore').rstrip())
        except asyncio.CancelledError:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2)
            raise
        except Exception as exc:
            bridge.add_log(f'[web-ui] error tailing journal: {exc}')
            await broadcast({'type': 'log', 'text': f'[web-ui] error tailing journal: {exc}', 'ts': time.time()})
        finally:
            if proc is not None and proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=2)
        await asyncio.sleep(1.5)


async def _idle_decay_loop() -> None:
    while True:
        await asyncio.sleep(5.0)
        snap = bridge.snapshot()
        if time.time() - snap['last_event_ts'] > 7 and snap['state'] == 'speaking':
            bridge.set_state('idle')
            await broadcast({'type': 'state', 'state': 'idle', 'ts': time.time()})


def start_speaking_pulse(duration: float = 3.2) -> None:
    global speaker_task

    async def _pulse() -> None:
        levels = [0.18, 0.34, 0.62, 0.28, 0.56, 0.22, 0.48, 0.16]
        end_at = time.time() + max(0.8, duration)
        i = 0
        while time.time() < end_at:
            level = levels[i % len(levels)]
            bridge.set_audio_level(level)
            await broadcast({'type': 'audio_level', 'level': level, 'ts': time.time()})
            i += 1
            await asyncio.sleep(0.12)
        bridge.set_audio_level(0.18)
        await broadcast({'type': 'audio_level', 'level': 0.18, 'ts': time.time()})

    if speaker_task and not speaker_task.done():
        speaker_task.cancel()
    speaker_task = asyncio.create_task(_pulse())


@app.on_event('startup')
async def on_startup() -> None:
    global journal_task, idle_task
    bridge.seed_logs(_journal_lines())
    journal_task = asyncio.create_task(_journal_loop())
    idle_task = asyncio.create_task(_idle_decay_loop())


@app.on_event('shutdown')
async def on_shutdown() -> None:
    for task in [journal_task, speaker_task, idle_task]:
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def run(host: str = '127.0.0.1', port: int = 7070, open_browser: bool = False) -> None:
    import uvicorn

    if open_browser:
        webbrowser.open(f'http://{host}:{port}')
    uvicorn.run('jarvis.web.app:app', host=host, port=port, reload=False)


if __name__ == '__main__':
    run(open_browser=True)
