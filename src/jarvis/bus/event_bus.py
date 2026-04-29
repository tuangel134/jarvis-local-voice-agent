from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DB = Path.home() / ".local/share/jarvis/events_bus.db"


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dict__"):
        try:
            return dict(obj.__dict__)
        except Exception:
            pass
    return str(obj)


def _safe_json(data: Any) -> str:
    try:
        return json.dumps(data, ensure_ascii=False, default=_json_default)
    except Exception:
        return json.dumps({"_unserializable": str(data)}, ensure_ascii=False)


def _summarize_payload(payload: Any, max_len: int = 160) -> str:
    try:
        if isinstance(payload, dict):
            if "text" in payload:
                s = str(payload.get("text", ""))
            elif "input_text" in payload:
                s = str(payload.get("input_text", ""))
            elif "intent" in payload:
                s = f"{payload.get('intent')} {payload.get('entities', '')}"
            elif "response" in payload:
                s = str(payload.get("response", ""))
            else:
                s = json.dumps(payload, ensure_ascii=False, default=_json_default)
        else:
            s = str(payload)
    except Exception:
        s = str(payload)

    s = " ".join(s.split())
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _intent_to_dict(intent: Any) -> dict[str, Any]:
    if intent is None:
        return {}

    if isinstance(intent, dict):
        return {
            "name": intent.get("name") or intent.get("intent_name") or "",
            "confidence": intent.get("confidence") or intent.get("intent_confidence") or 0.0,
            "entities": intent.get("entities") or {},
            "raw_text": intent.get("raw_text") or intent.get("text") or "",
        }

    return {
        "name": getattr(intent, "name", ""),
        "confidence": getattr(intent, "confidence", 0.0),
        "entities": getattr(intent, "entities", {}) or {},
        "raw_text": getattr(intent, "raw_text", "") or getattr(intent, "text", ""),
    }


