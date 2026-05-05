# JARVIS LOCAL VOICE AGENT ( aun en mejora, recibira actualizacion pronto y una demaciado grande )

Jarvis Local Voice Agent es un asistente de voz local-first para Linux, Zorin OS y Ubuntu. Se controla desde terminal con `jarvis enable` y `jarvis disable`, escucha wake words como `hey jarvis`, transcribe tu voz, detecta intención, ejecuta skills seguras en tu PC y responde por los altavoces.

Diseñado para Angel, Zorin OS/Ubuntu noble, Ollama local, Groq API opcional, Piper como voz local rápida y fallbacks para que el daemon no se rompa si falla un proveedor.

## Flujo principal

1. Ejecutas:

```bash
jarvis enable
```

2. Jarvis queda escuchando en segundo plano.

3. Dices:

```text
hey jarvis abre youtube
```

4. Jarvis detecta la activación, entiende la intención, abre YouTube y responde:

```text
Abriendo YouTube.
```

5. Para apagar la escucha:

```bash
jarvis disable
```

Cuando está disabled, el daemon no escucha el micrófono.

## Estructura

```text
jarvis-local-voice-agent/
├── README.md
├── install.sh
├── uninstall.sh
├── requirements.txt
├── pyproject.toml
├── .env.example
├── config.example.yaml
├── jarvis
├── systemd/
│   └── jarvis.service
├── scripts/
│   ├── install_deps_ubuntu.sh
│   ├── check_audio.sh
│   ├── download_models.sh
│   └── download_voices.sh
├── src/
│   └── jarvis/
│       ├── __init__.py
│       ├── main.py
│       ├── cli.py
│       ├── daemon.py
│       ├── config.py
│       ├── logger.py
│       ├── state.py
│       ├── audio/
│       │   ├── microphone.py
│       │   ├── speaker.py
│       │   ├── vad.py
│       │   ├── wakeword.py
│       │   └── recorder.py
│       ├── stt/
│       │   ├── base.py
│       │   ├── faster_whisper_stt.py
│       │   ├── whispercpp_stt.py
│       │   └── factory.py
│       ├── tts/
│       │   ├── base.py
│       │   ├── piper_tts.py
│       │   ├── coqui_tts.py
│       │   ├── elevenlabs_tts.py
│       │   ├── openai_tts.py
│       │   ├── system_tts.py
│       │   └── manager.py
│       ├── llm/
│       │   ├── base.py
│       │   ├── ollama_provider.py
│       │   ├── groq_provider.py
│       │   ├── openai_provider.py
│       │   ├── openrouter_provider.py
│       │   └── router.py
│       ├── brain/
│       │   ├── intent_classifier.py
│       │   ├── planner.py
│       │   ├── executor.py
│       │   ├── response_builder.py
│       │   └── memory.py
│       ├── skills/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── browser.py
│       │   ├── system.py
│       │   ├── files.py
│       │   ├── apps.py
│       │   ├── notes.py
│       │   ├── services.py
│       │   ├── reminders.py
│       │   └── shell_safe.py
│       └── utils/
│           ├── shell.py
│           ├── paths.py
│           ├── text.py
│           └── security.py
└── tests/
    ├── test_intents.py
    ├── test_router.py
    ├── test_skills.py
    └── test_tts_fallback.py
```

## Instalación

```bash
cd jarvis-local-voice-agent
chmod +x install.sh
./install.sh
```

El instalador hace esto:

- Verifica Python 3.10+.
- Instala paquetes apt necesarios: `python3-venv`, `python3-pip`, `portaudio19-dev`, `ffmpeg`, `espeak-ng`, `curl`, `git`, `build-essential`, `libsndfile1`, `alsa-utils`.
- Crea venv en `~/.local/share/jarvis/venv`.
- Instala dependencias Python.
- Crea carpetas de datos, logs, voces, temporales y notas.
- Copia `config.example.yaml` a `~/.config/jarvis/config.yaml` si no existe.
- Copia `.env.example` a `~/.config/jarvis/.env` si no existe.
- Instala comando global `~/.local/bin/jarvis`.
- Instala servicio systemd user en `~/.config/systemd/user/jarvis.service`.

