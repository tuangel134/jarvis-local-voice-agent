#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$HOME/.local/share/jarvis"
CONFIG_DIR="$HOME/.config/jarvis"
LOGS_DIR="$DATA_DIR/logs"
TMP_DIR="$DATA_DIR/tmp"
VOICES_DIR="$DATA_DIR/voices/piper"
VENV_DIR="$DATA_DIR/venv"
BIN_DIR="$HOME/.local/bin"
SERVICE_DIR="$HOME/.config/systemd/user"
NOTES_DIR="$HOME/NotasJarvis"

say_step() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33mADVERTENCIA: %s\033[0m\n' "$1"; }

say_step "Verificando Python"
if ! command -v python3 >/dev/null 2>&1; then
  echo "No se encontró python3. Instala Python 3.10 o superior."
  exit 1
fi
python3 - <<'PY_INSTALL_CHECK'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ requerido")
print(f"Python OK: {sys.version.split()[0]}")
PY_INSTALL_CHECK

say_step "Instalando dependencias del sistema"
if command -v apt >/dev/null 2>&1; then
  sudo apt update
  sudo apt install -y \
    python3-venv python3-pip portaudio19-dev ffmpeg espeak-ng curl git \
    build-essential libsndfile1 libsndfile1-dev pulseaudio-utils alsa-utils
else
  warn "No se detectó apt. Instala manualmente: python3-venv python3-pip portaudio19-dev ffmpeg espeak-ng curl git build-essential libsndfile1"
fi

say_step "Creando carpetas"
mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$LOGS_DIR" "$TMP_DIR" "$VOICES_DIR" "$BIN_DIR" "$SERVICE_DIR" "$NOTES_DIR"

say_step "Creando entorno virtual"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip wheel setuptools

say_step "Instalando Jarvis y dependencias Python"
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
"$VENV_DIR/bin/pip" install -e "$PROJECT_DIR"

say_step "Copiando configuración"
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
  cp "$PROJECT_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
  echo "Creado: $CONFIG_DIR/config.yaml"
else
  echo "Ya existe: $CONFIG_DIR/config.yaml"
fi
if [[ ! -f "$CONFIG_DIR/.env" ]]; then
  cp "$PROJECT_DIR/.env.example" "$CONFIG_DIR/.env"
  echo "Creado: $CONFIG_DIR/.env"
else
  echo "Ya existe: $CONFIG_DIR/.env"
fi

say_step "Instalando comando global jarvis"
cat > "$BIN_DIR/jarvis" <<'JARVIS_WRAPPER'
#!/usr/bin/env bash
set -euo pipefail

VENV="${JARVIS_VENV:-$HOME/.local/share/jarvis/venv}"

if [[ -x "$VENV/bin/python3" ]]; then
  PY="$VENV/bin/python3"
elif [[ -x "$VENV/bin/python" ]]; then
  PY="$VENV/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "ERROR: No encontré Python. Instala python3 o reinstala Jarvis." >&2
  exit 1
fi

exec "$PY" -m jarvis.cli "$@"
JARVIS_WRAPPER
chmod +x "$BIN_DIR/jarvis"
hash -r 2>/dev/null || true

say_step "Instalando servicio systemd user"
cp "$PROJECT_DIR/systemd/jarvis.service" "$SERVICE_DIR/jarvis.service"
systemctl --user daemon-reload || warn "No se pudo recargar systemd user. Puede que falte sesión systemd de usuario."

say_step "Inicializando estado"
"$BIN_DIR/jarvis" config >/dev/null || true
"$BIN_DIR/jarvis" disable --no-stop-service >/dev/null || true


say_step "Configuración inicial de audio"
JARVIS_INSTALL_AUDIO_MODE="${JARVIS_INSTALL_AUDIO:-auto}"
INTERACTIVE_INSTALL=0
if [[ -t 0 && -t 1 ]]; then
  INTERACTIVE_INSTALL=1
fi

run_audio_quick_setup() {
  "$BIN_DIR/jarvis" audio-quick-setup
}


run_audio_test_wizard() {
  if [[ ! -x "$BIN_DIR/jarvis" ]]; then
    warn "No encontré $BIN_DIR/jarvis para ejecutar la prueba guiada de audio."
    return 1
  fi
  if [[ ! -t 0 ]]; then
    warn "Sin terminal interactiva: omitiendo prueba guiada de audio."
    return 0
  fi
  echo
  echo "Prueba guiada de audio"
  echo "  1) Validar TTS y micrófono ahora"
  echo "  2) Omitir por ahora"
  read -r -p "Elige [1-2]: " audio_test_choice
  case "${audio_test_choice:-1}" in
    1)
      "$BIN_DIR/jarvis" audio-test --guided --seconds 3 || warn "La prueba guiada de audio no quedó OK. Puedes repetirla luego con: jarvis audio-test"
      ;;
    *)
      echo "Prueba de audio omitida. Puedes ejecutarla luego con: jarvis audio-test"
      ;;
  esac
}

