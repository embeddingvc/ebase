"""
Scheduled skill routines for the dashboard background runner.

Each routine is a scheduled ``claude -p "Run {skill} skill"`` invocation.
Stored at ``{outreach_base}/config/dashboard_routines.json``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web.dashboard_data import _atomic_write_json, _read_json, outreach_base

CONFIG_NAME = "dashboard_routines.json"
RUNS_LOG = "routine_runs.jsonl"

# Canonical on-disk shape per routine row.
ROUTINE_FIELDS = frozenset(
    {
        "id",
        "name",
        "skill",
        "interval_minutes",
        "active",
        "active_window_start",
        "active_window_end",
        "last_run_at",
        "last_status",
        "last_error",
    }
)

# 24-hour "HH:MM" (00:00 – 23:59); empty/None means "no restriction".
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Default business-hours window applied to brand-new routines (server local time).
DEFAULT_WINDOW_START = "09:00"
DEFAULT_WINDOW_END = "17:00"

DEFAULT_ROUTINES: list[dict[str, Any]] = [
    {
        "id": "sync_pending",
        "name": "Sync Pending Connections",
        "skill": "sync-pending-connections",
        "interval_minutes": 30,
        "active": True,
        "active_window_start": DEFAULT_WINDOW_START,
        "active_window_end": DEFAULT_WINDOW_END,
    },
    {
        "id": "conversation_planner",
        "name": "Conversation Planner",
        "skill": "conversation-planner",
        "interval_minutes": 30,
        "active": True,
        "active_window_start": DEFAULT_WINDOW_START,
        "active_window_end": DEFAULT_WINDOW_END,
    },
]


def _normalize_time_str(value: Any) -> str | None:
    """Return canonical 'HH:MM' or None. Raises ValueError on invalid input."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if not _TIME_RE.match(s):
        raise ValueError(f"invalid time: {value!r} (expected HH:MM, 24h)")
    return s


def _coerce_time_str_silent(value: Any) -> str | None:
    """Like ``_normalize_time_str`` but drops invalid values instead of raising.

    Used when loading existing config so a hand-edited bad value can't brick
    the scheduler. The strict variant is used for the API write path.
    """
    try:
        return _normalize_time_str(value)
    except ValueError:
        return None


def _config_path() -> Path:
    base = outreach_base()
    path = base / "config" / CONFIG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _runs_log_path() -> Path:
    base = outreach_base()
    path = base / "logs" / RUNS_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _allowed_skills() -> frozenset[str]:
    from web.skill_runner import ALLOWED_SKILLS

    return ALLOWED_SKILLS


def _is_legacy_routine(row: dict[str, Any]) -> bool:
    """Old dashboard used stage-funnel rows without ``skill``."""
    if not row.get("skill"):
        return True
    if "stages" in row or "prospect_count" in row or "progress_pct" in row:
        return True
    return row.get("skill") not in _allowed_skills()


def _normalize_stored_routine(raw: dict[str, Any]) -> dict[str, Any]:
    rid = (raw.get("id") or "").strip() or str(uuid.uuid4())[:8]
    skill = (raw.get("skill") or "").strip()
    return {
        "id": rid,
        "name": (raw.get("name") or skill or rid).strip(),
        "skill": skill,
        "interval_minutes": max(1, int(raw.get("interval_minutes") or 30)),
        "active": bool(raw.get("active", False)),
        "active_window_start": _coerce_time_str_silent(raw.get("active_window_start")),
        "active_window_end": _coerce_time_str_silent(raw.get("active_window_end")),
        "last_run_at": raw.get("last_run_at"),
        "last_status": raw.get("last_status"),
        "last_error": raw.get("last_error"),
    }


def _migrate_routines(routines: list[Any] | None) -> list[dict[str, Any]]:
    if not routines:
        return [dict(r) for r in DEFAULT_ROUTINES]
    rows = [r for r in routines if isinstance(r, dict)]
    if not rows or any(_is_legacy_routine(r) for r in rows):
        return [dict(r) for r in DEFAULT_ROUTINES]
    return [_normalize_stored_routine(r) for r in rows]


def _skill_icon(skill: str) -> str:
    if "sync" in skill:
        return "sync"
    if "planner" in skill or "conversation" in skill:
        return "forum"
    if "connection" in skill:
        return "person_add"
    return "bolt"


def _display_status(routine: dict[str, Any]) -> str:
    if not routine.get("active"):
        return "disabled"
    last = routine.get("last_status")
    if last == "failed":
        return "error"
    if last in (None, "success", "running"):
        return "active"
    return "idle"