Si `~/.local/bin` no está en tu PATH, agrega a `~/.bashrc` o `~/.zshrc`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Pruebas iniciales

```bash
jarvis doctor
jarvis test-tts
jarvis test-mic
jarvis enable
jarvis status
jarvis disable
```

`jarvis test-tts` debe decir por altavoces:

```text
Hola, soy Jarvis. La voz funciona correctamente.
```

`jarvis test-mic` graba 5 segundos, transcribe y muestra el texto.

## Comandos de terminal

```bash
jarvis enable
jarvis disable
jarvis status
jarvis restart
jarvis logs
jarvis test-mic
jarvis test-tts
jarvis say "hola angel"
jarvis config
jarvis doctor
```

### `jarvis enable`

Activa estado enabled, arranca el servicio systemd user y deja Jarvis escuchando wake word.

### `jarvis disable`

Cambia estado a disabled y detiene el servicio. El micrófono deja de escucharse.

### `jarvis status`

Muestra estado, servicio, STT, LLM, TTS, micrófono, altavoz, logs, config y rutas.

### `jarvis logs`

Muestra logs recientes desde `~/.local/share/jarvis/logs/jarvis.log`.

### `jarvis doctor`

Revisa instalación, audio, ffmpeg, espeak-ng, Piper, modelo Piper, Ollama, variables API y servicio systemd.

## Wake word

Wake words configuradas por defecto:

- `hey jarvis`
- `oye jarvis`
- `jarvis`

Ejemplos:

```text
hey jarvis abre youtube
oye jarvis qué hora es
jarvis abre mi carpeta de descargas
hey jarvis revisa si jellyfin está activo
hey jarvis usa la IA avanzada para analizar este error
```

La implementación incluida usa fallback offline por STT: graba chunks cortos, transcribe con faster-whisper y detecta las frases. Es más pesado que un wake-word neural dedicado, pero funciona sin depender de nube. Puedes agregar openWakeWord después creando otro detector en `src/jarvis/audio/wakeword.py`.

## STT: voz a texto

Proveedor principal:

```yaml
stt:
  provider: "faster-whisper"
  model: "base"
  device: "cpu"
  compute_type: "int8"
  language: "es"
```

Modelos recomendados:

- `tiny`: más rápido, menos preciso.
- `base`: equilibrio recomendado.
- `small`: mejor precisión, más lento.
- `medium`: pesado en CPU.

Para cambiarlo:

```bash
nano ~/.config/jarvis/config.yaml
```

Edita:

```yaml
stt:
  model: "small"
```

## TTS: voz de Jarvis

El sistema de voz tiene providers intercambiables:

- Piper local por defecto.
- Coqui/XTTS local opcional.
- ElevenLabs opcional por API.
- OpenAI TTS opcional por API.
- fallback del sistema con espeak-ng/spd-say.

### Piper local

Config default:

```yaml
tts:
  provider: "piper"
  fallback: "espeak"
  piper:
    enabled: true
    binary: "piper"
    voice: "es_ES-davefx-medium"
    model_path: "~/.local/share/jarvis/voices/piper/es_ES-davefx-medium.onnx"
    config_path: "~/.local/share/jarvis/voices/piper/es_ES-davefx-medium.onnx.json"
```

Descargar voz española:

```bash
bash scripts/download_voices.sh
```

O voz mexicana:

```bash
bash scripts/download_voices.sh es_MX-ald-medium
```

Si usas otra voz, cambia en `~/.config/jarvis/config.yaml`:

```yaml
tts:
  piper:
    voice: "es_MX-ald-medium"
    model_path: "~/.local/share/jarvis/voices/piper/es_MX-ald-medium.onnx"
    config_path: "~/.local/share/jarvis/voices/piper/es_MX-ald-medium.onnx.json"
```

