from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import shutil
import subprocess

import yaml

from jarvis.config import DEFAULT_CONFIG_PATH


def _load_sd():
    try:
        import sounddevice as sd  # type: ignore
        return sd
    except Exception:
        return None


def _normalize_pref(value: Any) -> Any:
    if value in (None, "", "default"):
        return None
    if isinstance(value, str):
        raw = value.strip()
        if raw == "" or raw.lower() == "default":
            return None
        if raw.lstrip("-").isdigit():
            try:
                return int(raw)
            except Exception:
                return raw
        return raw
    return value


def _default_indexes(sd: Any) -> tuple[int | None, int | None]:
    try:
        maybe = getattr(getattr(sd, "default", None), "device", None)
        if isinstance(maybe, (list, tuple)) and len(maybe) >= 2:
            inp = maybe[0]
            out = maybe[1]
        else:
            inp = out = None
        inp = int(inp) if inp not in (None, -1, "-1") else None
        out = int(out) if out not in (None, -1, "-1") else None
        return inp, out
    except Exception:
        return None, None


def _run_command(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False)
        if proc.returncode == 0:
            return (proc.stdout or "").strip()
    except Exception:
        return ""
    return ""


def _list_pactl_sources() -> list[dict[str, str]]:
    if shutil.which("pactl") is None:
        return []
    out = _run_command(["pactl", "list", "short", "sources"])
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"id": parts[0], "name": parts[1]})
    return rows


def _list_pactl_sinks() -> list[dict[str, str]]:
    if shutil.which("pactl") is None:
        return []
    out = _run_command(["pactl", "list", "short", "sinks"])
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"id": parts[0], "name": parts[1]})
    return rows


def _pactl_default(kind: str) -> tuple[str | None, str | None]:
    if shutil.which("pactl") is None:
        return None, None
    info = _run_command(["pactl", "info"])
    if not info:
        return None, None
    needle = "Default Source: " if kind == "source" else "Default Sink: "
    for line in info.splitlines():
        if line.startswith(needle):
            name = line.split(":", 1)[1].strip()
            rows = _list_pactl_sources() if kind == "source" else _list_pactl_sinks()
            for item in rows:
                if item.get("name") == name:
                    return item.get("id"), name
            return None, name
    return None, None


def scan_audio_devices() -> dict[str, Any]:
    sd = _load_sd()
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    if sd is None:
        source_id, source_name = _pactl_default("source")
        sink_id, sink_name = _pactl_default("sink")
        return {
            "inputs": inputs,
            "outputs": outputs,
            "default_input_index": None,
            "default_output_index": None,
            "default_source_id": source_id,
            "default_source_name": source_name,
            "default_sink_id": sink_id,
            "default_sink_name": sink_name,
            "pactl_sources": _list_pactl_sources(),
            "pactl_sinks": _list_pactl_sinks(),
            "sounddevice_available": False,
        }

    default_input, default_output = _default_indexes(sd)
    try:
        devices = list(sd.query_devices())
    except Exception:
        devices = []

    for index, info in enumerate(devices):
        try:
            name = str(info.get("name", "")).strip()
            max_input = int(info.get("max_input_channels", 0) or 0)
            max_output = int(info.get("max_output_channels", 0) or 0)
            samplerate = float(info.get("default_samplerate", 0.0) or 0.0)
        except Exception:
            continue
        row = {
            "index": index,
            "name": name,
            "max_input_channels": max_input,
            "max_output_channels": max_output,
            "default_samplerate": samplerate,
            "is_default_input": index == default_input,
            "is_default_output": index == default_output,
        }
        if max_input > 0:
            inputs.append(dict(row))
        if max_output > 0:
            outputs.append(dict(row))

    source_id, source_name = _pactl_default("source")
    sink_id, sink_name = _pactl_default("sink")
    return {
        "inputs": inputs,
        "outputs": outputs,
        "default_input_index": default_input,
        "default_output_index": default_output,
        "default_source_id": source_id,
        "default_source_name": source_name,
        "default_sink_id": sink_id,
        "default_sink_name": sink_name,
        "pactl_sources": _list_pactl_sources(),
        "pactl_sinks": _list_pactl_sinks(),
        "sounddevice_available": True,
    }


