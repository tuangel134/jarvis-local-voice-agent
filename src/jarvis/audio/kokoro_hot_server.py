# -*- coding: utf-8 -*-
"""
Jarvis Kokoro Hot Server v4.0.5.2

Proceso persistente ejecutado con el Python 3.12 del venv Kokoro.
Protocolo JSON lines por stdin/stdout. Los logs van a stderr.

Fix v4.0.5.2:
- Extrae audio de KPipeline de forma robusta aunque Kokoro 0.9.4 devuelva
  objetos/tuplas/listas con metadatos.
- Evita np.asarray(..., dtype=float32) sobre estructuras heterogéneas.

# >>> JARVIS_V4052_KOKORO_HOT_SERVER_OUTPUT_SHAPE_FIX
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
import traceback
from pathlib import Path
from typing import Any
from collections.abc import Sequence

_PIPELINE = None
_PIPELINE_LANG = None
_LAST_LOAD_MS = 0
_DEBUG_EXTRACT = os.environ.get("JARVIS_KOKORO_HOT_EXTRACT_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}


def _log(msg: str) -> None:
    print(str(msg), file=sys.stderr, flush=True)


def _as_float(value: Any, default: float = 0.95) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _diagnose() -> dict[str, Any]:
    info: dict[str, Any] = {
        "ok": True,
        "executable": sys.executable,
        "version": sys.version,
        "cwd": os.getcwd(),
        "pythonpath": os.environ.get("PYTHONPATH", ""),
        "server_version": "v4.0.5.2",
    }
    for mod in ("numpy", "torch", "soundfile", "kokoro"):
        try:
            m = __import__(mod)
            info[f"{mod}_ok"] = True
            info[f"{mod}_version"] = getattr(m, "__version__", "unknown")
        except Exception as exc:
            info[f"{mod}_ok"] = False
            info[f"{mod}_error"] = str(exc)
    try:
        from kokoro import KPipeline  # noqa: F401
        info["KPipeline_ok"] = True
    except Exception as exc:
        info["KPipeline_ok"] = False
        info["KPipeline_error"] = str(exc)
    return info


def _is_string_like(value: Any) -> bool:
    return isinstance(value, (str, bytes, bytearray))


def _object_summary(value: Any) -> str:
    try:
        typ = type(value).__name__
        attrs = []
        for attr in ("audio", "wav", "samples", "array", "data", "output"):
            if hasattr(value, attr):
                attrs.append(attr)
        if hasattr(value, "shape"):
            attrs.append(f"shape={getattr(value, 'shape', None)}")
        if isinstance(value, Sequence) and not _is_string_like(value):
            attrs.append(f"len={len(value)}")
        return typ + ("[" + ",".join(attrs) + "]" if attrs else "")
    except Exception:
        return type(value).__name__


def _try_tensor_to_numpy(value: Any):
    try:
        if hasattr(value, "detach"):
            value = value.detach()
        if hasattr(value, "cpu"):
            value = value.cpu()
        if hasattr(value, "numpy"):
            value = value.numpy()
    except Exception:
        pass
    return value


def _try_direct_numeric_array(value: Any):
    """Devuelve ndarray float32 si value ya es claramente audio numérico; si no, None."""
    if value is None or _is_string_like(value):
        return None
    import numpy as np
    value = _try_tensor_to_numpy(value)

    # numpy array ya numérico
    if isinstance(value, np.ndarray):
        if value.dtype == object:
            return None
        try:
            arr = value.astype(np.float32, copy=False)
        except Exception:
            return None
        if arr.size < 16:
            return None
        return arr.reshape(-1)

    # Torch-like sin numpy array explícito ya se convirtió arriba; listas planas numéricas.
    if isinstance(value, Sequence) and not _is_string_like(value):
        if not value:
            return None
        # Solo convertir directo si parece lista plana de números. Si tiene sublistas/tuplas,
        # se analiza recursivamente en _extract_audio_array.
        sample = list(value[:8]) if hasattr(value, "__getitem__") else list(value)[:8]
        if sample and all(isinstance(x, (int, float)) for x in sample):
            try:
                arr = np.asarray(value, dtype=np.float32).reshape(-1)
                if arr.size >= 16:
                    return arr
            except Exception:
                return None
    return None


def _candidate_values(value: Any):
    """Genera candidatos de audio en orden de mayor probabilidad."""
    if value is None or _is_string_like(value):
        return

    # Objetos tipo resultado: preferir atributos obvios.
    for attr in ("audio", "wav", "samples", "array", "output_audio"):
        try:
            if hasattr(value, attr):
                yield getattr(value, attr)
        except Exception:
            pass

    if isinstance(value, dict):
        for key in ("audio", "wav", "samples", "array", "output", "data"):
            if key in value:
                yield value.get(key)
        return

    if isinstance(value, Sequence) and not _is_string_like(value):
        n = len(value)
        # Kokoro README: cada item suele ser (graphemes, phonemes, audio).
        # Por eso se intenta primero el último elemento.
        if n >= 3:
            yield value[-1]
        # Formato gradio común: (sample_rate, audio_array)
        if n == 2 and isinstance(value[0], int):
            yield value[1]
        # Como fallback, revisar del final al inicio, saltando strings.
        for item in reversed(value):
            if not _is_string_like(item):
                yield item
        return

    # Valor directo: tensor/ndarray/lista plana.
    yield value


def _extract_audio_array(value: Any, depth: int = 0, seen: set[int] | None = None):
    """Busca recursivamente un array/tensor de audio dentro de cualquier salida de Kokoro."""
    if seen is None:
        seen = set()
    if value is None or depth > 6:
        return None
    oid = id(value)
    if oid in seen:
        return None
    seen.add(oid)

    direct = _try_direct_numeric_array(value)
    if direct is not None:
        return direct

    import numpy as np
    found = []
    for cand in _candidate_values(value) or []:
        arr = _extract_audio_array(cand, depth + 1, seen)
        if arr is not None and getattr(arr, "size", 0) >= 16:
            found.append(arr.reshape(-1))

    if found:
        if len(found) == 1:
            return found[0]
        try:
            return np.concatenate(found)
        except Exception:
            return found[0]
    return None


def _normalize_audio(arr):
    import numpy as np
    arr = np.asarray(arr, dtype=np.float32).reshape(-1)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if arr.size == 0:
        raise RuntimeError("audio vacío")
    max_abs = float(np.max(np.abs(arr))) if arr.size else 0.0
    # Si viene como PCM int16/float enorme, normalizar; si viene ya -1..1, no tocar.
    if max_abs > 2.0:
        arr = arr / max_abs
    arr = np.clip(arr, -1.0, 1.0)
    return arr


def _write_wav_pcm16(path: str | os.PathLike[str], audio, sample_rate: int = 24000) -> None:
    arr = _normalize_audio(audio)
    pcm = (arr * 32767.0).astype("<i2").tobytes()
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)


def _make_pipeline(lang: str):
    from kokoro import KPipeline
    errors = []
    for mode in ("kw", "pos"):
        try:
            if mode == "kw":
                return KPipeline(lang_code=lang)
            return KPipeline(lang)
        except Exception as exc:
            errors.append(f"{mode}: {exc}")
    raise RuntimeError("No pude crear KPipeline: " + " | ".join(errors))


def _load_pipeline(lang: str):
    global _PIPELINE, _PIPELINE_LANG, _LAST_LOAD_MS
    lang = str(lang or "e").strip() or "e"
    if _PIPELINE is not None and _PIPELINE_LANG == lang:
        _LAST_LOAD_MS = 0
        return _PIPELINE
    t0 = time.perf_counter()
    _PIPELINE = _make_pipeline(lang)
    _PIPELINE_LANG = lang
    _LAST_LOAD_MS = int((time.perf_counter() - t0) * 1000)
    _log(f"pipeline listo lang={lang} load_ms={_LAST_LOAD_MS}")
    return _PIPELINE


def _call_pipeline_variants(pipeline, text: str, voice: str, speed: float):
    """Variantes compatibles con Kokoro moderno y forks."""
    variants = [
        {"voice": voice, "speed": speed},
        {"voice": voice, "speed": speed, "split_pattern": r"\n+"},
        {"voice": voice, "speed": speed, "split_pattern": None},
    ]
    for kwargs in variants:
        try:
            yield kwargs, pipeline(text, **kwargs), None
        except Exception as exc:
            yield kwargs, None, exc


def synthesize(req: dict[str, Any]) -> dict[str, Any]:
    rid = str(req.get("id") or "")
    text = str(req.get("text") or "").strip()
    voice = str(req.get("voice") or "em_alex").strip() or "em_alex"
    speed = _as_float(req.get("speed"), 0.95)
    lang = str(req.get("lang") or "e").strip() or "e"
    output = str(req.get("output") or "").strip()
    if not text:
        return {"id": rid, "ok": False, "error": "texto vacío"}
    if not output:
        return {"id": rid, "ok": False, "error": "output vacío"}

    t0 = time.perf_counter()
    pipeline = _load_pipeline(lang)
    t1 = time.perf_counter()

    import numpy as np
    parts = []
    call_errors = []
    extract_debug = []

    for kwargs, generator, err in _call_pipeline_variants(pipeline, text, voice, speed):
        if err is not None:
            call_errors.append(f"call {kwargs}: {err}")
            continue
        try:
            local_parts = []
            for idx, item in enumerate(generator):
                if _DEBUG_EXTRACT and len(extract_debug) < 12:
                    extract_debug.append(f"item{idx}={_object_summary(item)}")
                arr = _extract_audio_array(item)
                if arr is not None and getattr(arr, "size", 0) >= 16:
                    local_parts.append(arr)
                else:
                    if _DEBUG_EXTRACT and len(extract_debug) < 12:
                        extract_debug.append(f"item{idx}_no_audio={repr(item)[:300]}")
            if local_parts:
                parts = local_parts
                break
            call_errors.append(f"call {kwargs}: generador sin audio útil")
        except Exception as exc:
            call_errors.append(f"call {kwargs}: {exc}")
            if _DEBUG_EXTRACT:
                extract_debug.append(traceback.format_exc()[-1200:])

    if not parts:
        msg = "Kokoro no devolvió audio utilizable. Errores: " + " | ".join(call_errors)
        if extract_debug:
            msg += " | extract_debug=" + " || ".join(extract_debug)
        raise RuntimeError(msg)

    audio = parts[0] if len(parts) == 1 else np.concatenate([_normalize_audio(p) for p in parts])
    _write_wav_pcm16(output, audio, 24000)
    t2 = time.perf_counter()
    return {
        "id": rid,
        "ok": True,
        "path": str(Path(output).expanduser()),
        "voice": voice,
        "speed": speed,
        "lang": lang,
        "server_version": "v4.0.5.2",
        "chunks": len(parts),
        "samples": int(len(audio)),
        "load_ms": _LAST_LOAD_MS or int((t1 - t0) * 1000),
        "synth_ms": int((t2 - t1) * 1000),
        "total_ms": int((t2 - t0) * 1000),
    }


def main() -> int:
    _log("Jarvis Kokoro Hot Server iniciado v4.0.5.2")
    preload = os.environ.get("JARVIS_KOKORO_HOT_PRELOAD", "1").strip() != "0"
    if preload:
        try:
            _load_pipeline(os.environ.get("JARVIS_KOKORO_LANG", "e"))
        except Exception as exc:
            _log("preload falló: " + str(exc))
            _log(traceback.format_exc())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        rid = ""
        try:
            req = json.loads(line)
            rid = str(req.get("id") or "")
            cmd = req.get("cmd")
            if cmd == "ping":
                res = {"id": rid, "ok": True, "pong": True, "server_version": "v4.0.5.2"}
            elif cmd == "diagnose":
                res = {"id": rid, **_diagnose()}
            elif cmd == "stop":
                print(json.dumps({"id": rid, "ok": True, "stopped": True}, ensure_ascii=False), flush=True)
                return 0
            else:
                res = synthesize(req)
        except Exception as exc:
            _log("ERROR request: " + str(exc))
            _log(traceback.format_exc())
            res = {"id": rid, "ok": False, "error": str(exc), "traceback": traceback.format_exc()[-3500:]}
        print(json.dumps(res, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
# <<< JARVIS_V4052_KOKORO_HOT_SERVER_OUTPUT_SHAPE_FIX
