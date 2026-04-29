from __future__ import annotations

import numpy as np


def rms_energy(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    audio = audio.astype('float32')
    return float(np.sqrt(np.mean(np.square(audio))))


def is_speech(audio: np.ndarray, threshold: float = 0.011) -> bool:
    return rms_energy(audio) >= threshold
