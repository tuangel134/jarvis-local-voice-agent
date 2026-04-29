from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jarvis.brain.event_journal import EventJournal


def _short_path(path: str) -> str:
    if not path:
        return ""
    try:
        p = Path(path).expanduser()
        home = Path.home()
        if str(p).startswith(str(home)):
            return "~/" + str(p.relative_to(home))
        return str(p)
    except Exception:
        return str(path)


class Explainer:
    # Explicador sin LLM para Event Journal.
    #
    # Compatibilidad:
    # - Explainer() usa EventJournal().get_last()
    # - Explainer(EventJournal()) usa ese journal
    # - Explainer(dict_event) usa directamente ese evento
    #
    # Esto corrige el caso donde el launcher antiguo de `jarvis explain last`
    # pasa un dict en vez de un EventJournal.

    def __init__(self, journal: EventJournal | dict[str, Any] | None = None):
        self._explicit_event: dict[str, Any] | None = None

        if isinstance(journal, dict):
            # Puede ser un evento real o puede ser config.yaml cargado por el launcher.
            # Solo tratamos como evento si tiene columnas del journal.
            event_keys = {"input_text", "intent_name", "planner_steps_json", "result_text", "duration_ms", "success"}
            if any(k in journal for k in event_keys):
                self._explicit_event = journal
                self.journal = EventJournal()
            else:
                # Es config dict; EventJournal sabe ignorarlo o leer ruta si existe.
                self.journal = EventJournal(journal)
        elif journal is None:
            self.journal = EventJournal()
        else:
            self.journal = journal

    def _get_event(self) -> dict[str, Any] | None:
        if self._explicit_event is not None:
            return self._explicit_event

        if hasattr(self.journal, "get_last"):
            return self.journal.get_last()

        return None

    def explain_last(self) -> str:
        event = self._get_event()
        if not event:
            return "No tengo eventos registrados todavía."

        parts: list[str] = []

        input_text = event.get("input_text") or ""
        intent_name = event.get("intent_name") or ""
        result = event.get("result_text") or ""
        duration_ms = event.get("duration_ms") or 0
        success = bool(event.get("success"))
        feedback = event.get("feedback")

        if input_text:
            parts.append(f"Entrada: {input_text}")

        if intent_name:
            parts.append(f"Intención detectada: {intent_name}.")

        steps_raw = event.get("planner_steps_json") or "[]"
        try:
            steps = json.loads(steps_raw)
        except Exception:
            steps = []

        plan_parts: list[str] = []

        for step in steps:
            if not isinstance(step, dict):
                continue

            tool = step.get("tool", "")
            params = step.get("params", {}) or {}
            if not isinstance(params, dict):
                params = {}

            if tool == "open_folder":
                path = _short_path(params.get("path", ""))
                plan_parts.append(
                    f"abrí {path} porque detecté una carpeta explícita en tu comando"
                )
            elif tool == "search_files":
                query = params.get("query", "")
                base = _short_path(params.get("base", "") or params.get("path", ""))
                if base:
                    plan_parts.append(f"busqué '{query}' dentro de {base}")
                else:
                    plan_parts.append(f"busqué '{query}'")
            elif tool == "open_result":
                idx = params.get("index", "")
                plan_parts.append(
                    f"abrí el resultado #{idx} porque pediste abrir un resultado de la búsqueda"
                )
            elif tool == "open_url":
                target = params.get("url") or params.get("target") or params.get("url_name") or ""
                plan_parts.append(f"abrí {target}")
            elif tool == "play_music":
                query = params.get("query", "")
                platform = params.get("platform", "")
                if platform:
                    plan_parts.append(f"reproduje '{query}' en {platform}")
                else:
                    plan_parts.append(f"reproduje '{query}'")
            else:
                plan_parts.append(f"ejecuté {tool} con parámetros {params}")

        if plan_parts:
            parts.append("Plan: " + ". Después, ".join(plan_parts) + ".")

        if result:
            parts.append(f"Resultado: {result}")

        fb = ""
        if feedback == 1:
            fb = " Feedback: marcado como bueno."
        elif feedback == -1:
            fb = " Feedback: marcado como malo."

        parts.append(f"Estado: {'éxito' if success else 'fallo'} en {duration_ms} ms.{fb}")

        return "\n".join(parts)


def explain_last() -> str:
    return Explainer().explain_last()
