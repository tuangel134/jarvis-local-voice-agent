from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from jarvis.audio.microphone import Microphone
from jarvis.audio.recorder import Recorder
from jarvis.config import DEFAULT_CONFIG_PATH, DEFAULT_ENV_PATH, create_default_config_if_missing, load_config
from jarvis.logger import setup_logger
from jarvis.state import JarvisState
from jarvis.stt.factory import create_stt
from jarvis.tts.manager import TTSManager

app = typer.Typer(help='Jarvis Local Voice Agent')
console = Console()


def _run_systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['systemctl', '--user', *args], text=True, capture_output=True)


def _service_active() -> bool:
    res = _run_systemctl(['is-active', '--quiet', 'jarvis'])
    return res.returncode == 0


@app.command()
def enable() -> None:
    """Activa Jarvis y arranca el servicio de usuario."""
    create_default_config_if_missing()
    JarvisState().set_enabled(True)
    _run_systemctl(['enable', 'jarvis'])
    res = _run_systemctl(['start', 'jarvis'])
    if res.returncode != 0:
        console.print('[yellow]No se pudo arrancar systemd user automáticamente.[/yellow]')
        console.print(res.stderr.strip())
    console.print('Jarvis activado. Escuchando wake word: hey jarvis.')


@app.command()
def disable(stop_service: bool = typer.Option(True, '--stop-service/--no-stop-service')) -> None:
    """Desactiva Jarvis y deja de escuchar micrófono."""
    JarvisState().set_enabled(False)
    if stop_service:
        _run_systemctl(['stop', 'jarvis'])
    console.print('Jarvis desactivado. El micrófono ya no está siendo escuchado.')


@app.command()
def restart() -> None:
    """Reinicia el servicio de Jarvis."""
    JarvisState().set_enabled(True)
    res = _run_systemctl(['restart', 'jarvis'])
    if res.returncode == 0:
        console.print('Jarvis reiniciado.')
    else:
        console.print('[red]No se pudo reiniciar Jarvis.[/red]')
        console.print(res.stderr.strip())


@app.command()
def status() -> None:
    """Muestra estado, configuración, modelos y rutas."""
    cfg = load_config()
    st = JarvisState().read()
    table = Table(title='Estado de Jarvis')
    table.add_column('Campo')
    table.add_column('Valor')
    table.add_row('enabled', str(st.get('enabled')))
    table.add_row('servicio corriendo', str(_service_active()))
    table.add_row('pid', str(st.get('pid')))
    table.add_row('STT proveedor', cfg.get('stt', {}).get('provider', 'faster-whisper'))
    table.add_row('STT modelo', cfg.get('stt', {}).get('model', 'base'))
    table.add_row('LLM local', cfg.get('llm', {}).get('local_model', 'qwen2.5:3b'))
    table.add_row('Proveedor remoto', cfg.get('llm', {}).get('heavy_provider', 'groq'))
    table.add_row('Modelo remoto', cfg.get('llm', {}).get('heavy_model', 'llama-3.3-70b-versatile'))
    table.add_row('TTS actual', cfg.get('tts', {}).get('provider', 'piper'))
    table.add_row('Voz Piper', cfg.get('tts', {}).get('piper', {}).get('voice', ''))
    table.add_row('Micrófono', str(cfg.get('audio', {}).get('input_device', 'default')))
    table.add_row('Altavoz', str(cfg.get('audio', {}).get('output_device', 'default')))
    table.add_row('Log', str(cfg.get('logging', {}).get('file')))
    table.add_row('Config', str(DEFAULT_CONFIG_PATH))
    table.add_row('Env', str(DEFAULT_ENV_PATH))
    table.add_row('Datos', str(cfg.get('paths', {}).get('data_dir')))
    console.print(table)


