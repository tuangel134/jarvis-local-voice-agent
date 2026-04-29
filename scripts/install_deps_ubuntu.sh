#!/usr/bin/env bash
set -euo pipefail
sudo apt update
sudo apt install -y \
  python3-venv python3-pip portaudio19-dev ffmpeg espeak-ng curl git \
  build-essential libsndfile1 libsndfile1-dev pulseaudio-utils alsa-utils
