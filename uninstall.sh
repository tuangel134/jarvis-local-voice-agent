#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="$HOME/.local/share/jarvis"
CONFIG_DIR="$HOME/.config/jarvis"
SERVICE="$HOME/.config/systemd/user/jarvis.service"
BIN="$HOME/.local/bin/jarvis"
NOTES_DIR="$HOME/NotasJarvis"

echo "Desinstalando Jarvis Local Voice Agent..."
systemctl --user stop jarvis 2>/dev/null || true
systemctl --user disable jarvis 2>/dev/null || true
rm -f "$SERVICE"
systemctl --user daemon-reload 2>/dev/null || true
rm -f "$BIN"

echo "Servicio y comando jarvis eliminados."
read -r -p "¿Borrar configuración en $CONFIG_DIR? [s/N]: " ans
if [[ "$ans" =~ ^[sS]$ ]]; then
  rm -rf "$CONFIG_DIR"
  echo "Configuración borrada."
fi

read -r -p "¿Borrar datos, venv, voces, logs en $DATA_DIR? [s/N]: " ans
if [[ "$ans" =~ ^[sS]$ ]]; then
  rm -rf "$DATA_DIR"
  echo "Datos borrados."
fi

read -r -p "¿Borrar notas en $NOTES_DIR? [s/N]: " ans
if [[ "$ans" =~ ^[sS]$ ]]; then
  rm -rf "$NOTES_DIR"
  echo "Notas borradas."
else
  echo "Notas conservadas en $NOTES_DIR"
fi

echo "Desinstalación completada."
