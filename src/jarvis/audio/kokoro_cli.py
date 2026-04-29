from __future__ import annotations
import argparse
from pathlib import Path
import soundfile as sf
from kokoro import KPipeline

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default="em_alex")
    ap.add_argument("--lang", default="e")
    ap.add_argument("--speed", type=float, default=0.95)
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    pipeline = KPipeline(lang_code=args.lang, repo_id="hexgrad/Kokoro-82M")
    gen = pipeline(args.text, voice=args.voice, speed=args.speed)

    for _, _, audio in gen:
        sf.write(str(out), audio, 24000)
        print(str(out))
        return

    raise RuntimeError("Kokoro no generó audio")

# >>> JARVIS_V4034_KOKORO_APLAY_PAD_ALL
# Intercepta aplay dentro de Kokoro para que TODO WAV tenga silencio inicial,
# incluyendo /home/angel/.local/share/jarvis/tmp/jarvis_kokoro.wav cuando NO viene del cache.
def _jarvis_v4034_patch_aplay_padding() -> None:
    try:
        import os as _os
        import subprocess as _subprocess
        from pathlib import Path as _Path
        try:
            from jarvis.audio.wav_pad import make_padded_wav as _jarvis_v4034_make_padded_wav
        except Exception:
            _jarvis_v4034_make_padded_wav = None

        if getattr(_subprocess.run, "_jarvis_v4034_padded", False):
            return

        def _jarvis_v4034_pad_cmd(cmd):
            if _jarvis_v4034_make_padded_wav is None:
                return cmd
            try:
                if isinstance(cmd, (list, tuple)) and cmd:
                    exe = _Path(str(cmd[0])).name
                    if exe != "aplay":
                        return cmd
                    new_cmd = list(cmd)
                    for i, part in enumerate(new_cmd):
                        s = str(part)
                        if s.lower().endswith(".wav"):
                            p = _Path(s).expanduser()
                            if p.exists():
                                new_cmd[i] = str(_jarvis_v4034_make_padded_wav(p))
                                # Silenciar aplay si no estaba silenciado.
                                if "-q" not in new_cmd:
                                    new_cmd.insert(1, "-q")
                                return new_cmd
                    return cmd
            except Exception:
                return cmd
            return cmd

        _orig_run = _subprocess.run
        _orig_call = getattr(_subprocess, "call", None)
        _orig_check_call = getattr(_subprocess, "check_call", None)
        _orig_popen = getattr(_subprocess, "Popen", None)

        def _run(cmd, *args, **kwargs):
            return _orig_run(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
        _run._jarvis_v4034_padded = True
        _subprocess.run = _run

        if _orig_call is not None:
            def _call(cmd, *args, **kwargs):
                return _orig_call(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.call = _call

        if _orig_check_call is not None:
            def _check_call(cmd, *args, **kwargs):
                return _orig_check_call(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.check_call = _check_call

        if _orig_popen is not None:
            def _popen(cmd, *args, **kwargs):
                return _orig_popen(_jarvis_v4034_pad_cmd(cmd), *args, **kwargs)
            _subprocess.Popen = _popen
    except Exception:
        pass

_jarvis_v4034_patch_aplay_padding()
# <<< JARVIS_V4034_KOKORO_APLAY_PAD_ALL

if __name__ == "__main__":
    main()
