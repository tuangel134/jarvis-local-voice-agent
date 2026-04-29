from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def setup_logger(config: dict[str, Any], name: str = 'jarvis') -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    log_cfg = config.get('logging', {})
    level_name = str(log_cfg.get('level', 'INFO')).upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')

    log_file = Path(log_cfg.get('file', '~/.local/share/jarvis/logs/jarvis.log')).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=int(log_cfg.get('max_bytes', 5_242_880)),
        backupCount=int(log_cfg.get('backup_count', 3)),
        encoding='utf-8',
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level)
    logger.addHandler(console)
    return logger
