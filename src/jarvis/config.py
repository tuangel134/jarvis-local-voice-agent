from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from jarvis.utils.paths import ensure_dir, expand_path

DEFAULT_CONFIG_PATH = Path('~/.config/jarvis/config.yaml').expanduser()
DEFAULT_ENV_PATH = Path('~/.config/jarvis/.env').expanduser()
PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_CONFIG = PROJECT_ROOT / 'config.example.yaml'
EXAMPLE_ENV = PROJECT_ROOT / '.env.example'


class ConfigError(RuntimeError):
    pass


def create_default_config_if_missing() -> Path:
    ensure_dir(DEFAULT_CONFIG_PATH.parent)
    if not DEFAULT_CONFIG_PATH.exists():
        if EXAMPLE_CONFIG.exists():
            shutil.copy(EXAMPLE_CONFIG, DEFAULT_CONFIG_PATH)
        else:
            DEFAULT_CONFIG_PATH.write_text('assistant:\n  name: Jarvis\n', encoding='utf-8')
    if not DEFAULT_ENV_PATH.exists():
        if EXAMPLE_ENV.exists():
            shutil.copy(EXAMPLE_ENV, DEFAULT_ENV_PATH)
        else:
            DEFAULT_ENV_PATH.write_text('GROQ_API_KEY=\nOPENAI_API_KEY=\nOPENROUTER_API_KEY=\nELEVENLABS_API_KEY=\n', encoding='utf-8')
    return DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = expand_path(path) if path else create_default_config_if_missing()
    assert cfg_path is not None
    if not cfg_path.exists():
        raise ConfigError(f'No existe config: {cfg_path}')
    load_dotenv(DEFAULT_ENV_PATH)
    load_dotenv(Path.cwd() / '.env')
    data = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
    _expand_known_paths(data)
    _ensure_runtime_dirs(data)
    return data


def _expand_known_paths(data: dict[str, Any]) -> None:
    paths = data.get('paths', {})
    for key, value in list(paths.items()):
        if isinstance(value, str):
            paths[key] = str(Path(value).expanduser())
    logging = data.get('logging', {})
    if isinstance(logging.get('file'), str):
        logging['file'] = str(Path(logging['file']).expanduser())
    piper = data.get('tts', {}).get('piper', {})
    for key in ('model_path', 'config_path'):
        if isinstance(piper.get(key), str):
            piper[key] = str(Path(piper[key]).expanduser())


def _ensure_runtime_dirs(data: dict[str, Any]) -> None:
    paths = data.get('paths', {})
    for key in ('data_dir', 'config_dir', 'logs_dir', 'notes_dir', 'voices_dir', 'temp_dir'):
        if paths.get(key):
            ensure_dir(paths[key])


def get_env_from_config(config: dict[str, Any], provider_key: str, default_env: str) -> str:
    env_name = config.get(provider_key, {}).get('api_key_env', default_env)
    return os.getenv(env_name, '')