run_audio_advanced_setup() {
  "$BIN_DIR/jarvis" audio-setup
}

if [[ "$JARVIS_INSTALL_AUDIO_MODE" == "skip" ]]; then
  echo "Omitiendo configuración inicial de audio (JARVIS_INSTALL_AUDIO=skip)."
elif [[ "$JARVIS_INSTALL_AUDIO_MODE" == "quick" ]]; then
  run_audio_quick_setup || warn "No se completó la configuración rápida de audio."
elif [[ "$JARVIS_INSTALL_AUDIO_MODE" == "advanced" ]]; then
  run_audio_advanced_setup || warn "No se completó la configuración avanzada de audio."
elif [[ "$JARVIS_INSTALL_AUDIO_MODE" == "required" ]]; then
  if [[ "$INTERACTIVE_INSTALL" -ne 1 ]]; then
    echo "JARVIS_INSTALL_AUDIO=required necesita una terminal interactiva."
    exit 1
  fi
  while true; do
    printf '\nSe requiere configurar el audio antes de terminar la instalación.\n'
    printf '  1) Perfil simple recomendado\n'
    printf '  2) Modo avanzado\n'
    printf '  3) Volver a mostrar dispositivos\n'
    read -r -p "Elige una opción [1-3]: " audio_choice
    case "$audio_choice" in
      1)
        if run_audio_quick_setup; then
          break
        fi
        ;;
      2)
        if run_audio_advanced_setup; then
          break
        fi
        ;;
      3)
        "$BIN_DIR/jarvis" audio-devices || true
        ;;
      *)
        echo "Opción inválida."
        ;;
    esac
  done
elif [[ "$INTERACTIVE_INSTALL" -eq 1 ]]; then
  printf '\nJarvis puede configurar el audio ahora mismo para que el primer arranque sea más fácil.\n'
  printf '  1) Perfil simple recomendado\n'
  printf '  2) Modo avanzado\n'
  printf '  3) Omitir por ahora\n'
  read -r -p "Elige una opción [1-3] (Enter=1): " audio_choice
  audio_choice="${audio_choice:-1}"
  case "$audio_choice" in
    1)
      if run_audio_quick_setup; then
      run_audio_test_wizard
    else
      warn "No se completó la configuración rápida de audio. Puedes repetirla luego con: jarvis audio-quick-setup"
    fi
      ;;
    2)
      if run_audio_advanced_setup; then
      run_audio_test_wizard
    else
      warn "No se completó la configuración avanzada de audio. Puedes repetirla luego con: jarvis audio-setup"
    fi
      ;;
    3)
      echo "Audio omitido por ahora. Puedes configurarlo después con: jarvis audio-quick-setup"
      ;;
    *)
      warn "Opción inválida; se omite la configuración de audio."
      echo "Puedes configurarlo después con: jarvis audio-quick-setup"
      ;;
  esac
else
  echo "Instalación no interactiva: se omite la configuración de audio."
  echo "Configúrala después con: jarvis audio-quick-setup"
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  warn "$BIN_DIR no parece estar en tu PATH. Agrega esta línea a ~/.bashrc o ~/.zshrc:"
  echo "export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

cat <<'FINAL_INSTRUCTIONS'

Instalación completada.

Prueba:

jarvis audio-quick-setup
jarvis test-tts
jarvis test-mic
jarvis doctor
jarvis enable
jarvis status
jarvis disable

Opcional para voz Piper natural en español:

bash scripts/download_voices.sh

Opcional para Ollama local:

bash scripts/download_models.sh


Si omitiste la configuración inicial de audio, puedes retomarla con:

jarvis audio-quick-setup
jarvis audio-setup
jarvis audio-devices

FINAL_INSTRUCTIONS
