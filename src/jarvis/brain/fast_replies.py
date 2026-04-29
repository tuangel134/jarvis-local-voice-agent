from __future__ import annotations

import hashlib
import random
import re
import subprocess
import unicodedata
from datetime import datetime
from typing import Any


def _norm(text: str) -> str:
    t = str(text or "").lower().strip()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    t = re.sub(r"[¡!¿?.,;:()\[\]{}\"'`´“”‘’]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _daily_choice(key: str, variants: list[str], text: str = "") -> str:
    if not variants:
        return ""
    day = datetime.now().strftime("%Y-%m-%d")
    seed = hashlib.sha256(f"{day}|{key}|{_norm(text)}".encode("utf-8")).hexdigest()
    rnd = random.Random(int(seed[:16], 16))
    return rnd.choice(variants)


def _time_text() -> str:
    now = datetime.now()
    h = now.hour
    m = now.minute
    return _daily_choice("time", [
        f"Son las {h} horas con {m:02d} minutos, señor.",
        f"Son las {h}:{m:02d}.",
        f"Ahora mismo son las {h}:{m:02d}, Ángel.",
        f"Según mi reloj, son las {h} con {m:02d}.",
    ])


def _date_text() -> str:
    now = datetime.now()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    return _daily_choice("date", [
        f"Hoy es {dias[now.weekday()]}, {now.day} de {meses[now.month - 1]} de {now.year}.",
        f"Estamos a {now.day} de {meses[now.month - 1]} de {now.year}, señor.",
        f"Fecha registrada: {dias[now.weekday()]} {now.day} de {meses[now.month - 1]}.",
    ])


def _battery_text() -> str:
    try:
        out = subprocess.run(
            ["bash", "-lc", "upower -e 2>/dev/null | grep -i BAT | head -1 | xargs -r upower -i 2>/dev/null | awk -F: '/percentage/ {gsub(/ /,\"\",$2); print $2}'"],
            text=True, capture_output=True, timeout=2,
        ).stdout.strip()
        if out:
            return _daily_choice("battery", [
                f"Le queda un {out} de batería.",
                f"El nivel de energía es del {out}.",
                f"Batería actual: {out}, señor.",
                f"Mis lecturas indican {out} de energía restante.",
            ])
    except Exception:
        pass
    return _daily_choice("battery_unknown", [
        "No detecto batería en este equipo, señor. Parece que estoy conectado a energía fija.",
        "No encuentro un módulo de batería disponible. En esta estación trabajo con alimentación directa.",
        "No tengo lectura de batería. Este sistema parece estar en modo escritorio.",
    ])


FAST_REPLY_VARIANTS: dict[str, list[str]] = {
    "presence": [
        "Sí, aquí estoy, señor.",
        "Para usted, siempre.",
        "Aquí estoy, siempre atento.",
        "Presente, Ángel.",
        "A la escucha.",
        "Mis sensores están activos. ¿Qué necesita?",
        "No me he movido de su escritorio.",
        "Por supuesto. Como siempre.",
        "A su lado, aunque no me vea.",
        "Siempre estoy aquí, señor.",
        "Listo para asistirle.",
        "Dígame.",
        "A sus órdenes.",
    ],
    "greeting": [
        "¿Sí, señor?",
        "A sus órdenes.",
        "¿En qué puedo ayudarle?",
        "Siempre atento.",
        "Listo para asistirle.",
        "Dígame.",
        "¿Qué desea?",
        "Para usted, siempre.",
        "A la escucha.",
        "Buenas, Ángel. Sistemas listos.",
        "Hola, señor. Núcleo operativo en línea.",
        "Aquí Jarvis. ¿Cuál es la misión?",
        "Lo escucho, Ángel.",
        "Modo asistencia activado.",
    ],
    "thanks": [
        "Es un placer.",
        "No hay de qué.",
        "Para eso estoy.",
        "A su servicio.",
        "Un honor.",
        "Siempre, señor.",
        "Cuando guste, Ángel.",
        "Me alegra ser útil.",
        "Misión cumplida.",
        "De nada. Mantengo los sistemas atentos.",
    ],
    "goodbye": [
        "Que tenga un buen día.",
        "Hasta la próxima, señor.",
        "Estaré aquí si me necesita.",
        "Volviendo a modo de espera.",
        "Apagando motores principales.",
        "Quedo en espera, Ángel.",
        "Modo vigilancia silenciosa activado.",
        "Hasta luego. Mis sensores quedan atentos.",
        "Cuando me necesite, solo llámeme.",
        "Cierro comunicación, pero sigo presente.",
    ],
    "status": [
        "Operativo y atento, señor.",
        "Todos mis módulos principales siguen en línea.",
        "Estoy funcionando correctamente.",
        "Sistemas activos. Voz, memoria y bus de eventos respondiendo.",
        "Estoy estable. Listo para la siguiente orden.",
        "Núcleo local activo. Esperando instrucciones.",
        "Me encuentro en condiciones óptimas para asistirle.",
    ],
    "capabilities": [
        "Puedo abrir carpetas, buscar archivos, abrir páginas, reproducir música, revisar servicios, recordar alias y explicar mis últimas acciones.",
        "Por ahora puedo controlar archivos, búsquedas, navegador, música, servicios como Jellyfin, memoria local, historial y eventos del bus.",
        "Tengo control local de varias tareas: abrir rutas, buscar builds, revisar resultados, responder rápido y registrar eventos para depuración.",
        "Puedo ayudarle con su sistema, sus carpetas, builds, búsquedas, música, páginas web y memoria de alias. Y sigo aprendiendo, señor.",
        "Mis funciones actuales incluyen voz, STT, TTS con Kokoro, aliases, búsquedas, historial, explicación de acciones y NeoBus.",
    ],
}


PATTERNS: list[tuple[str, list[str]]] = [
    ("presence", [
        r"\b(estas ahi|estas aqui|sigues ahi|me escuchas|me oyes|estas activo|estas despierto)\b",
        r"\b(ya estas ahi|jarvis estas ahi|jarvis estas aqui)\b",
    ]),
    ("greeting", [
        r"^(hola|buenas|buen dia|buenas tardes|buenas noches|que onda|hey jarvis|oye jarvis|jarvis)$",
        r"^(hola jarvis|buenas jarvis|jarvis hola)$",
    ]),
    ("thanks", [
        r"^(gracias|muchas gracias|ok gracias|perfecto gracias|te lo agradezco)$",
        r"\b(gracias jarvis|bien hecho gracias)\b",
    ]),
    ("goodbye", [
        r"^(adios|hasta luego|nos vemos|es todo|eso es todo|es todo por ahora|bye|apagate por ahora)$",
        r"\b(vuelve a modo de espera|modo espera)\b",
    ]),
    ("status", [
        r"\b(como estas|estado del sistema|estas bien|todo bien|funcionas bien)\b",
        r"^(status|estado)$",
    ]),
    ("capabilities", [
        r"\b(que puedes hacer|que sabes hacer|cuales son tus funciones|que funciones tienes|ayuda rapida)\b",
    ]),
    ("time", [
        r"\b(que hora es|dime la hora|hora actual|que horas son)\b",
    ]),
    ("date", [
        r"\b(que dia es|cual es la fecha|fecha actual|que fecha es)\b",
    ]),
    ("battery", [
        r"\b(cuanta bateria|bateria|nivel de bateria|energia restante)\b",
    ]),
]


def match_fast_reply(text: str, config: dict | None = None) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    t = _norm(raw)
    for key, regexes in PATTERNS:
        for pattern in regexes:
            if re.search(pattern, t):
                if key == "time":
                    response = _time_text()
                elif key == "date":
                    response = _date_text()
                elif key == "battery":
                    response = _battery_text()
                else:
                    response = _daily_choice(key, FAST_REPLY_VARIANTS.get(key, []), raw)
                if response:
                    return {"key": key, "response": response, "text": raw, "local": True}
    return None


def all_fast_reply_examples() -> dict[str, list[str]]:
    return FAST_REPLY_VARIANTS

# === JARVIS_V4083_HELP_FAST_REPLY_BEGIN ===
# Jarvis v4.0.8.3
# Añade fast reply local para "ayúdame" / "necesito ayuda" sin depender del LLM.
try:
    import re as _jarvis_v4083_re
    import logging as _jarvis_v4083_logging

    def _jarvis_v4083_norm(text):
        t = str(text or "").strip().lower()
        repl = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "¿": "", "?": "", "¡": "", "!": "",
        }
        for a, b in repl.items():
            t = t.replace(a, b)
        t = _jarvis_v4083_re.sub(r"[^a-z0-9ñ\s]", " ", t)
        t = _jarvis_v4083_re.sub(r"\s+", " ", t).strip()
        return t

    def _jarvis_v4083_is_help_request(text):
        n = _jarvis_v4083_norm(text)
        patterns = [
            r"^ayudame$",
            r"^ayudame por favor$",
            r"^ayuda me$",
            r"^ayuzame$",
            r"^ayuzame por favor$",
            r"^ayusame$",
            r"^ayudame jarvis$",
            r"^necesito ayuda$",
            r"^ocup[oó] ayuda$",
            r"^quiero ayuda$",
            r"^auxilio$",
            r"^ayuda a mi$",
        ]
        return any(_jarvis_v4083_re.search(p, n) for p in patterns)

    def _jarvis_v4083_build_like(sample, key, response):
        # Intenta devolver el mismo tipo que usa el sistema actual.
        try:
            if isinstance(sample, tuple):
                if len(sample) >= 2:
                    data = list(sample)
                    data[0] = key
                    data[1] = response
                    return tuple(data)
            if isinstance(sample, dict):
                out = dict(sample)
                for k in ("key", "match", "category", "name", "fast_key"):
                    if k in out:
                        out[k] = key
                for k in ("response", "text", "reply"):
                    if k in out:
                        out[k] = response
                if "response" not in out:
                    out["response"] = response
                if "key" not in out and "match" not in out and "category" not in out:
                    out["key"] = key
                return out
        except Exception:
            pass
        return {"key": key, "response": response}

    def _jarvis_v4083_wrap(orig, name):
        def _wrapped(text, *args, **kwargs):
            if _jarvis_v4083_is_help_request(text):
                try:
                    sample = None
                    try:
                        sample = orig("hola jarvis", *args, **kwargs)
                    except Exception:
                        pass
                    result = _jarvis_v4083_build_like(sample, "help", "¿En qué necesitas ayuda?")
                    _jarvis_v4083_logging.getLogger("jarvis").info(
                        "FAST_REPLY local help usado text=%r",
                        text,
                    )
                    try:
                        from jarvis.bus.event_bus import EventBus
                        EventBus().publish(
                            "fast_reply.matched",
                            {"text": text, "response": "¿En qué necesitas ayuda?", "fast_key": "help"},
                            source="fast_reply_help",
                        )
                    except Exception:
                        pass
                    return result
                except Exception:
                    pass
            return orig(text, *args, **kwargs)
        _wrapped.__jarvis_v4083_help__ = True
        _wrapped.__wrapped__ = orig
        return _wrapped

    for _name in ("match_fast_reply", "find_fast_reply", "lookup_fast_reply", "get_fast_reply", "match"):
        _obj = globals().get(_name)
        if callable(_obj) and not getattr(_obj, "__jarvis_v4083_help__", False):
            globals()[_name] = _jarvis_v4083_wrap(_obj, _name)

