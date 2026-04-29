#!/usr/bin/env bash
set -euo pipefail

echo "=== Dispositivos ALSA ==="
arecord -l || true
aplay -l || true

echo
if command -v pactl >/dev/null 2>&1; then
  echo "=== Fuentes PulseAudio/PipeWire ==="
  pactl list short sources || true
  echo
  echo "=== Salidas PulseAudio/PipeWire ==="
  pactl list short sinks || true
fi

echo
python3 - <<'PY_AUDIO_CHECK'
try:
    import sounddevice as sd
    print("=== sounddevice devices ===")
    print(sd.query_devices())
except Exception as e:
    print(f"No se pudo consultar sounddevice: {e}")
PY_AUDIO_CHECK