@app.command()
def logs(
    lines: int = typer.Option(120, '--lines', '-n'),
    follow: bool = typer.Option(True, '--follow/--no-follow', '-f/-F'),
) -> None:
    """Muestra logs de Jarvis. Por defecto salen en tiempo real."""
    if follow:
        console.print('[cyan]Logs en vivo. Presiona Ctrl+C para salir.[/cyan]')
        subprocess.run([
            'journalctl',
            '--user',
            '-u',
            'jarvis',
            '-n',
            str(lines),
            '-f',
        ])
        return

    cfg = load_config()
    log_file = Path(cfg.get('logging', {}).get('file', '~/.local/share/jarvis/logs/jarvis.log')).expanduser()

    if log_file.exists():
        content = log_file.read_text(encoding='utf-8', errors='ignore').splitlines()[-lines:]
        console.print('\n'.join(content))
        return

    res = _run_systemctl(['status', 'jarvis', '--no-pager'])
    console.print(res.stdout or res.stderr or 'No hay logs todavía.')


@app.command('stop-music')
def stop_music() -> None:
    """Detiene la música reproducida por Jarvis."""
    pid_file = Path('~/.local/share/jarvis/music_player.pid').expanduser()
    stopped = False

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.killpg(pid, 15)
            stopped = True
        except Exception:
            try:
                os.kill(pid, 15)
                stopped = True
            except Exception:
                pass
        pid_file.unlink(missing_ok=True)

    try:
        subprocess.run(
            ['pkill', '-f', 'mpv.*Jarvis Music'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        stopped = True
    except Exception:
        pass

    console.print('Música detenida.' if stopped else 'No encontré música activa.')


@app.command('test-mic')
def test_mic(seconds: int = typer.Option(5, '--seconds', '-s')) -> None:
    """Graba unos segundos y transcribe para probar micrófono."""
    cfg = load_config()
    logger = setup_logger(cfg)
    recorder = Recorder(cfg)
    stt = create_stt(cfg, logger)
    console.print(f'Grabando {seconds} segundos. Habla ahora...')
    wav = recorder.record_test(seconds)
    console.print(f'Audio guardado temporalmente: {wav}')
    text = stt.transcribe(wav)
    if not cfg.get('assistant', {}).get('debug', False):
        Path(wav).unlink(missing_ok=True)
    console.print(f'Transcripción: [bold]{text or "(vacío)"}[/bold]')


@app.command('test-tts')
def test_tts() -> None:
    """Prueba la voz."""
    cfg = load_config()
    logger = setup_logger(cfg)
    TTSManager(cfg, logger).test()
    console.print('Prueba TTS ejecutada.')


@app.command()
def say(text: str) -> None:
    """Dice un texto por altavoces."""
    cfg = load_config()
    logger = setup_logger(cfg)
    TTSManager(cfg, logger).speak(text)



@app.command('audio-test')
def audio_test(
    seconds: int = typer.Option(3, '--seconds', '-s', help='Segundos de grabación para la prueba de micrófono.'),
    guided: bool = typer.Option(True, '--guided/--no-guided', help='Hace preguntas de validación al terminar cada prueba.'),
    skip_tts: bool = typer.Option(False, '--skip-tts', help='Omite la prueba de salida/TTS.'),
    skip_mic: bool = typer.Option(False, '--skip-mic', help='Omite la prueba de entrada/micrófono.'),
    phrase: str = typer.Option('hola jarvis prueba de micrófono', '--phrase', help='Frase sugerida para la prueba de micrófono.'),
    tts_text: str = typer.Option('Hola. Esta es una prueba de audio de Jarvis.', '--tts-text', help='Texto a reproducir en la prueba TTS.'),
) -> None:
    """Valida salida y micrófono con el perfil de audio actual."""
    from jarvis.audio.device_selector import resolve_input_device, resolve_output_device

    cfg = load_config()
    logger = setup_logger(cfg)
    wake = resolve_input_device(cfg, role='wake')
    stt_dev = resolve_input_device(cfg, role='stt')
    out = resolve_output_device(cfg)

    table = Table(title='Prueba de audio actual')
    table.add_column('Rol')
    table.add_column('Dispositivo')
    table.add_column('Motivo')
    table.add_row('wake', str(wake.get('name')), str(wake.get('reason')))
    table.add_row('stt', str(stt_dev.get('name')), str(stt_dev.get('reason')))
    table.add_row('tts', str(out.get('name')), str(out.get('reason')))
    console.print(table)

    heard_ok = True
    mic_ok = True
    transcribed = ''

    if not skip_tts:
        console.print('[cyan]Reproduciendo prueba TTS...[/cyan]')
        try:
            TTSManager(cfg, logger).speak(tts_text)
        except Exception:
            TTSManager(cfg, logger).test()
        if guided:
            console.print(f"[dim]Dispositivo esperado de salida: {out.get('name')}[/dim]")
            heard_ok = typer.confirm(f"¿Escuchaste la voz de Jarvis por este dispositivo esperado: {out.get('name')}?", default=True)

    if not skip_mic:
        recorder = Recorder(cfg)
        stt = create_stt(cfg, logger)
        console.print(f"[cyan]Voy a grabar {seconds} segundos. Di esta frase: [/cyan][bold]{phrase}[/bold]")
        wav = recorder.record_test(seconds)
        console.print(f'[dim]Audio temporal: {wav}[/dim]')
        try:
            transcribed = stt.transcribe(wav) or ''
        finally:
            if not cfg.get('assistant', {}).get('debug', False):
                Path(wav).unlink(missing_ok=True)
        console.print(f"Transcripción obtenida: [bold]{transcribed or '(vacío)'}[/bold]")
        if guided:
            mic_ok = typer.confirm('¿La transcripción se parece a lo que dijiste?', default=bool(transcribed))

    if heard_ok and mic_ok:
        console.print('[green]Prueba de audio OK.[/green]')
        return

    console.print('[yellow]La prueba de audio no quedó totalmente bien.[/yellow]')
    console.print('Sugerencias:')
    console.print('- Repite: [bold]jarvis audio-test[/bold]')
    console.print('- Reconfigura simple: [bold]jarvis audio-quick-setup[/bold]')
    console.print('- Reconfigura avanzada: [bold]jarvis audio-setup[/bold]')
    raise typer.Exit(code=2)


@app.command()
def config() -> None:
    """Muestra ruta de config y crea config si falta."""
    path = create_default_config_if_missing()
    console.print(f'Config: {path}')
    console.print(f'Env: {DEFAULT_ENV_PATH}')


@app.command()
def doctor() -> None:
    """Revisa instalación, audio, Piper, Ollama, APIs y systemd."""
    cfg = load_config()
    table = Table(title='Jarvis doctor')
    table.add_column('Chequeo')
    table.add_column('Estado')
    table.add_column('Detalle')

    def add(name: str, ok: bool, detail: str = '') -> None:
        table.add_row(name, '[green]OK[/green]' if ok else '[red]FALTA[/red]', detail)

    add('Python', True, os.sys.version.split()[0])
    add('Config', DEFAULT_CONFIG_PATH.exists(), str(DEFAULT_CONFIG_PATH))
    add('Env', DEFAULT_ENV_PATH.exists(), str(DEFAULT_ENV_PATH))
    add('ffmpeg', shutil.which('ffmpeg') is not None, shutil.which('ffmpeg') or 'sudo apt install ffmpeg')
    add('espeak-ng', shutil.which('espeak-ng') is not None, shutil.which('espeak-ng') or 'sudo apt install espeak-ng')
    add('piper', shutil.which(cfg.get('tts', {}).get('piper', {}).get('binary', 'piper')) is not None, 'pipx/pip/binario piper')
    piper_model = Path(cfg.get('tts', {}).get('piper', {}).get('model_path', '')).expanduser()
    add('modelo Piper', piper_model.exists(), str(piper_model))
    add('ollama', shutil.which('ollama') is not None, shutil.which('ollama') or 'curl -fsSL https://ollama.com/install.sh | sh')
    if shutil.which('ollama'):
        res = subprocess.run(['ollama', 'list'], text=True, capture_output=True, timeout=5)
        add('modelo local Ollama', cfg.get('llm', {}).get('local_model', '') in res.stdout, f"ollama pull {cfg.get('llm', {}).get('local_model', 'qwen2.5:3b')}")
    for env in ['GROQ_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ELEVENLABS_API_KEY']:
        add(env, bool(os.getenv(env)), 'opcional')
    add('systemd user service', Path('~/.config/systemd/user/jarvis.service').expanduser().exists(), '~/.config/systemd/user/jarvis.service')
    try:
        mic = Microphone(cfg)
        devices = mic.list_devices()
        add('sounddevice/audio', True, devices.splitlines()[0] if devices else 'dispositivos detectados')
    except Exception as exc:
        add('sounddevice/audio', False, str(exc))
    console.print(table)


if __name__ == '__main__':
    app()




@app.command("brain-test")
def brain_test(text: str) -> None:
    """Prueba el cerebro semántico v2 sin usar micrófono."""
    import json
    from jarvis.config import load_config
    from jarvis.brain.semantic_router import SemanticRouter
    from jarvis.brain.action_validator import ActionValidator

    cfg = load_config()
    router = SemanticRouter(cfg)
    validator = ActionValidator(cfg)

    action = router.parse(text)
    intent = validator.to_intent(action, text)

    result = {
        "input": text,
        "semantic_action": action.to_dict(),
        "legacy_intent": {
            "name": intent.name,
            "confidence": intent.confidence,
            "entities": intent.entities,
            "raw_text": intent.raw_text,
        },
    }

    console.print_json(json.dumps(result, ensure_ascii=False, indent=2))


# === JARVIS_V4126_AUDIO_SETUP_CLI_BEGIN ===

def _jarvis_v4126_render_audio_tables(scan: dict, cfg: dict) -> None:
    from rich.table import Table as _JarvisAudioTable

    audio = cfg.get('audio', {}) if isinstance(cfg, dict) else {}
    wake_name = str(audio.get('wake_input_device_name') or audio.get('input_device_name') or '').strip()
    stt_name = str(audio.get('stt_input_device_name') or audio.get('input_device_name') or '').strip()
    out_name = str(audio.get('output_device_name') or '').strip()

    in_table = _JarvisAudioTable(title='Entradas de audio')
    in_table.add_column('Índice')
    in_table.add_column('Nombre')
    in_table.add_column('Canales')
    in_table.add_column('SR')
    in_table.add_column('Flags')
    for item in scan.get('inputs', []):
        flags = []
        if item.get('is_default_input'):
            flags.append('default')
        if wake_name and wake_name == item.get('name'):
            flags.append('wake')
        if stt_name and stt_name == item.get('name'):
            flags.append('stt')
        if str(item.get('name')).strip().lower() == 'sysdefault':
            flags.append('route')
        in_table.add_row(
            str(item.get('index')),
            str(item.get('name')),
            str(item.get('max_input_channels')),
            str(int(float(item.get('default_samplerate') or 0))),
            ','.join(flags),
        )
    console.print(in_table)

    out_table = _JarvisAudioTable(title='Salidas de audio')
    out_table.add_column('Índice')
    out_table.add_column('Nombre')
    out_table.add_column('Canales')
    out_table.add_column('SR')
    out_table.add_column('Flags')
    for item in scan.get('outputs', []):
        flags = []
        if item.get('is_default_output'):
            flags.append('default')
        if out_name and out_name == item.get('name'):
            flags.append('tts')
        if str(item.get('name')).strip().lower() == 'sysdefault':
            flags.append('route')
        out_table.add_row(
            str(item.get('index')),
            str(item.get('name')),
            str(item.get('max_output_channels')),
            str(int(float(item.get('default_samplerate') or 0))),
            ','.join(flags),
        )
    console.print(out_table)


def _jarvis_v4127_print_routes(scan: dict, cfg: dict) -> None:
    audio = cfg.get('audio', {}) if isinstance(cfg, dict) else {}
    if scan.get('pactl_sources'):
        console.print('[cyan]PipeWire/Pulse sources:[/cyan]')
        for item in scan['pactl_sources']:
            flags = []
            if item.get('id') == scan.get('default_source_id') or item.get('name') == scan.get('default_source_name'):
                flags.append('default')
            if audio.get('pulse_source_name') == item.get('name') or str(audio.get('pulse_source_id') or '') == str(item.get('id')):
                flags.append('mic-route')
            suffix = f" [{' ,'.join(flags)}]" if flags else ''
            console.print(f"  {item['id']}: {item['name']}{suffix}")
    if scan.get('pactl_sinks'):
        console.print('[cyan]PipeWire/Pulse sinks:[/cyan]')
        for item in scan['pactl_sinks']:
            flags = []
            if item.get('id') == scan.get('default_sink_id') or item.get('name') == scan.get('default_sink_name'):
                flags.append('default')
            if audio.get('pulse_sink_name') == item.get('name') or str(audio.get('pulse_sink_id') or '') == str(item.get('id')):
                flags.append('tts-route')
            suffix = f" [{' ,'.join(flags)}]" if flags else ''
            console.print(f"  {item['id']}: {item['name']}{suffix}")


def _jarvis_v4127_valid_device(items: list[dict], value: str) -> bool:
    raw = str(value or '').strip()
    if raw == '' or raw.lower() == 'default':
        return True
    if raw.lower() == 'sysdefault':
        for item in items:
            if str(item.get('name', '')).strip().lower() == 'sysdefault':
                return True
    if raw.lstrip('-').isdigit():
        for item in items:
            if str(item.get('index')) == raw:
                return True
        return False
    lowered = raw.lower()
    for item in items:
        name = str(item.get('name', '')).strip().lower()
        if lowered == name or lowered in name or name in lowered:
            return True
    return False


def _jarvis_v4127_valid_route(items: list[dict], value: str) -> bool:
    raw = str(value or '').strip()
    if raw == '' or raw.lower() == 'default':
        return True
    lowered = raw.lower()
    if raw.lstrip('-').isdigit():
        for item in items:
            if str(item.get('id')) == raw:
                return True
    for item in items:
        name = str(item.get('name', '')).strip().lower()
        if lowered == name or lowered in name or name in lowered:
            return True
    return False


def _jarvis_v4127_abort_invalid(label: str, value: str) -> None:
    console.print(f'[red]{label} inválido:[/red] {value}')
    raise typer.Exit(code=2)


def _jarvis_v4127_pref_display(result: dict) -> str:
    if result.get('name'):
        return str(result['name'])
    if result.get('index') is not None:
        return str(result['index'])
    return 'default'


def _jarvis_v4128_render_audio_profiles(profiles: list[dict]) -> None:
    from rich.table import Table as _JarvisProfileTable

    table = _JarvisProfileTable(title='Perfiles sugeridos')
    table.add_column('#')
    table.add_column('Perfil')
    table.add_column('Mic')
    table.add_column('Salida')
    table.add_column('PipeWire')
    for idx, profile in enumerate(profiles, start=1):
        mic = profile.get('input_display') or ((profile.get('input') or {}).get('name')) or '—'
        out = profile.get('output_display') or ((profile.get('output') or {}).get('name')) or '—'
        route_bits = []
        if profile.get('source'):
            route_bits.append(f"src {profile['source']['id']}")
        if profile.get('sink'):
            route_bits.append(f"sink {profile['sink']['id']}")
        table.add_row(str(idx), str(profile.get('label')), str(mic), str(out), ' | '.join(route_bits) or '—')
    console.print(table)

@app.command('audio-devices')
def audio_devices() -> None:
    """Lista micrófonos y salidas de audio detectadas."""
    from jarvis.audio.device_selector import scan_audio_devices, scan_audio_profiles
    cfg = load_config()
    scan = scan_audio_devices()
    _jarvis_v4126_render_audio_tables(scan, cfg)
    _jarvis_v4127_print_routes(scan, cfg)
    profiles = scan_audio_profiles()
    if profiles:
        _jarvis_v4128_render_audio_profiles(profiles)


@app.command('audio-quick-setup')
def audio_quick_setup(
    profile: str = typer.Option('', '--profile', help='Número o nombre del perfil sugerido.'),
    restart_service: bool = typer.Option(False, '--restart', help='Reinicia Jarvis al guardar.'),
    same_stt_as_wake: bool = typer.Option(True, '--same-stt-as-wake/--separate-stt', help='Usa el mismo micro para wake y STT.'),
) -> None:
    """Onboarding simple: eliges un dispositivo humano y Jarvis configura audio."""
    from jarvis.audio.device_selector import scan_audio_devices, scan_audio_profiles, resolve_audio_profile, save_audio_profile

    cfg = load_config()
    scan = scan_audio_devices()
    profiles = scan_audio_profiles()
    _jarvis_v4126_render_audio_tables(scan, cfg)
    _jarvis_v4127_print_routes(scan, cfg)
    if not profiles:
        console.print('[red]No encontré perfiles de audio útiles.[/red]')
        raise typer.Exit(code=2)
    _jarvis_v4128_render_audio_profiles(profiles)

    choice = profile.strip() if isinstance(profile, str) else profile
    if choice in (None, ''):
        choice = typer.prompt('Perfil a usar para Jarvis (número o nombre)', default='1')
    selected = resolve_audio_profile(choice)
    if selected is None:
        console.print(f'[red]Perfil no encontrado:[/red] {choice}')
        raise typer.Exit(code=2)

    result = save_audio_profile(choice, restart=restart_service, same_stt_as_wake=same_stt_as_wake)
    console.print('[green]Perfil de audio guardado.[/green]')
    console.print(f"Perfil: {selected['label']}")
    console.print(f"Wake mic: {result['wake']['name']} (index={result['wake']['index']}, reason={result['wake']['reason']})")
    console.print(f"STT mic: {result['stt']['name']} (index={result['stt']['index']}, reason={result['stt']['reason']})")
    console.print(f"Salida TTS: {result['output']['name']} (index={result['output']['index']}, reason={result['output']['reason']})")
    if result.get('pulse_source_name'):
        console.print(f"PipeWire source: {result['pulse_source_name']}")
    if result.get('pulse_sink_name'):
        console.print(f"PipeWire sink: {result['pulse_sink_name']}")
    console.print(f"Config: {result['path']}")
    if restart_service:
        console.print('[green]Jarvis reiniciado.[/green]')
    else:
        console.print('Aplica con: [bold]jarvis disable && jarvis enable[/bold]')


@app.command('audio-setup')
def audio_setup(
    wake: str = typer.Option('', '--wake', help='Índice o nombre del micrófono para wake word.'),
    stt: str = typer.Option('', '--stt', help='Índice o nombre del micrófono para STT/recorder.'),
    output: str = typer.Option('', '--output', help='Índice o nombre de la salida de audio/TTS.'),
    pulse_source: str = typer.Option('', '--pulse-source', help='ID o nombre de PipeWire/Pulse source para micrófono.'),
    pulse_sink: str = typer.Option('', '--pulse-sink', help='ID o nombre de PipeWire/Pulse sink para salida/TTS.'),
    same_stt_as_wake: bool = typer.Option(True, '--same-stt-as-wake/--separate-stt', help='Usa el mismo micro para wake y STT.'),
    restart_service: bool = typer.Option(False, '--restart', help='Reinicia Jarvis al guardar.'),
) -> None:
    """Modo avanzado: escanea audio y guarda micrófonos/salida con validación real."""
    from jarvis.audio.device_selector import (
        scan_audio_devices,
        save_audio_preferences,
        resolve_input_device,
        resolve_output_device,
        scan_audio_profiles,
    )

    cfg = load_config()
    scan = scan_audio_devices()
    profiles = scan_audio_profiles()
    _jarvis_v4126_render_audio_tables(scan, cfg)
    _jarvis_v4127_print_routes(scan, cfg)
    if profiles:
        _jarvis_v4128_render_audio_profiles(profiles)
        console.print('[dim]Tip: para un flujo más simple usa [bold]jarvis audio-quick-setup[/bold].[/dim]')

    audio = cfg.get('audio', {}) if isinstance(cfg, dict) else {}
    current_wake = _jarvis_v4127_pref_display(resolve_input_device(cfg, role='wake'))
    current_stt = _jarvis_v4127_pref_display(resolve_input_device(cfg, role='stt'))
    current_out = _jarvis_v4127_pref_display(resolve_output_device(cfg))
    current_source = str(audio.get('pulse_source_id') or audio.get('pulse_source_name') or scan.get('default_source_id') or scan.get('default_source_name') or '')
    current_sink = str(audio.get('pulse_sink_id') or audio.get('pulse_sink_name') or scan.get('default_sink_id') or scan.get('default_sink_name') or '')

    pulse_source_value = pulse_source.strip() if isinstance(pulse_source, str) else pulse_source
    pulse_sink_value = pulse_sink.strip() if isinstance(pulse_sink, str) else pulse_sink
    wake_value = wake.strip() if isinstance(wake, str) else wake
    stt_value = stt.strip() if isinstance(stt, str) else stt
    output_value = output.strip() if isinstance(output, str) else output

    if pulse_source_value in (None, ''):
        pulse_source_value = typer.prompt('PipeWire/Pulse source para micrófono (id, nombre o blank)', default=current_source, show_default=bool(current_source))
    if pulse_sink_value in (None, ''):
        pulse_sink_value = typer.prompt('PipeWire/Pulse sink para audio/TTS (id, nombre o blank)', default=current_sink, show_default=bool(current_sink))

    route_input_default = current_wake
    route_output_default = current_out

    if wake_value in (None, ''):
        wake_value = typer.prompt('Micrófono para wake word (índice, nombre o default)', default=route_input_default)
    if same_stt_as_wake:
        stt_value = wake_value
    elif stt_value in (None, ''):
        stt_value = typer.prompt('Micrófono para STT/recorder (índice, nombre o default)', default=current_stt)
    if output_value in (None, ''):
        output_value = typer.prompt('Salida de audio/TTS (índice, nombre o default)', default=route_output_default)

    if not _jarvis_v4127_valid_route(scan.get('pactl_sources', []), pulse_source_value):
        _jarvis_v4127_abort_invalid('PipeWire/Pulse source', pulse_source_value)
    if not _jarvis_v4127_valid_route(scan.get('pactl_sinks', []), pulse_sink_value):
        _jarvis_v4127_abort_invalid('PipeWire/Pulse sink', pulse_sink_value)
    if not _jarvis_v4127_valid_device(scan.get('inputs', []), wake_value):
        _jarvis_v4127_abort_invalid('Micrófono wake', wake_value)
    if not same_stt_as_wake and not _jarvis_v4127_valid_device(scan.get('inputs', []), stt_value):
        _jarvis_v4127_abort_invalid('Micrófono STT', stt_value)
    if not _jarvis_v4127_valid_device(scan.get('outputs', []), output_value):
        _jarvis_v4127_abort_invalid('Salida TTS', output_value)

    result = save_audio_preferences(
        wake_pref=wake_value,
        stt_pref=stt_value,
        output_pref=output_value,
        pulse_source_pref=pulse_source_value,
        pulse_sink_pref=pulse_sink_value,
        same_stt_as_wake=same_stt_as_wake,
    )

    console.print('[green]Audio guardado.[/green]')
    console.print(f"Wake mic: {result['wake']['name']} (index={result['wake']['index']}, reason={result['wake']['reason']})")
    console.print(f"STT mic: {result['stt']['name']} (index={result['stt']['index']}, reason={result['stt']['reason']})")
    console.print(f"Salida TTS: {result['output']['name']} (index={result['output']['index']}, reason={result['output']['reason']})")
    if result.get('pulse_source_name'):
        console.print(f"PipeWire source: {result['pulse_source_name']}")
    if result.get('pulse_sink_name'):
        console.print(f"PipeWire sink: {result['pulse_sink_name']}")
    console.print(f"Config: {result['path']}")

    if restart_service:
        res = _run_systemctl(['restart', 'jarvis'])
        if res.returncode == 0:
            console.print('[green]Jarvis reiniciado.[/green]')
        else:
            console.print('[yellow]No pude reiniciar Jarvis automáticamente.[/yellow]')
            console.print(res.stderr.strip())
    else:
        console.print('Aplica con: [bold]jarvis disable && jarvis enable[/bold]')
# === JARVIS_V4126_AUDIO_SETUP_CLI_END ===