Piper debe estar instalado como binario `piper`. Si no está, Jarvis usa fallback `espeak-ng`.

### Coqui/XTTS opcional

Instala opcional:

```bash
~/.local/share/jarvis/venv/bin/pip install TTS
```

Activa:

```yaml
tts:
  provider: "coqui"
  coqui:
    enabled: true
    model: "tts_models/multilingual/multi-dataset/xtts_v2"
    language: "es"
    device: "cpu"
```

Si Coqui falla, Jarvis cae a Piper y luego a espeak-ng.

### ElevenLabs opcional

Edita `~/.config/jarvis/.env`:

```bash
ELEVENLABS_API_KEY=tu_key
```

Config:

```yaml
tts:
  provider: "elevenlabs"
  elevenlabs:
    enabled: true
    voice_id: "tu_voice_id"
    model: "eleven_multilingual_v2"
```

### OpenAI TTS opcional

Edita `~/.config/jarvis/.env`:

```bash
OPENAI_API_KEY=tu_key
```

Config:

```yaml
tts:
  provider: "openai"
  openai_tts:
    enabled: true
    model: "gpt-4o-mini-tts"
    voice: "alloy"
```

La API de audio speech de OpenAI acepta modelos de TTS como `gpt-4o-mini-tts`, `tts-1` y `tts-1-hd` según la documentación actual de audio speech.

## LLM local con Ollama

Instalar Ollama:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Descargar modelo default:

```bash
ollama pull qwen2.5:3b
```

O usando script:

```bash
bash scripts/download_models.sh
```

Modelos pequeños recomendados:

```bash
ollama pull qwen2.5:3b
ollama pull llama3.2:3b
ollama pull phi3:mini
ollama pull gemma2:2b
```

Cambiar modelo local:

```yaml
llm:
  local_model: "llama3.2:3b"
```

## Modelo pesado por API

Default:

```yaml
llm:
  heavy_provider: "groq"
  heavy_model: "llama-3.3-70b-versatile"
```

Configura Groq en `~/.config/jarvis/.env`:

```bash
GROQ_API_KEY=tu_key
```

OpenAI opcional:

```yaml
llm:
  heavy_provider: "openai"
openai:
  model: "gpt-4o-mini"
```

OpenRouter opcional:

```yaml
llm:
  heavy_provider: "openrouter"
openrouter:
  model: "meta-llama/llama-3.1-70b-instruct"
```

El modelo remoto nunca ejecuta comandos directamente. Solo razona y devuelve respuesta/plan. La ejecución local la controla `Executor` y las skills con reglas de seguridad.

## Router local/API

Tareas simples usan reglas directas, skills o modelo local:

- abrir YouTube
- abrir navegador
- abrir carpeta
- decir hora
- decir fecha
- buscar archivos
- abrir app permitida
- crear nota
- leer nota
- revisar servicio
- conversación simple

Tareas pesadas usan API si está configurada:

- programar
- analizar logs largos
- explicar errores complejos
- escribir código
- crear planes largos
- investigar
- resumir archivos grandes
- generar proyectos completos
- debugging avanzado

Frases que fuerzan remoto:

```text
usa la IA avanzada
usa el modelo potente
esto es pesado
analiza este error
programa
crea una app
genera código
revisa este log
```

## Skills incluidas

### BrowserSkill

Abre URLs permitidas con `xdg-open`.

Ejemplos:

```text
hey jarvis abre youtube
hey jarvis abre google
hey jarvis abre chatgpt
hey jarvis abre github
```

### AppsSkill

Abre apps permitidas:

- firefox
- google-chrome
- chromium
- code
- nautilus
- gnome-terminal

Config en `security.allowed_apps` y `security.app_aliases`.

### FilesSkill

Abre carpetas y busca archivos en:

- Descargas
- Documentos
- Escritorio
- Videos
- Imágenes
- Música

No borra archivos en v1.