def has_audio_preferences(config: dict[str, Any]) -> bool:
    audio = (config or {}).get("audio", {}) or {}
    keys = [
        "wake_input_device",
        "wake_input_device_name",
        "stt_input_device",
        "stt_input_device_name",
        "input_device",
        "input_device_name",
        "output_device",
        "output_device_name",
        "pulse_source_id",
        "pulse_source_name",
        "pulse_sink_id",
        "pulse_sink_name",
    ]
    for key in keys:
        value = audio.get(key)
        if value not in (None, "", "default"):
            return True
    return False


def _name_match(items: list[dict[str, Any]], needle: str) -> tuple[dict[str, Any] | None, str | None]:
    needle = str(needle or "").strip().lower()
    if not needle:
        return None, None
    for item in items:
        if str(item.get("name", "")).strip().lower() == needle:
            return item, "name_exact"
    for item in items:
        name = str(item.get("name", "")).strip().lower()
        if needle in name or name in needle:
            return item, "name_partial"
    compact = needle.replace(" ", "")
    for item in items:
        name = str(item.get("name", "")).strip().lower().replace(" ", "")
        if compact and compact in name:
            return item, "name_compact"
    return None, None


def _index_match(items: list[dict[str, Any]], value: Any) -> tuple[dict[str, Any] | None, str | None]:
    norm = _normalize_pref(value)
    if not isinstance(norm, int):
        return None, None
    for item in items:
        if int(item.get("index", -9999)) == norm:
            return item, "preferred_index_valid"
    return None, None


def _resolve_pactl_entity(items: list[dict[str, str]], pref: Any) -> tuple[dict[str, str] | None, str | None]:
    value = _normalize_pref(pref)
    if value in (None, "", "default"):
        return None, None
    if isinstance(value, int):
        value = str(value)
    raw = str(value).strip()
    for item in items:
        if item.get("id") == raw:
            return item, "id_exact"
    lowered = raw.lower()
    for item in items:
        if str(item.get("name", "")).strip().lower() == lowered:
            return item, "name_exact"
    for item in items:
        name = str(item.get("name", "")).strip().lower()
        if lowered in name or name in lowered:
            return item, "name_partial"
    return None, None


def apply_audio_routes(config: dict[str, Any]) -> dict[str, Any]:
    audio = (config or {}).get("audio", {}) or {}
    result: dict[str, Any] = {}
    if shutil.which("pactl") is None:
        return result

    source_pref = audio.get("pulse_source_name") or audio.get("pulse_source_id")
    sink_pref = audio.get("pulse_sink_name") or audio.get("pulse_sink_id")
    scan = scan_audio_devices()
    if source_pref not in (None, "", "default"):
        item, reason = _resolve_pactl_entity(scan.get("pactl_sources", []), source_pref)
        if item is not None:
            subprocess.run(["pactl", "set-default-source", item["name"]], capture_output=True, text=True, timeout=3, check=False)
            result["source"] = {"name": item["name"], "id": item["id"], "reason": reason}
    if sink_pref not in (None, "", "default"):
        item, reason = _resolve_pactl_entity(scan.get("pactl_sinks", []), sink_pref)
        if item is not None:
            subprocess.run(["pactl", "set-default-sink", item["name"]], capture_output=True, text=True, timeout=3, check=False)
            result["sink"] = {"name": item["name"], "id": item["id"], "reason": reason}
    return result


