#!/usr/bin/env bash
set -euo pipefail
VOICE_DIR="$HOME/.local/share/jarvis/voices/piper"
mkdir -p "$VOICE_DIR"
VOICE="${1:-es_ES-davefx-medium}"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"

case "$VOICE" in
  es_ES-davefx-medium)
    MODEL_URL="$BASE/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx?download=true"
    CONFIG_URL="$BASE/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json?download=true"
    ;;
  es_ES-sharvard-medium)
    MODEL_URL="$BASE/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx?download=true"
    CONFIG_URL="$BASE/es/es_ES/sharvard/medium/es_ES-sharvard-medium.onnx.json?download=true"
    ;;
  es_MX-ald-medium)
    MODEL_URL="$BASE/es/es_MX/ald/medium/es_MX-ald-medium.onnx?download=true"
    CONFIG_URL="$BASE/es/es_MX/ald/medium/es_MX-ald-medium.onnx.json?download=true"
    ;;
  *)
    echo "Voz no conocida en este script: $VOICE"
    echo "Opciones: es_ES-davefx-medium, es_ES-sharvard-medium, es_MX-ald-medium"
    exit 1
    ;;
esac

echo "Descargando voz Piper: $VOICE"
curl -L "$MODEL_URL" -o "$VOICE_DIR/$VOICE.onnx"
curl -L "$CONFIG_URL" -o "$VOICE_DIR/$VOICE.onnx.json"
echo "Voz instalada en $VOICE_DIR"
echo "Actualiza ~/.config/jarvis/config.yaml si usaste una voz distinta a la default."
