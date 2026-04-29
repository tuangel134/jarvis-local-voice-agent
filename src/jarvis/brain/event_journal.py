from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class EventJournal:
    def __init__(
        self,
        db_path: str | Path | dict | None = None,
        logger: Any | None = None,
        *args: Any,
        **kwargs: Any,
    ):
        # Compatibilidad:
        # - EventJournal()
        # - EventJournal("/ruta/events.db")
        # - EventJournal(config_dict)
        # - EventJournal(config_dict, logger)
        self.logger = logger

        if isinstance(db_path, dict):
            candidate = (
                db_path.get("events_db")
                or db_path.get("event_journal_db")
                or db_path.get("journal_db")
            )
            if not candidate:
                data_cfg = db_path.get("data", {}) if isinstance(db_path.get("data", {}), dict) else {}
                paths_cfg = db_path.get("paths", {}) if isinstance(db_path.get("paths", {}), dict) else {}
                candidate = (
                    data_cfg.get("events_db")
                    or paths_cfg.get("events_db")
                    or paths_cfg.get("event_journal_db")
                )
            db_path = candidate

        self.db_path = Path(db_path).expanduser() if db_path else Path.home() / ".local/share/jarvis/events.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    input_text TEXT,
                    intent_name TEXT,
                    intent_confidence REAL,
                    planner_steps_json TEXT,
                    result_text TEXT,
                    success INTEGER,
                    duration_ms INTEGER,
                    error_text TEXT,
                    feedback INTEGER DEFAULT NULL
                )
                """
            )

            cols = {r["name"] for r in con.execute("PRAGMA table_info(events)").fetchall()}
            if "feedback" not in cols:
                con.execute("ALTER TABLE events ADD COLUMN feedback INTEGER DEFAULT NULL")

            con.execute(
                """
                CREATE TABLE IF NOT EXISTS aliases (
                    alias TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    hits INTEGER DEFAULT 0,
                    last_used TEXT
                )
                """
            )

            con.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_events_feedback ON events(feedback)")
            con.commit()

    def _json_default(self, obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        if hasattr(obj, "__dict__"):
            return dict(obj.__dict__)
        return str(obj)

    @staticmethod
    def normalize_steps(steps: Any) -> list[dict[str, Any]]:
        """
        Normaliza planner_steps para que daemon.py pueda llamar:
        EventJournal.normalize_steps(...)
        """
        if steps is None:
            return []

        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                return []

        if is_dataclass(steps):
            steps = asdict(steps)

        if isinstance(steps, dict):
            if "planner_steps" in steps:
                steps = steps.get("planner_steps")
            elif "steps" in steps:
                steps = steps.get("steps")
            else:
                steps = [steps]

        if not isinstance(steps, list):
            return []

        normalized: list[dict[str, Any]] = []
        for step in steps:
            if step is None:
                continue

            if is_dataclass(step):
                step = asdict(step)
            elif hasattr(step, "__dict__") and not isinstance(step, dict):
                step = dict(step.__dict__)

            if isinstance(step, dict):
                tool = str(step.get("tool") or step.get("name") or step.get("action") or "")
                params = step.get("params") or step.get("entities") or {}
                if not isinstance(params, dict):
                    params = {"value": params}
                normalized.append({"tool": tool, "params": params})
            else:
                normalized.append({"tool": str(step), "params": {}})

        return normalized

    def _intent_name(self, intent: Any) -> str:
        if intent is None:
            return ""
        if isinstance(intent, dict):
            return str(intent.get("name") or intent.get("intent_name") or "")
        return str(getattr(intent, "name", ""))

    def _intent_confidence(self, intent: Any) -> float:
        if intent is None:
            return 0.0
        if isinstance(intent, dict):
            return float(intent.get("confidence") or intent.get("intent_confidence") or 0.0)
        return float(getattr(intent, "confidence", 0.0) or 0.0)

    def record(
        self,
        input_text: str = "",
        intent: Any = None,
        planner_steps: Any = None,
        result: str = "",
        success: bool = True,
        duration_ms: int = 0,
        error_text: str | None = None,
        result_text: str | None = None,
        **kwargs: Any,
    ) -> int:
        """
        Compatible con llamadas viejas/nuevas:
        - record(..., result="...")
        - record(..., result_text="...")
        - record(..., intent_name="...", intent_confidence=...)
        """
        if result_text is not None and not result:
            result = result_text

        if "result_text" in kwargs and not result:
            result = str(kwargs.get("result_text") or "")

        if "duration" in kwargs and not duration_ms:
            duration_ms = int(kwargs.get("duration") or 0)

        if intent is None and ("intent_name" in kwargs or "intent_confidence" in kwargs):
            intent = {
                "name": kwargs.get("intent_name", ""),
                "confidence": kwargs.get("intent_confidence", 0.0),
            }

        steps_json = json.dumps(self.normalize_steps(planner_steps), ensure_ascii=False, default=self._json_default)
        ts = datetime.now().isoformat(timespec="seconds")

        with self._connect() as con:
            cur = con.execute(
                """
                INSERT INTO events (
                    timestamp, input_text, intent_name, intent_confidence,
                    planner_steps_json, result_text, success, duration_ms,
                    error_text, feedback
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    ts,
                    input_text,
                    self._intent_name(intent),
                    self._intent_confidence(intent),
                    steps_json,
                    result,
                    1 if success else 0,
                    int(duration_ms or 0),
                    error_text,
                ),
            )
            con.commit()
            return int(cur.lastrowid)

    def get_last(self) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def list_events(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 10), 100))
        with self._connect() as con:
            rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def format_history(self, limit: int = 10) -> str:
        rows = self.list_events(limit)
        if not rows:
            return "No hay eventos registrados."

        out = []
        out.append("  ID  OK      ms  intent            feedback  input")
        out.append("---------------------------------------------------------------")

        for r in rows:
            event_id = int(r.get("id") or 0)
            ok = "✓" if int(r.get("success") or 0) else "✗"
            ms = int(r.get("duration_ms") or 0)
            intent = str(r.get("intent_name") or "")[:16]
            input_text = " ".join(str(r.get("input_text") or "").split())
            if len(input_text) > 52:
                input_text = input_text[:49] + "..."

            fb = r.get("feedback")
            if fb == 1:
                feedback = "bueno"
            elif fb == -1:
                feedback = "malo"
            else:
                feedback = "-"

            out.append(f"{event_id:4d}   {ok}  {ms:6d}  {intent:<16}  {feedback:<8}  {input_text}")

        return "\n".join(out)

    def format_events(self, limit: int = 10) -> str:
        return self.format_history(limit)

    def set_feedback_last(self, value: int) -> dict[str, Any] | None:
        value = 1 if int(value) > 0 else -1
        last = self.get_last()
        if not last:
            return None

        with self._connect() as con:
            con.execute("UPDATE events SET feedback=? WHERE id=?", (value, int(last["id"])))
            con.commit()

        last["feedback"] = value
        return last

    def feedback_stats(self) -> dict[str, int]:
        with self._connect() as con:
            row = con.execute(
                """
                SELECT
                  SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) AS good,
                  SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) AS bad,
                  SUM(CASE WHEN feedback IS NULL THEN 1 ELSE 0 END) AS none,
                  COUNT(*) AS total
                FROM events
                """
            ).fetchone()
            return {
                "good": int(row["good"] or 0),
                "bad": int(row["bad"] or 0),
                "none": int(row["none"] or 0),
                "total": int(row["total"] or 0),
            }

    @staticmethod
    def normalize_alias(text: str) -> str:
        t = str(text or "").strip().lower()
        t = t.strip("'\"“”‘’`")
        t = t.replace("_", " ").replace("-", " ")
        t = " ".join(t.split())
        return t

    def remember_alias(self, alias: str, path: str) -> bool:
        alias_norm = self.normalize_alias(alias)
        if not alias_norm:
            raise ValueError("Alias vacío.")

        expanded = str(Path(path).expanduser())

        with self._connect() as con:
            con.execute(
                """
                INSERT INTO aliases(alias, path, created_at, updated_at, hits, last_used)
                VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 0, NULL)
                ON CONFLICT(alias) DO UPDATE SET
                    path=excluded.path,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (alias_norm, expanded),
            )
            con.commit()

        return True

    def forget_alias(self, alias: str) -> bool:
        alias_norm = self.normalize_alias(alias)
        with self._connect() as con:
            cur = con.execute("DELETE FROM aliases WHERE alias=?", (alias_norm,))
            con.commit()
            return cur.rowcount > 0

    def list_aliases(self) -> list[dict[str, Any]]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT alias, path, created_at, updated_at, hits, last_used FROM aliases ORDER BY alias ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_alias(self, alias: str) -> str:
        alias_norm = self.normalize_alias(alias)
        if not alias_norm:
            return ""

        with self._connect() as con:
            row = con.execute("SELECT path FROM aliases WHERE alias=?", (alias_norm,)).fetchone()
            if not row:
                return ""

            con.execute(
                "UPDATE aliases SET hits=COALESCE(hits,0)+1, last_used=CURRENT_TIMESTAMP WHERE alias=?",
                (alias_norm,),
            )
            con.commit()
            return str(row["path"] or "")

    def memory_stats(self) -> dict[str, Any]:
        fb = self.feedback_stats()
        with self._connect() as con:
            aliases = con.execute("SELECT COUNT(*) AS total FROM aliases").fetchone()
        return {
            "events": fb["total"],
            "feedback_good": fb["good"],
            "feedback_bad": fb["bad"],
            "feedback_none": fb["none"],
            "aliases": int(aliases["total"] or 0),
            "db_path": str(self.db_path),
        }


def get_journal() -> EventJournal:
    return EventJournal()


def set_feedback_last(value: int) -> dict[str, Any] | None:
    return EventJournal().set_feedback_last(value)


def remember_alias(alias: str, path: str) -> bool:
    return EventJournal().remember_alias(alias, path)


def resolve_alias(alias: str) -> str:
    return EventJournal().resolve_alias(alias)

# ---------------------------------------------------------------------------
# v3.4.8 compatibility: clean dictated query inside planner_steps before journaling
# ---------------------------------------------------------------------------
try:
    import re as _jarvis_journal_re

    def _jarvis_v34_8_clean_journal_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jarvis_journal_re.sub(r"\s+", " ", q).strip()
        corrections = {
            "a a b": "aab",
            "a a ve": "aab",
            "aave": "aab",
            "aap": "aab",
            "abb": "aab",
        }
        if q in corrections:
            return corrections[q]
        q = _jarvis_journal_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jarvis_journal_re.sub(r"\ba\s*a\s*b\b", "aab", q)
        q = _jarvis_journal_re.sub(r"\b(aap|abb|aave)\b", "aab", q)
        return _jarvis_journal_re.sub(r"\s+", " ", q).strip()

    if "EventJournal" in globals() and hasattr(EventJournal, "normalize_steps") and not getattr(EventJournal.normalize_steps, "_jarvis_v34_8_wrapped", False):
        _jarvis_v34_8_orig_normalize_steps = EventJournal.normalize_steps

        def _jarvis_v34_8_normalize_steps(steps):
            normalized = _jarvis_v34_8_orig_normalize_steps(steps)
            for step in normalized:
                params = step.get("params") or {}
                if isinstance(params, dict):
                    if "query" in params:
                        params["query"] = _jarvis_v34_8_clean_journal_query(params.get("query"))
                    if "search_query" in params:
                        params["search_query"] = _jarvis_v34_8_clean_journal_query(params.get("search_query"))
            return normalized

        _jarvis_v34_8_normalize_steps._jarvis_v34_8_wrapped = True
        EventJournal.normalize_steps = staticmethod(_jarvis_v34_8_normalize_steps)
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.9 compatibility: fuzzy aliases for common STT mistakes
# ---------------------------------------------------------------------------
try:
    import difflib as _jv349_difflib

    if "EventJournal" in globals() and not getattr(EventJournal.resolve_alias, "_jv349_fuzzy_wrapped", False):
        _jv349_orig_resolve_alias = EventJournal.resolve_alias

        def _jv349_resolve_alias(self, alias: str) -> str:
            # 1) exact behavior first
            exact = _jv349_orig_resolve_alias(self, alias)
            if exact:
                return exact

            q = self.normalize_alias(alias)

            # 2) common Whisper mistakes for "builds"
            correction_candidates = {
                "build": "builds",
                "builds": "builds",
                "buils": "builds",
                "buil": "builds",
                "buells": "builds",
                "buels": "builds",
                "bills": "builds",
                "bilz": "builds",
            }
            if q in correction_candidates:
                corrected = correction_candidates[q]
                val = _jv349_orig_resolve_alias(self, corrected)
                if val:
                    return val

            # 3) singular/plural fallback
            if q.endswith("s"):
                val = _jv349_orig_resolve_alias(self, q[:-1])
                if val:
                    return val
            else:
                val = _jv349_orig_resolve_alias(self, q + "s")
                if val:
                    return val

            # 4) fuzzy fallback over saved aliases
            try:
                aliases = self.list_aliases()
                names = [str(r.get("alias") or "") for r in aliases]
                matches = _jv349_difflib.get_close_matches(q, names, n=1, cutoff=0.70)
                if matches:
                    return _jv349_orig_resolve_alias(self, matches[0])
            except Exception:
                pass

            return ""

        _jv349_resolve_alias._jv349_fuzzy_wrapped = True
        EventJournal.resolve_alias = _jv349_resolve_alias
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.12 compatibility: stronger STT fuzzy aliases for "builds"
# ---------------------------------------------------------------------------
try:
    if "EventJournal" in globals() and hasattr(EventJournal, "resolve_alias") and not getattr(EventJournal.resolve_alias, "_jv3412_fuzzy_builds", False):
        _jv3412_orig_resolve_alias = EventJournal.resolve_alias

        def _jv3412_resolve_alias(self, alias: str) -> str:
            # Exact/fuzzy behavior from previous patches first.
            val = _jv3412_orig_resolve_alias(self, alias)
            if val:
                return val

            q = self.normalize_alias(alias)

            # Faster-Whisper / Spanish pronunciation mistakes for "builds".
            builds_variants = {
                "build", "builds", "buil", "buils", "buid", "buidas",
                "buells", "buels", "boils", "boil", "bills", "bilz",
                "viles", "biles", "buils", "builes", "bields", "bield",
                "bild", "bilds", "builts", "blinds",
            }

            if q in builds_variants:
                val = _jv3412_orig_resolve_alias(self, "builds")
                if val:
                    return val

            # Si una frase completa contiene una variante, también resolverla.
            words = set(q.split())
            if words & builds_variants:
                val = _jv3412_orig_resolve_alias(self, "builds")
                if val:
                    return val

            return ""

        _jv3412_resolve_alias._jv3412_fuzzy_builds = True
        EventJournal.resolve_alias = _jv3412_resolve_alias
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.13 compatibility: stronger fuzzy alias for build/builds variants
# ---------------------------------------------------------------------------
try:
    if "EventJournal" in globals() and hasattr(EventJournal, "resolve_alias") and not getattr(EventJournal.resolve_alias, "_jv3413_builds_fuzzy", False):
        _jv3413_orig_resolve_alias = EventJournal.resolve_alias

        def _jv3413_resolve_alias(self, alias: str) -> str:
            val = _jv3413_orig_resolve_alias(self, alias)
            if val:
                return val

            q = self.normalize_alias(alias)
            variants = {
                "build", "builds", "buil", "buils", "buid", "buidas",
                "buells", "buels", "boils", "boil", "boiled", "bools", "bool",
                "bills", "bilz", "biles", "builes", "bields", "bield",
                "bild", "bilds", "builts", "blinds",
            }
            if q in variants or (set(q.split()) & variants):
                val = _jv3413_orig_resolve_alias(self, "builds")
                if val:
                    return val

            return ""

        _jv3413_resolve_alias._jv3413_builds_fuzzy = True
        EventJournal.resolve_alias = _jv3413_resolve_alias
except Exception:
    pass

# ---------------------------------------------------------------------------
# v3.4.14 compatibility: normalize dictated artifact queries early
# ---------------------------------------------------------------------------
try:
    import re as _jv3414_re

    def _jv3414_clean_artifact_query(value):
        q = str(value or "").strip().lower()
        q = q.strip(" .,:;!?¡¿\"'“”‘’`")
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        aab_variants = {
            "aab", ".aab",
            "a a b", "a a ve", "aave",
            "a ap", "a a p", "aap",
            "a ab", "a abe", "a b",
            "abb", "aav", "ab",
        }
        apk_variants = {
            "apk", ".apk",
            "a p k", "a pe ka", "a p ka", "ap k", "a pk",
        }

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        q = _jv3414_re.sub(r"\ba\s+a\s+b\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+a\s+p\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s+ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ap\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*ab\b", "aab", q)
        q = _jv3414_re.sub(r"\ba\s*p\s*k\b", "apk", q)
        q = _jv3414_re.sub(r"\b(aap|abb|aave|aav)\b", "aab", q)
        q = _jv3414_re.sub(r"\s+", " ", q).strip()

        if q in aab_variants:
            return "aab"
        if q in apk_variants:
            return "apk"

        return q

    def _jv3414_clean_mapping(obj):
        if not isinstance(obj, dict):
            return obj
        for key in ("query", "search_query"):
            if key in obj:
                obj[key] = _jv3414_clean_artifact_query(obj.get(key))
        if isinstance(obj.get("params"), dict):
            _jv3414_clean_mapping(obj["params"])
        if isinstance(obj.get("entities"), dict):
            _jv3414_clean_mapping(obj["entities"])
        return obj

    def _jv3414_clean_any(obj):
        if obj is None:
            return obj

        if isinstance(obj, list):
            for i, item in enumerate(obj):
                obj[i] = _jv3414_clean_any(item)
            return obj

        if isinstance(obj, tuple):
            return tuple(_jv3414_clean_any(x) for x in obj)

        if isinstance(obj, dict):
            return _jv3414_clean_mapping(obj)

        # dataclass / normal objects used by Jarvis: Intent, SemanticAction, Plan, etc.
        for attr in ("query", "search_query"):
            if hasattr(obj, attr):
                try:
                    setattr(obj, attr, _jv3414_clean_artifact_query(getattr(obj, attr)))
                except Exception:
                    pass

        for attr in ("params", "entities"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, dict):
                        _jv3414_clean_mapping(val)
                except Exception:
                    pass

        for attr in ("steps", "planner_steps"):
            if hasattr(obj, attr):
                try:
                    val = getattr(obj, attr)
                    if isinstance(val, list):
                        setattr(obj, attr, _jv3414_clean_any(val))
                except Exception:
                    pass

        return obj
except Exception:
    pass

try:
    if "EventJournal" in globals() and hasattr(EventJournal, "normalize_steps") and not getattr(EventJournal.normalize_steps, "_jv3414_wrapped", False):
        _jv3414_orig_normalize_steps = EventJournal.normalize_steps

        def _jv3414_normalize_steps(steps):
            return _jv3414_clean_any(_jv3414_orig_normalize_steps(steps))

        _jv3414_normalize_steps._jv3414_wrapped = True
        EventJournal.normalize_steps = staticmethod(_jv3414_normalize_steps)
except Exception:
    pass