def _resolve_from_preferences(
    items: list[dict[str, Any]],
    default_index: int | None,
    preferences: list[Any],
    role: str,
    kind: str,
) -> dict[str, Any]:
    requested = None
    requested_name = None
    for pref in preferences:
        if pref in (None, "", "default"):
            continue
        requested = pref if requested is None else requested
        if isinstance(pref, str) and not pref.lstrip("-").isdigit():
            requested_name = pref if requested_name is None else requested_name
        item, reason = _index_match(items, pref)
        if item is not None:
            return {
                "role": role,
                "kind": kind,
                "device": item["index"],
                "index": item["index"],
                "name": item["name"],
                "reason": reason,
                "requested": requested,
                "requested_name": requested_name,
            }
        if isinstance(pref, str):
            item, reason = _name_match(items, pref)
            if item is not None:
                return {
                    "role": role,
                    "kind": kind,
                    "device": item["index"],
                    "index": item["index"],
                    "name": item["name"],
                    "reason": reason,
                    "requested": requested,
                    "requested_name": requested_name,
                }

    if default_index is not None:
        for item in items:
            if int(item.get("index", -1)) == default_index:
                return {
                    "role": role,
                    "kind": kind,
                    "device": item["index"],
                    "index": item["index"],
                    "name": item["name"],
                    "reason": "default_index",
                    "requested": requested,
                    "requested_name": requested_name,
                }

    if items:
        first = items[0]
        return {
            "role": role,
            "kind": kind,
            "device": first["index"],
            "index": first["index"],
            "name": first["name"],
            "reason": "first_valid",
            "requested": requested,
            "requested_name": requested_name,
        }

    return {
        "role": role,
        "kind": kind,
        "device": "default",
        "index": None,
        "name": "default",
        "reason": "no_devices",
        "requested": requested,
        "requested_name": requested_name,
    }


def resolve_input_device(config: dict[str, Any], role: str = "stt", current: Any = None) -> dict[str, Any]:
    apply_audio_routes(config)
    audio = (config or {}).get("audio", {}) or {}
    scan = scan_audio_devices()
    preferences: list[Any] = []
    if role == "wake":
        preferences.extend([audio.get("wake_input_device_name"), audio.get("wake_input_device")])
    elif role in ("stt", "recorder"):
        preferences.extend([audio.get("stt_input_device_name"), audio.get("stt_input_device")])
    preferences.extend([audio.get("input_device_name"), audio.get("input_device"), current])
    return _resolve_from_preferences(scan["inputs"], scan.get("default_input_index"), preferences, role, "input")


def resolve_output_device(config: dict[str, Any], current: Any = None) -> dict[str, Any]:
    apply_audio_routes(config)
    audio = (config or {}).get("audio", {}) or {}
    scan = scan_audio_devices()
    preferences: list[Any] = []
    preferences.extend([audio.get("output_device_name"), audio.get("output_device"), current])
    return _resolve_from_preferences(scan["outputs"], scan.get("default_output_index"), preferences, "tts", "output")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def save_audio_preferences(
    wake_pref: Any = None,
    stt_pref: Any = None,
    output_pref: Any = None,
    pulse_source_pref: Any = None,
    pulse_sink_pref: Any = None,
    same_stt_as_wake: bool = True,
    path: str | Path | None = None,
) -> dict[str, Any]:
    cfg_path = Path(path).expanduser() if path else DEFAULT_CONFIG_PATH
    cfg = _load_yaml(cfg_path)
    audio = cfg.setdefault("audio", {})

    if pulse_source_pref not in (None, ""):
        pulse_source_item, _ = _resolve_pactl_entity(_list_pactl_sources(), pulse_source_pref)
        if pulse_source_item is not None:
            audio["pulse_source_id"] = pulse_source_item["id"]
            audio["pulse_source_name"] = pulse_source_item["name"]
        else:
            audio["pulse_source_id"] = None
            audio["pulse_source_name"] = str(pulse_source_pref).strip() or None
    if pulse_sink_pref not in (None, ""):
        pulse_sink_item, _ = _resolve_pactl_entity(_list_pactl_sinks(), pulse_sink_pref)
        if pulse_sink_item is not None:
            audio["pulse_sink_id"] = pulse_sink_item["id"]
            audio["pulse_sink_name"] = pulse_sink_item["name"]
        else:
            audio["pulse_sink_id"] = None
            audio["pulse_sink_name"] = str(pulse_sink_pref).strip() or None

    wake_cfg = {"audio": dict(audio)}
    if wake_pref not in (None, ""):
        if isinstance(wake_pref, str) and not wake_pref.lstrip("-").isdigit():
            wake_cfg["audio"]["wake_input_device_name"] = wake_pref
        else:
            wake_cfg["audio"]["wake_input_device"] = _normalize_pref(wake_pref)
    wake_choice = resolve_input_device(wake_cfg, role="wake")

    stt_choice = wake_choice
    if not same_stt_as_wake:
        stt_cfg = {"audio": dict(audio)}
        if stt_pref not in (None, ""):
            if isinstance(stt_pref, str) and not str(stt_pref).lstrip("-").isdigit():
                stt_cfg["audio"]["stt_input_device_name"] = stt_pref
            else:
                stt_cfg["audio"]["stt_input_device"] = _normalize_pref(stt_pref)
        stt_choice = resolve_input_device(stt_cfg, role="stt")

    out_cfg = {"audio": dict(audio)}
    if output_pref not in (None, ""):
        if isinstance(output_pref, str) and not str(output_pref).lstrip("-").isdigit():
            out_cfg["audio"]["output_device_name"] = output_pref
        else:
            out_cfg["audio"]["output_device"] = _normalize_pref(output_pref)
    output_choice = resolve_output_device(out_cfg)

    audio["wake_input_device"] = wake_choice["index"] if wake_choice["index"] is not None else "default"
    audio["wake_input_device_name"] = wake_choice["name"]
    audio["stt_input_device"] = stt_choice["index"] if stt_choice["index"] is not None else "default"
    audio["stt_input_device_name"] = stt_choice["name"]
    audio["input_device"] = audio["stt_input_device"]
    audio["input_device_name"] = audio["stt_input_device_name"]
    audio["output_device"] = output_choice["index"] if output_choice["index"] is not None else "default"
    audio["output_device_name"] = output_choice["name"]

    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {
        "path": str(cfg_path),
        "wake": wake_choice,
        "stt": stt_choice,
        "output": output_choice,
        "same_stt_as_wake": same_stt_as_wake,
        "pulse_source_name": audio.get("pulse_source_name"),
        "pulse_sink_name": audio.get("pulse_sink_name"),
    }