def _window_label(start: str | None, end: str | None) -> str | None:
    if not start or not end:
        return None
    return f"{start}\u2013{end}"


def _minutes_of_day(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return int(hh) * 60 + int(mm)


def in_active_window(
    routine: dict[str, Any], *, now: datetime | None = None
) -> bool:
    """True if ``routine`` may run at ``now`` (default: server local time).

    Unset/blank window means "always on". When ``start == end`` the routine
    would never run, so the validator forbids it; defensively we return False.
    Supports windows that cross midnight (``start > end``).
    """
    start = routine.get("active_window_start")
    end = routine.get("active_window_end")
    if not start or not end:
        return True
    now = now or datetime.now()
    minutes = now.hour * 60 + now.minute
    start_m = _minutes_of_day(start)
    end_m = _minutes_of_day(end)
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= minutes < end_m
    return minutes >= start_m or minutes < end_m


def to_display_routine(stored: dict[str, Any]) -> dict[str, Any]:
    """API shape for the Scheduled Routines list."""
    skill = stored.get("skill") or ""
    start = stored.get("active_window_start")
    end = stored.get("active_window_end")
    return {
        "id": stored.get("id"),
        "name": stored.get("name"),
        "skill": skill,
        "interval_minutes": stored.get("interval_minutes"),
        "active": bool(stored.get("active")),
        "active_window_start": start,
        "active_window_end": end,
        "active_window_label": _window_label(start, end),
        "last_run_at": stored.get("last_run_at"),
        "last_status": stored.get("last_status"),
        "last_error": stored.get("last_error"),
        "icon": _skill_icon(skill),
        "status": _display_status(stored),
    }


def load_config() -> dict[str, Any]:
    path = _config_path()
    raw = _read_json(path, None)
    existing = raw.get("routines") if isinstance(raw, dict) else None
    migrated = _migrate_routines(existing)
    data = {"routines": migrated}
    if existing != migrated:
        save_config(data)
    elif not path.is_file():
        save_config(data)
    return data


def save_config(data: dict[str, Any]) -> None:
    _atomic_write_json(_config_path(), data)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_run_log(
    *,
    routine_id: str,
    skill: str,
    status: str,
    started_at: str,
    finished_at: str,
    error: str | None = None,
    stdout_tail: str | None = None,
) -> None:
    path = _runs_log_path()
    row = {
        "routine_id": routine_id,
        "skill": skill,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "error": error,
        "stdout_tail": (stdout_tail or "")[-500:] if stdout_tail else None,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def update_routine_after_run(
    routine_id: str,
    *,
    status: str,
    error: str | None,
) -> None:
    data = load_config()
    for r in data.get("routines") or []:
        if r.get("id") == routine_id:
            r["last_run_at"] = _now_iso()
            r["last_status"] = status
            r["last_error"] = error
            break
    save_config(data)


def get_routines_for_api() -> dict[str, Any]:
    """Raw stored routines (for the Configure modal)."""
    data = load_config()
    routines = list(data.get("routines") or [])
    return {"routines": routines, "total": len(routines)}


def get_routines_display() -> dict[str, Any]:
    """Enriched routines for the dashboard list."""
    data = load_config()
    stored = list(data.get("routines") or [])
    routines = [to_display_routine(r) for r in stored]
    return {"routines": routines, "total": len(routines)}


def validate_routine(row: dict[str, Any]) -> str | None:
    skill = (row.get("skill") or "").strip()
    if skill not in _allowed_skills():
        return f"invalid skill: {skill}"
    interval = row.get("interval_minutes")
    if not isinstance(interval, (int, float)) or interval < 1:
        return "interval_minutes must be >= 1"
    if not (row.get("name") or "").strip():
        return "name required"
    try:
        start = _normalize_time_str(row.get("active_window_start"))
        end = _normalize_time_str(row.get("active_window_end"))
    except ValueError as exc:
        return str(exc)
    if (start is None) != (end is None):
        return "active_window_start and active_window_end must both be set or both blank"
    if start is not None and start == end:
        return "active_window_start and active_window_end must differ"
    return None


def upsert_routines(routines: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in routines:
        err = validate_routine(raw)
        if err:
            raise ValueError(err)
        row = _normalize_stored_routine(dict(raw))
        if row["id"] in seen:
            raise ValueError(f"duplicate routine id: {row['id']}")
        seen.add(row["id"])
        normalized.append(row)
    save_config({"routines": normalized})
    return get_routines_for_api()
