#!/usr/bin/env bash
set -euo pipefail
MODEL="${1:-qwen2.5:3b}"
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama no está instalado. Instálalo con:"
  echo "curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi
ollama pull "$MODEL"
echo "Modelo descargado: $MODEL"
