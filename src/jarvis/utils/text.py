from __future__ import annotations

import re
import unicodedata
from typing import Iterable


def normalize(text: str) -> str:
    text = text.strip().lower()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def contains_any(text: str, needles: Iterable[str]) -> bool:
    n = normalize(text)
    return any(normalize(x) in n for x in needles)


def strip_wake_word(text: str, wake_words: Iterable[str]) -> tuple[bool, str]:
    normalized = normalize(text)
    for wake in sorted(wake_words, key=len, reverse=True):
        w = normalize(wake)
        idx = normalized.find(w)
        if idx >= 0:
            after = normalized[idx + len(w):].strip(' ,.:;')
            return True, after
    return False, text.strip()


def split_for_tts(text: str, max_chars: int = 280) -> list[str]:
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    parts: list[str] = []
    current = ''
    sentences = re.split(r'(?<=[.!?。！？])\s+', text)
    for sentence in sentences:
        if len(sentence) > max_chars:
            words = sentence.split()
            for word in words:
                candidate = f'{current} {word}'.strip()
                if len(candidate) > max_chars and current:
                    parts.append(current)
                    current = word
                else:
                    current = candidate
        else:
            candidate = f'{current} {sentence}'.strip()
            if len(candidate) > max_chars and current:
                parts.append(current)
                current = sentence
            else:
                current = candidate
    if current:
        parts.append(current)
    return parts


def remove_command_prefix(text: str) -> str:
    text = text.strip()
    prefixes = [
        'ejecuta el comando', 'ejecuta comando', 'corre el comando', 'corre comando',
        'lanza el comando', 'haz en terminal', 'en terminal', 'terminal'
    ]
    n = normalize(text)
    for prefix in prefixes:
        p = normalize(prefix)
        if n.startswith(p):
            return text[len(prefix):].strip(' :')
    return text
