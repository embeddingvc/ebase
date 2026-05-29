"""
Scheduled routines for the dashboard background runner.

Two execution modes are supported (selected via the top-level
``scheduler_kind`` field in ``dashboard_routines.json``):

- ``"loop"`` (default, legacy): each routine is a ``claude -p "Run {skill} skill"``
  invocation. The skill itself fans out across connections inside one Claude call.
- ``"per_prospect"`` (new, see ``docs/designs/per-connection-routines-with-backoff-design.md``):
  the dashboard runs typed sweeps. ``connection_sync`` is a deterministic
  Python sweep (no LLM); ``conversation_plan`` dispatches a fresh ``claude -p``
  per actionable prospect with per-row exponential backoff and rate-limit
  awareness.

Config lives at ``{outreach_base}/config/dashboard_routines.json``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web.dashboard_data import _atomic_write_json, _read_json, outreach_base
from web.routine_backoff import PLAN_DEFAULT, SYNC_DEFAULT, BackoffPolicy

CONFIG_NAME = "dashboard_routines.json"
RUNS_LOG = "routine_runs.jsonl"

# Top-level scheduler flag controlling which executor the scheduler uses.
#
# The legacy ``"loop"`` mode (one ``claude -p "Run {skill} skill"`` per row,
# skill loops over connections inside the call) is preserved for ad-hoc
# routines pointing at single-prospect / single-action skills like
# ``send-connection-request``. The "all in one" skills it used to drive
# (``sync-pending-connections``, ``conversation-planner`` batch mode) have
# been removed; default installs now use ``"per_prospect"`` which dispatches
# typed sweeps from ``web.routine_scheduler``.
SCHEDULER_KIND_LOOP = "loop"
SCHEDULER_KIND_PER_PROSPECT = "per_prospect"
_VALID_SCHEDULER_KINDS = frozenset({SCHEDULER_KIND_LOOP, SCHEDULER_KIND_PER_PROSPECT})
DEFAULT_SCHEDULER_KIND = SCHEDULER_KIND_PER_PROSPECT

# Per-prospect routine kinds (the ``kind`` field on a per_prospect row).
ROUTINE_KIND_CONNECTION_SYNC = "connection_sync"
ROUTINE_KIND_CONVERSATION_PLAN = "conversation_plan"
_VALID_PER_PROSPECT_KINDS = frozenset(
    {ROUTINE_KIND_CONNECTION_SYNC, ROUTINE_KIND_CONVERSATION_PLAN}
)

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

# Legacy "loop" routines are no longer auto-created. The two old defaults
# (sync-pending-connections + conversation-planner batch) were the only
# all-in-one skills and have been removed; per-prospect sweeps in
# ``web.routine_scheduler`` cover the same ground without an LLM in the
# loop. Users can still add custom ``"loop"`` routines pointing at the
# remaining single-action skills via the dashboard.
DEFAULT_ROUTINES: list[dict[str, Any]] = []


def _backoff_to_dict(policy: BackoffPolicy) -> dict[str, Any]:
    return {
        "initial_minutes": policy.initial_minutes,
        "multiplier": policy.multiplier,
        "max_minutes": policy.max_minutes,
        "error_jitter": policy.error_jitter,
    }


DEFAULT_PER_PROSPECT_ROUTINES: dict[str, dict[str, Any]] = {
    ROUTINE_KIND_CONNECTION_SYNC: {
        "active": True,
        "active_window_start": DEFAULT_WINDOW_START,
        "active_window_end": DEFAULT_WINDOW_END,
        "backoff": _backoff_to_dict(SYNC_DEFAULT),
    },
    ROUTINE_KIND_CONVERSATION_PLAN: {
        "active": True,
        "active_window_start": DEFAULT_WINDOW_START,
        "active_window_end": DEFAULT_WINDOW_END,
        "backoff": _backoff_to_dict(PLAN_DEFAULT),
    },
}


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


# Skills that used to be auto-created routines but have been removed from
# the allow-list (their "all in one" loop behaviour is now owned by the
# per-prospect scheduler sweeps). Rows pointing at these are dropped during
# migration rather than retained as broken.
_REMOVED_LOOP_SKILLS = frozenset({"sync-pending-connections", "conversation-planner"})


def _is_legacy_routine(row: dict[str, Any]) -> bool:
    """Old dashboard used stage-funnel rows without ``skill``."""
    if not row.get("skill"):
        return True
    if "stages" in row or "prospect_count" in row or "progress_pct" in row:
        return True
    return row.get("skill") not in _allowed_skills()


def _is_removed_loop_routine(row: dict[str, Any]) -> bool:
    return (row.get("skill") or "").strip() in _REMOVED_LOOP_SKILLS


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
    if not rows:
        return [dict(r) for r in DEFAULT_ROUTINES]

    # Drop rows that point at skills we removed (all-in-one loop skills).
    # These previously auto-ran nightly even after the per-prospect sweep
    # took over the same workload, so we delete them on next load.
    rows = [r for r in rows if not _is_removed_loop_routine(r)]
    if not rows:
        return [dict(r) for r in DEFAULT_ROUTINES]

    if any(_is_legacy_routine(r) for r in rows):
        return [dict(r) for r in DEFAULT_ROUTINES]
    return [_normalize_stored_routine(r) for r in rows]


def _coerce_scheduler_kind(value: Any) -> str:
    raw = (str(value or "")).strip().lower()
    if raw in _VALID_SCHEDULER_KINDS:
        return raw
    return DEFAULT_SCHEDULER_KIND


def _normalize_per_prospect(
    raw: Any,
) -> dict[str, dict[str, Any]]:
    """Fill in defaults for the optional ``per_prospect`` config block.

    Missing routines or fields use the canonical defaults so a config edited
    by hand can never disable the new path by accident.
    """
    out: dict[str, dict[str, Any]] = {}
    src = raw if isinstance(raw, dict) else {}
    for kind, defaults in DEFAULT_PER_PROSPECT_ROUTINES.items():
        row_raw = src.get(kind)
        row = row_raw if isinstance(row_raw, dict) else {}

        backoff_raw = row.get("backoff")
        backoff_dict = backoff_raw if isinstance(backoff_raw, dict) else {}
        merged_backoff = dict(defaults["backoff"])
        for k in ("initial_minutes", "multiplier", "max_minutes"):
            v = backoff_dict.get(k)
            try:
                if v is not None:
                    merged_backoff[k] = (
                        float(v) if k == "multiplier" else int(v)
                    )
            except (TypeError, ValueError):
                pass
        if "error_jitter" in backoff_dict:
            merged_backoff["error_jitter"] = bool(backoff_dict["error_jitter"])
        merged_backoff["initial_minutes"] = max(
            1, int(merged_backoff["initial_minutes"])
        )
        merged_backoff["multiplier"] = max(1.0, float(merged_backoff["multiplier"]))
        merged_backoff["max_minutes"] = max(1, int(merged_backoff["max_minutes"]))

        out[kind] = {
            "active": bool(row.get("active", defaults["active"])),
            "active_window_start": _coerce_time_str_silent(
                row.get("active_window_start", defaults["active_window_start"])
            ),
            "active_window_end": _coerce_time_str_silent(
                row.get("active_window_end", defaults["active_window_end"])
            ),
            "backoff": merged_backoff,
        }
    return out


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
    existing_routines = raw.get("routines") if isinstance(raw, dict) else None
    existing_kind = raw.get("scheduler_kind") if isinstance(raw, dict) else None
    existing_pp = raw.get("per_prospect") if isinstance(raw, dict) else None

    migrated_routines = _migrate_routines(existing_routines)
    scheduler_kind = _coerce_scheduler_kind(existing_kind)
    per_prospect = _normalize_per_prospect(existing_pp)

    data: dict[str, Any] = {
        "scheduler_kind": scheduler_kind,
        "routines": migrated_routines,
        "per_prospect": per_prospect,
    }

    needs_save = (
        not path.is_file()
        or existing_routines != migrated_routines
        or existing_kind != scheduler_kind
        or existing_pp != per_prospect
    )
    if needs_save:
        save_config(data)
    return data


def save_config(data: dict[str, Any]) -> None:
    _atomic_write_json(_config_path(), data)


def set_scheduler_kind(kind: str) -> str:
    """Persist a new scheduler kind. Returns the normalized value actually written."""
    normalized = _coerce_scheduler_kind(kind)
    data = load_config()
    if data.get("scheduler_kind") != normalized:
        data["scheduler_kind"] = normalized
        save_config(data)
    return normalized


def upsert_per_prospect(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """Patch one per-prospect routine block; returns the updated section.

    Strict validation runs on the *merged input* (defaults + caller's patch)
    before the lenient normalizer clamps anything, so callers cannot sneak in
    a sub-1 multiplier or a negative interval. The lenient normalizer still
    runs after validation passes so the on-disk format stays canonical.
    """
    if kind not in _VALID_PER_PROSPECT_KINDS:
        raise ValueError(
            f"invalid per_prospect kind: {kind!r}; "
            f"expected one of {sorted(_VALID_PER_PROSPECT_KINDS)}"
        )

    data = load_config()
    pp = data.get("per_prospect") or _normalize_per_prospect({})
    merged_row = {**pp.get(kind, {}), **dict(row)}

    err = _validate_per_prospect_row_strict(merged_row)
    if err:
        raise ValueError(err)

    pp_normalized = _normalize_per_prospect({**pp, kind: merged_row})

    data["per_prospect"] = pp_normalized
    save_config(data)
    return pp_normalized


def _validate_per_prospect_row_strict(row: dict[str, Any]) -> str | None:
    """Strict validator used on user input — rejects values the lenient
    normalizer would silently clamp."""
    try:
        start = _normalize_time_str(row.get("active_window_start"))
        end = _normalize_time_str(row.get("active_window_end"))
    except ValueError as exc:
        return str(exc)
    if (start is None) != (end is None):
        return "active_window_start and active_window_end must both be set or both blank"
    if start is not None and start == end:
        return "active_window_start and active_window_end must differ"

    bo_raw = row.get("backoff")
    if bo_raw is None:
        return None  # caller wants to inherit defaults
    if not isinstance(bo_raw, dict):
        return "backoff must be an object"

    for k in ("initial_minutes", "max_minutes"):
        v = bo_raw.get(k)
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            return f"backoff.{k} must be a positive integer"
    mult = bo_raw.get("multiplier")
    if mult is not None:
        if isinstance(mult, bool) or not isinstance(mult, (int, float)) or mult < 1.0:
            return "backoff.multiplier must be >= 1.0"
    return None


def get_per_prospect_config() -> dict[str, Any]:
    """Public accessor for the per-prospect config block."""
    return dict(load_config().get("per_prospect") or {})


def get_scheduler_kind() -> str:
    return _coerce_scheduler_kind(load_config().get("scheduler_kind"))


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
    return {
        "routines": routines,
        "total": len(routines),
        "scheduler_kind": _coerce_scheduler_kind(data.get("scheduler_kind")),
        "per_prospect": dict(data.get("per_prospect") or {}),
    }


def get_routines_display() -> dict[str, Any]:
    """Enriched routines for the dashboard list."""
    data = load_config()
    stored = list(data.get("routines") or [])
    routines = [to_display_routine(r) for r in stored]
    return {
        "routines": routines,
        "total": len(routines),
        "scheduler_kind": _coerce_scheduler_kind(data.get("scheduler_kind")),
        "per_prospect": dict(data.get("per_prospect") or {}),
    }


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