def _friendly_name_from_sounddevice(name: str) -> tuple[str, str]:
    raw = str(name or "").strip()
    lowered = raw.lower()
    if lowered == "sysdefault":
        return "", ""
    if "g535" in lowered or "logitech" in lowered:
        return "logitech_g535", "Logitech G535"
    if "alc221" in lowered or ("hda intel pch" in lowered and "analog" in lowered):
        return "audio_interno_alc221", "Audio interno (ALC221)"
    if "benq" in lowered:
        return "benq_ex240n", "BenQ EX240N"
    if "lg ultragear" in lowered:
        return "lg_ultragear", "LG UltraGear"
    base = re.sub(r"\s*\(hw:[^)]+\)", "", raw).strip()
    base = re.sub(r"\s*:\s*(USB Audio|Analog|Alt Analog|HDMI \d+)$", "", base).strip()
    key = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    return key, base or raw


def _friendly_name_from_pulse(name: str) -> tuple[str, str]:
    raw = str(name or "").strip()
    lowered = raw.lower()
    if "logitech" in lowered or "g535" in lowered:
        return "logitech_g535", "Logitech G535"
    if "pci-0000_00_1f.3" in lowered and "analog-stereo" in lowered:
        return "audio_interno_alc221", "Audio interno (ALC221)"
    if "benq" in lowered:
        return "benq_ex240n", "BenQ EX240N"
    if "ultragear" in lowered:
        return "lg_ultragear", "LG UltraGear"
    if "hdmi" in lowered:
        cleaned = raw.replace("alsa_output.", "").replace("alsa_input.", "")
        key = re.sub(r"[^a-z0-9]+", "_", cleaned.lower()).strip("_")
        return key, cleaned
    cleaned = raw.replace("alsa_output.", "").replace("alsa_input.", "")
    key = re.sub(r"[^a-z0-9]+", "_", cleaned.lower()).strip("_")
    return key, cleaned


