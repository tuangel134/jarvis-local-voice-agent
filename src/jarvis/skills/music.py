
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from jarvis.actions.specs import ActionSpec, RiskLevel
from jarvis.brain.context_store import ContextStore
from jarvis.brain.intent_classifier import Intent
from jarvis.skills.base import Skill
from jarvis.utils.security import is_url_allowed
from jarvis.utils.text import normalize


class MusicSkill(Skill):
    name = "media"
    description = "Controla reproducción musical, transporte multimedia y volumen del sistema."
    ACTIONS = (
        ActionSpec(name="search", namespace="media", description="Busca o reproduce música en YouTube, YouTube Music, TIDAL o Spotify.", intents=("play_music",), examples=("reproduce san lucas", "pon música de kevin kaarl"), risk_level=RiskLevel.SAFE, backend="mpv/xdg-open"),
        ActionSpec(name="pause_playback", namespace="media", description="Pausa la reproducción actual.", intents=("pause_music", "media_pause"), examples=("pausa la música", "pausa"), risk_level=RiskLevel.SAFE, backend="mpv ipc/playerctl"),
        ActionSpec(name="resume_playback", namespace="media", description="Reanuda la reproducción actual.", intents=("resume_music", "media_resume"), examples=("reanuda la música", "continúa la música"), risk_level=RiskLevel.SAFE, backend="mpv ipc/playerctl"),
        ActionSpec(name="stop_playback", namespace="media", description="Detiene la reproducción actual.", intents=("stop_music", "media_stop"), examples=("detén la música", "para la música"), risk_level=RiskLevel.SAFE, backend="mpv ipc/playerctl"),
        ActionSpec(name="next_track", namespace="media", description="Pasa a la siguiente pista cuando el backend lo permite.", intents=("media_next",), examples=("siguiente canción", "siguiente pista"), risk_level=RiskLevel.SAFE, backend="playerctl"),
        ActionSpec(name="previous_track", namespace="media", description="Vuelve a la pista anterior cuando el backend lo permite.", intents=("media_previous",), examples=("canción anterior", "pista anterior"), risk_level=RiskLevel.SAFE, backend="playerctl"),
        ActionSpec(name="volume_up", namespace="media", description="Sube el volumen del sistema.", intents=("media_volume_up",), examples=("sube el volumen", "más volumen"), risk_level=RiskLevel.SAFE, backend="wpctl/pactl/amixer"),
        ActionSpec(name="volume_down", namespace="media", description="Baja el volumen del sistema.", intents=("media_volume_down",), examples=("baja el volumen", "menos volumen"), risk_level=RiskLevel.SAFE, backend="wpctl/pactl/amixer"),
        ActionSpec(name="volume_set", namespace="media", description="Fija el volumen del sistema a un porcentaje.", intents=("media_volume_set",), examples=("volumen al 40", "pon el volumen al 70 por ciento"), risk_level=RiskLevel.SAFE, backend="wpctl/pactl/amixer"),
        ActionSpec(name="mute", namespace="media", description="Silencia el audio del sistema.", intents=("media_mute",), examples=("silencia el audio", "mutea"), risk_level=RiskLevel.SAFE, backend="wpctl/pactl/amixer"),
        ActionSpec(name="unmute", namespace="media", description="Quita el mute del audio del sistema.", intents=("media_unmute",), examples=("quita el mute", "activa el sonido"), risk_level=RiskLevel.SAFE, backend="wpctl/pactl/amixer"),
    )

    def can_handle(self, intent: Intent) -> bool:
        return intent.name in {"play_music", "pause_music", "resume_music", "stop_music", "media_pause", "media_resume", "media_stop", "media_next", "media_previous", "media_volume_up", "media_volume_down", "media_volume_set", "media_mute", "media_unmute"}

    def run(self, intent: Intent, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        name = intent.name
        if name in {"pause_music", "media_pause"}:
            return self._pause()
        if name in {"resume_music", "media_resume"}:
            return self._resume()
        if name in {"stop_music", "media_stop"}:
            return self._stop()
        if name == "media_next":
            return self._playerctl_command("next", "Siguiente pista.")
        if name == "media_previous":
            return self._playerctl_command("previous", "Pista anterior.")
        if name == "media_volume_up":
            return self._change_volume(int(entities.get("step") or 8))
        if name == "media_volume_down":
            return self._change_volume(-int(entities.get("step") or 8))
        if name == "media_volume_set":
            target = entities.get("percent")
            if target is None:
                return {"ok": False, "error": "No detecté el porcentaje de volumen."}
            return self._set_volume(int(target))
        if name == "media_mute":
            return self._mute(True)
        if name == "media_unmute":
            return self._mute(False)
        return self._play(entities, context)

    def _play(self, entities: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        query = str(entities.get("query") or "").strip()
        platform = normalize(str(entities.get("platform") or ""))
        cfg = context.get("config", self.config) if isinstance(context, dict) else self.config
        music_cfg = cfg.get("music", {})
        if not query:
            return {"ok": False, "error": "No detecté qué canción o artista buscar."}
        if not platform:
            platform = normalize(music_cfg.get("default_platform", "youtube"))
        if platform in {"youtube", "you tube", "yt", "youtube_music", "youtube music", "yt music"}:
            return self._play_youtube_audio(query)
        url = self._build_url(platform, query, music_cfg)
        if not url:
            return {"ok": False, "error": f"No conozco la plataforma de música: {platform}."}
        if not is_url_allowed(url, cfg):
            return {"ok": False, "error": "La URL musical no está permitida por seguridad."}
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "message": f"Buscando {query} en {self._platform_name(platform)}."}

    def _build_url(self, platform: str, query: str, music_cfg: dict[str, Any]) -> str | None:
        q = quote_plus(query)
        if platform in {"tidal", "taital", "taydal", "tidal music"}:
            base = str(music_cfg.get("tidal_search_base", "https://tidal.com/search?q="))
            return base.format(q) if "{}" in base else base + q
        if platform in {"spotify", "espoti", "spotifai"}:
            return f"https://open.spotify.com/search/{q}"
        if platform in {"youtube music", "music youtube", "yt music", "yutub music", "yutube music", "youtube_music"}:
            return f"https://music.youtube.com/search?q={q}"
        if platform in {"youtube", "you tube", "yt", "yutube", "jutube"}:
            return f"https://www.youtube.com/results?search_query={q}"
        return None

    def _platform_name(self, platform: str) -> str:
        if "tidal" in platform or "taital" in platform or "taydal" in platform:
            return "TIDAL"
        if "spotify" in platform or "spot" in platform:
            return "Spotify"
        if "music" in platform:
            return "YouTube Music"
        return "YouTube"

    def _play_youtube_audio(self, query: str) -> dict[str, Any]:
        query = self._clean_query(query)
        if not query:
            return {"ok": False, "error": "No detecté qué canción reproducir."}
        mpv = shutil.which("mpv")
        if not mpv:
            return {"ok": False, "error": "No encontré mpv. Instálalo con: sudo apt install mpv"}
        self._stop_previous_music()
        ipc_path = self._ipc_file()
        ipc_path.parent.mkdir(parents=True, exist_ok=True)
        ipc_path.unlink(missing_ok=True)
        try:
            proc = subprocess.Popen([mpv, "--no-video", "--force-window=no", "--really-quiet", f"--input-ipc-server={ipc_path}", "--title=Jarvis Music", f"ytdl://ytsearch1:{query}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self._write_pid(proc.pid)
            ContextStore(self.config).set_last_media(query=query, platform="youtube", pid=proc.pid)
            return {"ok": True, "message": f"Reproduciendo {query} en YouTube.", "pid": proc.pid, "query": query}
        except Exception as exc:
            return {"ok": False, "error": f"Error reproduciendo música: {exc}"}

    def _pause(self) -> dict[str, Any]:
        if self._send_mpv_ipc(["set_property", "pause", True]) or self._playerctl_raw("pause"):
            return {"ok": True, "message": "Música pausada."}
        pid = self._read_pid()
        if pid and self._signal_pid(pid, signal.SIGSTOP):
            return {"ok": True, "message": "Música pausada."}
        return {"ok": False, "error": "No encontré música activa para pausar."}

    def _resume(self) -> dict[str, Any]:
        if self._send_mpv_ipc(["set_property", "pause", False]) or self._playerctl_raw("play"):
            return {"ok": True, "message": "Continuando la música."}
        pid = self._read_pid()
        if pid and self._signal_pid(pid, signal.SIGCONT):
            return {"ok": True, "message": "Continuando la música."}
        return {"ok": False, "error": "No encontré música pausada."}

    def _stop(self) -> dict[str, Any]:
        if self._send_mpv_ipc(["quit"]) or self._playerctl_raw("stop"):
            self._cleanup_transport_state()
            return {"ok": True, "message": "Música detenida."}
        if self._stop_previous_music():
            return {"ok": True, "message": "Música detenida."}
        return {"ok": False, "error": "No encontré música activa."}

    def _change_volume(self, delta: int) -> dict[str, Any]:
        backend = self._volume_backend()
        if backend == "wpctl":
            sign = "+" if delta >= 0 else "-"
            if self._run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{abs(delta)}%{sign}"]):
                direction = "Subiendo" if delta >= 0 else "Bajando"
                return {"ok": True, "message": f"{direction} volumen {abs(delta)} por ciento."}
        elif backend == "pactl":
            sign = "+" if delta >= 0 else "-"
            if self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{abs(delta)}%"]):
                direction = "Subiendo" if delta >= 0 else "Bajando"
                return {"ok": True, "message": f"{direction} volumen {abs(delta)} por ciento."}
        elif backend == "amixer":
            sign = "+" if delta >= 0 else "-"
            if self._run(["amixer", "-q", "set", "Master", f"{abs(delta)}%{sign}"]):
                direction = "Subiendo" if delta >= 0 else "Bajando"
                return {"ok": True, "message": f"{direction} volumen {abs(delta)} por ciento."}
        return {"ok": False, "error": "No pude cambiar el volumen con ningún backend disponible."}

    def _set_volume(self, percent: int) -> dict[str, Any]:
        percent = max(0, min(150, int(percent)))
        backend = self._volume_backend()
        if backend == "wpctl" and self._run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"]):
            return {"ok": True, "message": f"Volumen al {percent} por ciento."}
        if backend == "pactl" and self._run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"]):
            return {"ok": True, "message": f"Volumen al {percent} por ciento."}
        if backend == "amixer" and self._run(["amixer", "-q", "set", "Master", f"{percent}%"]):
            return {"ok": True, "message": f"Volumen al {percent} por ciento."}
        return {"ok": False, "error": "No pude fijar el volumen."}

    def _mute(self, enabled: bool) -> dict[str, Any]:
        backend = self._volume_backend()
        if backend == "wpctl":
            ok = self._run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if enabled else "0"])
        elif backend == "pactl":
            ok = self._run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if enabled else "0"])
        elif backend == "amixer":
            ok = self._run(["amixer", "-q", "set", "Master", "mute" if enabled else "unmute"])
        else:
            ok = False
        if ok:
            return {"ok": True, "message": "Audio silenciado." if enabled else "Audio reactivado."}
        return {"ok": False, "error": "No pude cambiar el estado mute del audio."}

    def _playerctl_command(self, action: str, message: str) -> dict[str, Any]:
        if self._playerctl_raw(action):
            return {"ok": True, "message": message}
        return {"ok": False, "error": "No encontré un reproductor compatible con playerctl."}

    def _playerctl_raw(self, action: str) -> bool:
        playerctl = shutil.which("playerctl")
        return bool(playerctl and self._run([playerctl, action]))

    def _volume_backend(self) -> str | None:
        for name in ("wpctl", "pactl", "amixer"):
            if shutil.which(name):
                return name
        return None

    def _run(self, cmd: list[str]) -> bool:
        try:
            proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            return proc.returncode == 0
        except Exception:
            return False

    def _clean_query(self, query: str) -> str:
        q = str(query or "").strip().lower()
        q = q.strip(" .,:;¡!¿?\"'")
        corrections = {"kevin carl": "kevin kaarl", "kevin card": "kevin kaarl", "kevin karl": "kevin kaarl", "kevin kaal": "kevin kaarl", "javi carles y sal lucas": "kevin kaarl san lucas", "javi carles sal lucas": "kevin kaarl san lucas", "javi carlos y sal lucas": "kevin kaarl san lucas", "javi carlos sal lucas": "kevin kaarl san lucas", "javi carles": "kevin kaarl", "sal lucas": "san lucas"}
        for bad, good in corrections.items():
            q = q.replace(bad, good)
        return re.sub(r"\s+", " ", q).strip()

    def _pid_file(self) -> Path:
        return Path.home() / ".local/share/jarvis/music_player.pid"

    def _ipc_file(self) -> Path:
        return Path.home() / ".local/share/jarvis/music_player.sock"

    def _send_mpv_ipc(self, command: list[Any]) -> bool:
        sock_path = self._ipc_file()
        if not sock_path.exists():
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.5)
                client.connect(str(sock_path))
                payload = json.dumps({"command": command}, ensure_ascii=False) + "\n"
                client.sendall(payload.encode("utf-8"))
                response = client.recv(4096).decode("utf-8", errors="ignore").strip()
            return '"error":"success"' in response or '"error": "success"' in response or response == ""
        except Exception:
            return False

    def _write_pid(self, pid: int) -> None:
        p = self._pid_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(pid), encoding="utf-8")

    def _read_pid(self) -> int | None:
        p = self._pid_file()
        if not p.exists():
            return None
        try:
            return int(p.read_text(encoding="utf-8").strip())
        except Exception:
            p.unlink(missing_ok=True)
            return None

    def _signal_pid(self, pid: int, sig: signal.Signals) -> bool:
        try:
            os.kill(pid, sig)
            return True
        except Exception:
            return False

    def _stop_previous_music(self) -> bool:
        pid = self._read_pid()
        if not pid:
            return False
        if self._signal_pid(pid, signal.SIGTERM):
            self._cleanup_transport_state()
            return True
        return False

    def _cleanup_transport_state(self) -> None:
        self._pid_file().unlink(missing_ok=True)
        self._ipc_file().unlink(missing_ok=True)