### SystemSkill

Responde hora, fecha y estado de CPU/memoria/disco.

### ServicesSkill

Revisa servicios:

- jellyfin
- immich
- docker
- ssh

### NotesSkill

Crea notas markdown en `~/NotasJarvis`.

```text
hey jarvis crea una nota que diga revisar build de Expo
```

### RemindersSkill

Guarda recordatorios locales en JSON.

### ShellSafeSkill

Ejecuta solo comandos permitidos:

- `ls`
- `pwd`
- `df -h`
- `free -h`
- `uptime`
- `systemctl is-active SERVICIO`
- `xdg-open URL/RUTA segura`
- `find` limitado a HOME
- `cat` para archivos dentro de HOME
- `grep` simple

Bloquea patrones peligrosos como:

- `rm -rf`
- `sudo`
- `dd`
- `mkfs`
- `shutdown`
- `reboot`
- `chmod -R 777`
- `chown -R`
- pipes hacia shell
- rutas `/etc`, `/boot`, `/usr`

## Seguridad

Jarvis está hecho para controlar tu PC, pero v1 evita acciones destructivas por voz. El archivo `src/jarvis/utils/security.py` valida comandos, URLs, apps y rutas. En v1 no hay borrado de archivos por voz.

Mensaje ante acción peligrosa:

```text
Eso puede ser peligroso. No lo voy a ejecutar sin confirmación manual.
```

## Logs

Ruta default:

```bash
~/.local/share/jarvis/logs/jarvis.log
```

Ver logs:

```bash
jarvis logs
```

Se registra:

- inicio/apagado
- enable/disable
- wake word detectada
- texto transcrito
- intención detectada
- skill ejecutada
- proveedor LLM usado
- proveedor TTS usado
- errores y fallbacks

No se guarda audio permanentemente salvo que `assistant.debug: true`.

## Solución de problemas

### No hay micrófono

```bash
bash scripts/check_audio.sh
jarvis test-mic
```

Revisa permisos de audio, PipeWire/PulseAudio y dispositivo default.

### No habla

```bash
jarvis test-tts
jarvis doctor
```

Instala fallback:

```bash
sudo apt install espeak-ng ffmpeg alsa-utils pulseaudio-utils
```

### Piper falla

Jarvis cae a espeak-ng. Para corregir Piper:

```bash
bash scripts/download_voices.sh
jarvis doctor
```

Verifica que `model_path` y `config_path` existan.

### Ollama no responde

```bash
ollama serve
ollama pull qwen2.5:3b
```

### Falta GROQ_API_KEY

No rompe Jarvis. Solo las tareas pesadas no podrán usar Groq y el router intentará responder con Ollama local.

## Agregar una nueva skill

1. Crea archivo:

```bash
src/jarvis/skills/mi_skill.py
```

2. Usa esta plantilla:

```python
from __future__ import annotations

from typing import Any
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill


class MiSkill(Skill):
    name = "mi_skill"
    description = "Describe qué hace."

    def can_handle(self, intent: Intent) -> bool:
        return intent.name == "mi_intencion"

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": "Acción completada."}
```

3. Regístrala en `src/jarvis/skills/registry.py`:

```python
from jarvis.skills.mi_skill import MiSkill

self.skills = [
    BrowserSkill(config),
    MiSkill(config),
]
```

4. Si necesitas nueva intención, edita `src/jarvis/brain/intent_classifier.py`.

## Desinstalación

```bash
chmod +x uninstall.sh
./uninstall.sh
```

El desinstalador detiene y deshabilita el servicio, borra el comando global y pregunta antes de borrar config, datos, logs y notas.

## Uso final esperado

```bash
cd jarvis-local-voice-agent
chmod +x install.sh
./install.sh
jarvis test-tts
jarvis test-mic
jarvis enable
```

Luego di:

```text
hey jarvis abre youtube
```

Jarvis debe abrir YouTube y responder por altavoces:

```text
Abriendo YouTube.
```