def scan_audio_profiles() -> list[dict[str, Any]]:
    scan = scan_audio_devices()
    profiles: dict[str, dict[str, Any]] = {}

    def ensure_profile(key: str, label: str) -> dict[str, Any]:
        profile = profiles.get(key)
        if profile is None:
            profile = {
                "key": key,
                "label": label,
                "input": None,
                "output": None,
                "source": None,
                "sink": None,
                "preferred_input": None,
                "preferred_output": None,
                "input_display": None,
                "output_display": None,
                "route_only_input": False,
                "route_only_output": False,
                "score": 0,
            }
            profiles[key] = profile
        return profile

    sys_input = None
    sys_output = None
    for item in scan.get("inputs", []):
        if str(item.get("name", "")).strip().lower() == "sysdefault":
            sys_input = item
        key, label = _friendly_name_from_sounddevice(str(item.get("name", "")))
        if not key:
            continue
        profile = ensure_profile(key, label)
        if profile["input"] is None or item.get("max_input_channels", 0) > profile["input"].get("max_input_channels", 0):
            profile["input"] = item

    for item in scan.get("outputs", []):
        if str(item.get("name", "")).strip().lower() == "sysdefault":
            sys_output = item
        key, label = _friendly_name_from_sounddevice(str(item.get("name", "")))
        if not key:
            continue
        profile = ensure_profile(key, label)
        if profile["output"] is None or item.get("max_output_channels", 0) > profile["output"].get("max_output_channels", 0):
            profile["output"] = item

    for item in scan.get("pactl_sources", []):
        if str(item.get("name", "")).endswith(".monitor"):
            continue
        key, label = _friendly_name_from_pulse(str(item.get("name", "")))
        if not key:
            continue
        profile = ensure_profile(key, label)
        profile["source"] = item

    for item in scan.get("pactl_sinks", []):
        key, label = _friendly_name_from_pulse(str(item.get("name", "")))
        if not key:
            continue
        profile = ensure_profile(key, label)
        profile["sink"] = item

    result: list[dict[str, Any]] = []
    for profile in profiles.values():
        if profile["input"] is not None:
            profile["input_display"] = str(profile["input"].get("name", "")).strip()
            profile["preferred_input"] = str(profile["input"].get("name", "")).strip()
        elif profile["source"] is not None:
            source_name = str(profile["source"].get("name", "")).strip()
            profile["input_display"] = f"PipeWire mic: {source_name}"
            profile["route_only_input"] = True
            if sys_input is not None:
                profile["preferred_input"] = str(sys_input.get("name", "")).strip()

        if profile["output"] is not None:
            profile["output_display"] = str(profile["output"].get("name", "")).strip()
            profile["preferred_output"] = str(profile["output"].get("name", "")).strip()
        elif profile["sink"] is not None:
            sink_name = str(profile["sink"].get("name", "")).strip()
            profile["output_display"] = f"PipeWire salida: {sink_name}"
            profile["route_only_output"] = True
            if sys_output is not None:
                profile["preferred_output"] = str(sys_output.get("name", "")).strip()

        if profile["source"] is not None and profile["input"] is not None:
            profile["input_display"] = str(profile["input"].get("name", "")).strip() + " + PipeWire"
            profile["preferred_input"] = str(profile["input"].get("name", "")).strip()
            profile["route_only_input"] = False

        if profile["sink"] is not None and profile["output"] is not None:
            profile["output_display"] = str(profile["output"].get("name", "")).strip() + " + PipeWire"
            profile["preferred_output"] = str(profile["output"].get("name", "")).strip()
            profile["route_only_output"] = False

        score = 0
        if profile["input"] is not None:
            score += 30
        if profile["output"] is not None:
            score += 30
        if profile["source"] is not None:
            score += 20
        if profile["sink"] is not None:
            score += 20
        if profile.get("preferred_input"):
            score += 5
        if profile.get("preferred_output"):
            score += 5
        if profile.get("route_only_input"):
            score -= 3
        if profile.get("route_only_output"):
            score -= 3
        label_low = str(profile["label"]).lower()
        if "g535" in label_low or "headset" in label_low or "logitech" in label_low:
            score += 25
        if "interno" in label_low or "alc221" in label_low:
            score += 10
        profile["score"] = score
        result.append(profile)

    result.sort(key=lambda p: (-int(p.get("score", 0)), str(p.get("label", "")).lower()))
    return result
def resolve_audio_profile(query: Any) -> dict[str, Any] | None:
    profiles = scan_audio_profiles()
    if not profiles:
        return None
    raw = str(query or "").strip()
    if raw == "":
        return profiles[0]
    if raw.isdigit():
        idx = int(raw)
        if 1 <= idx <= len(profiles):
            return profiles[idx - 1]
    lowered = raw.lower()
    for profile in profiles:
        if lowered == str(profile.get("key", "")).lower():
            return profile
        if lowered == str(profile.get("label", "")).lower():
            return profile
    for profile in profiles:
        label = str(profile.get("label", "")).lower()
        key = str(profile.get("key", "")).lower()
        if lowered in label or lowered in key:
            return profile
    return None