except Exception:
    pass
# === JARVIS_V4083_HELP_FAST_REPLY_END ===

# === JARVIS_V4088_HELP_FILLER_FAST_REPLY_BEGIN ===
# Jarvis v4.0.8.8
# Acepta prefijos coloquiales: "ay, ayudame", "eh ayudame", etc. para fast reply local.
try:
    import re as _jarvis_v4088_re
    import logging as _jarvis_v4088_logging

    def _jarvis_v4088_norm(text):
        t = str(text or "").strip().lower()
        repl = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "¿": "", "?": "", "¡": "", "!": "",
        }
        for a, b in repl.items():
            t = t.replace(a, b)
        t = _jarvis_v4088_re.sub(r"[^a-z0-9ñ\s]", " ", t)
        t = _jarvis_v4088_re.sub(r"\s+", " ", t).strip()
        return t

    def _jarvis_v4088_help_like(text):
        n = _jarvis_v4088_norm(text)
        # quita muletillas al inicio
        n = _jarvis_v4088_re.sub(r"^(ay|eh|oye|ey|hey|ah|mmm|mm|este|bueno)\s+", "", n).strip()
        pats = [
            r"^ayudame$",
            r"^ayudame por favor$",
            r"^necesito ayuda$",
            r"^ocupo ayuda$",
            r"^quiero ayuda$",
            r"^ayuda a mi$",
        ]
        return any(_jarvis_v4088_re.search(p, n) for p in pats)

    def _jarvis_v4088_build_like(sample, key, response):
        try:
            if isinstance(sample, tuple):
                data = list(sample)
                if len(data) >= 2:
                    data[0] = key
                    data[1] = response
                    return tuple(data)
            if isinstance(sample, dict):
                out = dict(sample)
                for k in ("key", "match", "category", "name", "fast_key"):
                    if k in out:
                        out[k] = key
                for k in ("response", "text", "reply"):
                    if k in out:
                        out[k] = response
                if "response" not in out:
                    out["response"] = response
                if "key" not in out and "match" not in out and "category" not in out:
                    out["key"] = key
                return out
        except Exception:
            pass
        return {"key": key, "response": response}

    def _jarvis_v4088_wrap(orig, name):
        def _wrapped(text, *args, **kwargs):
            if _jarvis_v4088_help_like(text):
                try:
                    sample = None
                    try:
                        sample = orig("hola jarvis", *args, **kwargs)
                    except Exception:
                        pass
                    result = _jarvis_v4088_build_like(sample, "help", "¿En qué necesitas ayuda?")
                    _jarvis_v4088_logging.getLogger("jarvis").info(
                        "FAST_REPLY local help filler usado text=%r",
                        text,
                    )
                    try:
                        from jarvis.bus.event_bus import EventBus
                        EventBus().publish(
                            "fast_reply.matched",
                            {"text": text, "response": "¿En qué necesitas ayuda?", "fast_key": "help"},
                            source="fast_reply_help_filler",
                        )
                    except Exception:
                        pass
                    return result
                except Exception:
                    pass
            return orig(text, *args, **kwargs)
        _wrapped.__jarvis_v4088_help__ = True
        _wrapped.__wrapped__ = orig
        return _wrapped

    for _name in ("match_fast_reply", "find_fast_reply", "lookup_fast_reply", "get_fast_reply", "match"):
        _obj = globals().get(_name)
        if callable(_obj) and not getattr(_obj, "__jarvis_v4088_help__", False):
            globals()[_name] = _jarvis_v4088_wrap(_obj, _name)

except Exception:
    pass
# === JARVIS_V4088_HELP_FILLER_FAST_REPLY_END ===