class EventBus:
    def __init__(
        self,
        db_path: str | Path | dict | None = None,
        config: dict | None = None,
        logger: Any | None = None,
    ):
        self.logger = logger
        self._lock = threading.RLock()

        if isinstance(db_path, dict) and config is None:
            config = db_path
            db_path = None

        if isinstance(config, dict) and db_path is None:
            bus_cfg = config.get("bus", {}) if isinstance(config.get("bus", {}), dict) else {}
            db_path = bus_cfg.get("db_path") or config.get("events_bus_db")

        self.db_path = Path(db_path).expanduser() if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _warn(self, msg: str) -> None:
        try:
            if self.logger:
                self.logger.warning(msg)
        except Exception:
            pass

    def _connect(self):
        con = sqlite3.connect(str(self.db_path), timeout=0.2)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        try:
            with self._connect() as con:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS bus_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        summary TEXT,
                        source TEXT DEFAULT 'jarvis'
                    )
                    """
                )
                con.execute("CREATE INDEX IF NOT EXISTS idx_bus_events_topic ON bus_events(topic)")
                con.execute("CREATE INDEX IF NOT EXISTS idx_bus_events_timestamp ON bus_events(timestamp)")
                con.commit()
        except Exception as exc:
            self._warn(f"NeoBus init falló: {exc}")

    def publish(self, topic: str, payload: dict | None = None, source: str = "jarvis") -> bool:
        payload = payload or {}
        try:
            topic = str(topic or "").strip()
            if not topic:
                return False

            timestamp = datetime.now().isoformat(timespec="seconds")
            payload_json = _safe_json(payload)
            summary = _summarize_payload(payload)

            with self._lock:
                with self._connect() as con:
                    con.execute(
                        """
                        INSERT INTO bus_events(timestamp, topic, payload_json, summary, source)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (timestamp, topic, payload_json, summary, source),
                    )
                    con.commit()

            return True
        except Exception as exc:
            self._warn(f"NeoBus publish falló topic={topic}: {exc}")
            return False

    def list_events(self, topic: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 500))
        try:
            with self._connect() as con:
                if topic:
                    rows = con.execute(
                        """
                        SELECT * FROM bus_events
                        WHERE topic = ?
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (topic, limit),
                    ).fetchall()
                else:
                    rows = con.execute(
                        """
                        SELECT * FROM bus_events
                        ORDER BY id DESC
                        LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()

            return [dict(r) for r in rows]
        except Exception as exc:
            self._warn(f"NeoBus list_events falló: {exc}")
            return []

    def get_last(self, topic: str | None = None) -> dict[str, Any] | None:
        rows = self.list_events(topic=topic, limit=1)
        return rows[0] if rows else None

    def count_events(self, topic: str | None = None) -> int:
        try:
            with self._connect() as con:
                if topic:
                    row = con.execute(
                        "SELECT COUNT(*) AS total FROM bus_events WHERE topic=?",
                        (topic,),
                    ).fetchone()
                else:
                    row = con.execute("SELECT COUNT(*) AS total FROM bus_events").fetchone()
            return int(row["total"] or 0)
        except Exception as exc:
            self._warn(f"NeoBus count_events falló: {exc}")
            return 0

    def format_events(self, topic: str | None = None, limit: int = 20) -> str:
        rows = self.list_events(topic=topic, limit=limit)
        if not rows:
            if topic:
                return f"No hay eventos para topic={topic}."
            return "No hay eventos del bus todavía."

        out = []
        out.append("  ID  timestamp            topic                         summary")
        out.append("--------------------------------------------------------------------------")

        for r in rows:
            event_id = int(r.get("id") or 0)
            ts = str(r.get("timestamp") or "")[:19]
            tp = str(r.get("topic") or "")[:28]
            summary = str(r.get("summary") or "")
            if len(summary) > 68:
                summary = summary[:65] + "..."
            out.append(f"{event_id:4d}  {ts:<19}  {tp:<28}  {summary}")

        return "\n".join(out)


def _extract_record_payload(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    input_text = kwargs.get("input_text")
    intent = kwargs.get("intent")
    planner_steps = kwargs.get("planner_steps")
    result = kwargs.get("result") or kwargs.get("result_text")
    success = kwargs.get("success")
    duration_ms = kwargs.get("duration_ms")
    error_text = kwargs.get("error_text")

    if input_text is None and len(args) >= 1:
        input_text = args[0]
    if intent is None and len(args) >= 2:
        intent = args[1]
    if planner_steps is None and len(args) >= 3:
        planner_steps = args[2]
    if not result and len(args) >= 4:
        result = args[3]
    if success is None and len(args) >= 5:
        success = args[4]
    if duration_ms is None and len(args) >= 6:
        duration_ms = args[5]
    if error_text is None and len(args) >= 7:
        error_text = args[6]

    if success is None:
        success = True
    if duration_ms is None:
        duration_ms = 0

    intent_dict = _intent_to_dict(intent)

    return {
        "input_text": input_text or "",
        "intent": intent_dict.get("name", ""),
        "intent_confidence": intent_dict.get("confidence", 0.0),
        "entities": intent_dict.get("entities", {}),
        "raw_text": intent_dict.get("raw_text", ""),
        "planner_steps": planner_steps or [],
        "response": result or "",
        "success": bool(success),
        "duration_ms": int(duration_ms or 0),
        "error_text": error_text or "",
    }


def install_event_journal_bridge(event_bus: EventBus, logger: Any | None = None) -> bool:
    try:
        from jarvis.brain.event_journal import EventJournal
    except Exception as exc:
        try:
            if logger:
                logger.warning(f"No pude instalar bridge EventJournal->NeoBus: {exc}")
        except Exception:
            pass
        return False

    if getattr(EventJournal.record, "_neobus_bridge_installed", False):
        return True

    original_record = EventJournal.record

    def record_with_bus(self, *args, **kwargs):
        event_id = original_record(self, *args, **kwargs)

        try:
            payload = _extract_record_payload(args, kwargs)
            payload["event_journal_id"] = event_id

            text = payload.get("input_text", "")
            intent_name = payload.get("intent", "")
            steps = payload.get("planner_steps") or []
            response = payload.get("response", "")

            if text:
                event_bus.publish(
                    "perception.text.transcribed",
                    {"text": text, "event_journal_id": event_id},
                    source="journal_bridge",
                )

            if intent_name:
                event_bus.publish(
                    "intent.detected",
                    {
                        "text": text,
                        "intent": intent_name,
                        "confidence": payload.get("intent_confidence", 0.0),
                        "entities": payload.get("entities", {}),
                        "event_journal_id": event_id,
                    },
                    source="journal_bridge",
                )

            if steps:
                event_bus.publish(
                    "planner.steps",
                    {
                        "text": text,
                        "intent": intent_name,
                        "steps": steps,
                        "event_journal_id": event_id,
                    },
                    source="journal_bridge",
                )

            event_bus.publish("action.executed", payload, source="journal_bridge")

            if response:
                event_bus.publish(
                    "tts.response.generated",
                    {
                        "text": response,
                        "intent": intent_name,
                        "success": payload.get("success", True),
                        "duration_ms": payload.get("duration_ms", 0),
                        "event_journal_id": event_id,
                    },
                    source="journal_bridge",
                )

        except Exception as exc:
            try:
                if logger:
                    logger.warning(f"NeoBus journal bridge falló: {exc}")
            except Exception:
                pass

        return event_id

    record_with_bus._neobus_bridge_installed = True
    EventJournal.record = record_with_bus

    return True


def create_default_bus(config: dict | None = None, logger: Any | None = None) -> EventBus:
    return EventBus(config=config, logger=logger)

# ---------------------------------------------------------------------------
# v4.0.1 NeoBus Inspector helpers
# ---------------------------------------------------------------------------

def _neobus_v401_parse_payload(payload_json: str):
    try:
        return json.loads(payload_json or "{}")
    except Exception:
        return {"_raw": payload_json or ""}


def _neobus_v401_get_event(self, event_id: int):
    try:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM bus_events WHERE id=?",
                (int(event_id),),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["payload"] = _neobus_v401_parse_payload(data.get("payload_json", ""))
        return data
    except Exception as exc:
        self._warn(f"NeoBus get_event falló: {exc}")
        return None


def _neobus_v401_get_last_event(self, topic: str | None = None):
    rows = self.list_events(topic=topic, limit=1)
    if not rows:
        return None
    event_id = rows[0].get("id")
    return self.get_event(event_id)


def _neobus_v401_format_event_json(self, event_id: int) -> str:
    event = self.get_event(event_id)
    if not event:
        return f"No encontré evento #{event_id}."

    event.pop("payload_json", None)
    try:
        return json.dumps(event, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        return str(event)


def _neobus_v401_format_last_json(self, topic: str | None = None) -> str:
    event = self.get_last_event(topic=topic)
    if not event:
        if topic:
            return f"No hay eventos para topic={topic}."
        return "No hay eventos del bus todavía."

    event.pop("payload_json", None)
    try:
        return json.dumps(event, ensure_ascii=False, indent=2, default=_json_default)
    except Exception:
        return str(event)


def _neobus_v401_stats(self) -> dict[str, Any]:
    try:
        with self._connect() as con:
            total_row = con.execute("SELECT COUNT(*) AS total FROM bus_events").fetchone()
            topic_rows = con.execute(
                """
                SELECT topic, COUNT(*) AS total
                FROM bus_events
                GROUP BY topic
                ORDER BY total DESC, topic ASC
                """
            ).fetchall()
            last_row = con.execute(
                "SELECT id, timestamp, topic FROM bus_events ORDER BY id DESC LIMIT 1"
            ).fetchone()

        return {
            "db_path": str(self.db_path),
            "total": int(total_row["total"] or 0),
            "topics": {str(r["topic"]): int(r["total"] or 0) for r in topic_rows},
            "last": dict(last_row) if last_row else None,
        }
    except Exception as exc:
        self._warn(f"NeoBus stats falló: {exc}")
        return {"db_path": str(self.db_path), "total": 0, "topics": {}, "last": None}


def _neobus_v401_format_stats(self) -> str:
    stats = self.stats()
    out = []
    out.append(f"DB: {stats.get('db_path')}")
    out.append(f"Total eventos: {stats.get('total', 0)}")

    last = stats.get("last")
    if last:
        out.append(f"Último evento: #{last.get('id')} {last.get('timestamp')} {last.get('topic')}")

    out.append("")
    out.append("topic                         total")
    out.append("-----------------------------------")

    topics = stats.get("topics") or {}
    if not topics:
        out.append("(sin eventos)")
    else:
        for topic, total in topics.items():
            out.append(f"{topic[:28]:28}  {total}")

    return "\n".join(out)


def _neobus_v401_clear_events(self) -> int:
    try:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) AS total FROM bus_events").fetchone()
            total = int(row["total"] or 0)
            con.execute("DELETE FROM bus_events")
            con.commit()
        return total
    except Exception as exc:
        self._warn(f"NeoBus clear_events falló: {exc}")
        return 0


if not hasattr(EventBus, "get_event"):
    EventBus.get_event = _neobus_v401_get_event

if not hasattr(EventBus, "get_last_event"):
    EventBus.get_last_event = _neobus_v401_get_last_event

if not hasattr(EventBus, "format_event_json"):
    EventBus.format_event_json = _neobus_v401_format_event_json

if not hasattr(EventBus, "format_last_json"):
    EventBus.format_last_json = _neobus_v401_format_last_json

if not hasattr(EventBus, "stats"):
    EventBus.stats = _neobus_v401_stats

if not hasattr(EventBus, "format_stats"):
    EventBus.format_stats = _neobus_v401_format_stats

if not hasattr(EventBus, "clear_events"):
    EventBus.clear_events = _neobus_v401_clear_events