def save_audio_profile(profile_query: Any, restart: bool = False, same_stt_as_wake: bool = True) -> dict[str, Any]:
    profile = resolve_audio_profile(profile_query)
    if profile is None:
        raise ValueError(f"No encontré perfil de audio: {profile_query}")

    wake_pref = profile.get("preferred_input") or (profile.get("input") or {}).get("name")
    stt_pref = wake_pref
    output_pref = profile.get("preferred_output") or (profile.get("output") or {}).get("name")
    pulse_source_pref = (profile.get("source") or {}).get("id")
    pulse_sink_pref = (profile.get("sink") or {}).get("id")

    result = save_audio_preferences(
        wake_pref=wake_pref,
        stt_pref=stt_pref,
        output_pref=output_pref,
        pulse_source_pref=pulse_source_pref,
        pulse_sink_pref=pulse_sink_pref,
        same_stt_as_wake=same_stt_as_wake,
    )

    cfg_path = Path(result["path"])
    cfg = _load_yaml(cfg_path)
    audio = cfg.setdefault("audio", {})

    if profile.get("input") is not None:
        in_item = profile["input"]
        inferred_input_name = str(in_item["name"])
        audio["wake_input_device"] = int(in_item["index"])
        audio["wake_input_device_name"] = inferred_input_name
        audio["stt_input_device"] = int(in_item["index"])
        audio["stt_input_device_name"] = inferred_input_name
        audio["input_device"] = int(in_item["index"])
        audio["input_device_name"] = inferred_input_name
        result["wake"] = {"device": int(in_item["index"]), "index": int(in_item["index"]), "name": inferred_input_name, "reason": "profile_input_direct"}
        result["stt"] = {"device": int(in_item["index"]), "index": int(in_item["index"]), "name": inferred_input_name, "reason": "profile_input_direct"}
    elif profile.get("source") is not None:
        source_name = str(profile["source"]["name"])
        inferred_input_name = None
        if profile.get("output") is not None:
            inferred_input_name = str(profile["output"]["name"])
        elif profile.get("label"):
            inferred_input_name = str(profile.get("label")).strip()

        if inferred_input_name:
            audio["wake_input_device"] = "default"
            audio["wake_input_device_name"] = inferred_input_name
            audio["stt_input_device"] = "default"
            audio["stt_input_device_name"] = inferred_input_name
            audio["input_device"] = "default"
            audio["input_device_name"] = inferred_input_name
            wake_name = inferred_input_name
            wake_reason = "profile_pipewire_source_with_name_hint"
        else:
            wake_name = f"PipeWire route: {source_name}"
            wake_reason = "profile_pipewire_source_route"

        result["wake"] = {"device": audio.get("wake_input_device", "default"), "index": audio.get("wake_input_device") if isinstance(audio.get("wake_input_device"), int) else None, "name": wake_name, "reason": wake_reason}
        result["stt"] = {"device": audio.get("stt_input_device", "default"), "index": audio.get("stt_input_device") if isinstance(audio.get("stt_input_device"), int) else None, "name": wake_name, "reason": wake_reason}

    if profile.get("output") is not None:
        out_item = profile["output"]
        audio["output_device"] = int(out_item["index"])
        audio["output_device_name"] = str(out_item["name"])
        result["output"] = {"device": int(out_item["index"]), "index": int(out_item["index"]), "name": str(out_item["name"]), "reason": "profile_output_direct"}
    elif profile.get("sink") is not None:
        sink_name = str(profile["sink"]["name"])
        result["output"] = {"device": audio.get("output_device", "default"), "index": audio.get("output_device") if isinstance(audio.get("output_device"), int) else None, "name": f"PipeWire route: {sink_name}", "reason": "profile_pipewire_sink_route"}

    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")

    result["profile"] = profile
    if restart:
        subprocess.run(["systemctl", "--user", "restart", "jarvis"], capture_output=True, text=True, timeout=8, check=False)
    return result
