"""
Read-only outreach data for the web dashboard.

Mirrors ``tools.server._outreach_base()`` path resolution so UI and MCP stay aligned.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent
REPO_ROOT = WEB_DIR.parent

CDP_URL = os.environ.get("CDP_URL", "http://localhost:9222")
QUEUE_DIR = "queue"
LOGS_DIR = "logs"

MEETING_END_REASONS = frozenset({"call_scheduled"})
MEETING_NEXT_ACTIONS = frozenset({"confirm_meeting"})

def mock_mcp_enabled() -> bool:
    """Match tools.server._mock_mcp_enabled() (defaults to live)."""
    env = os.environ.get("OUTREACH_MOCK", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    if env in ("0", "false", "no"):
        return False
    return False


def outreach_base() -> Path:
    override = os.environ.get("OUTREACH_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if mock_mcp_enabled():
        return REPO_ROOT / "outreach" / "mock"
    return REPO_ROOT / "outreach"


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path, *, limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    if not path.is_file():
        return [], 0
    rows: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    total = 0
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        if total <= offset:
            continue
        if len(rows) < limit:
            rows.append(row)
    return rows, total


def _chrome_running(cdp_url: str = CDP_URL) -> tuple[bool, dict[str, Any] | None]:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return False, None


def _claude_cli_status() -> dict[str, Any]:
    path = shutil.which("claude")
    if not path:
        return {"status": "offline", "path": None, "detail": "claude CLI not on PATH"}
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(REPO_ROOT),
        )
        version = (proc.stdout or proc.stderr or "").strip() or "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        version = "unknown"
    return {"status": "online", "path": path, "detail": version}


def _linkedin_session_status(base: Path, cdp_online: bool) -> dict[str, Any]:
    if mock_mcp_enabled():
        sessions_path = base / "mock_linkedin_sessions.json"
        data = _read_json(sessions_path, {"sessions": {}})
        sessions = data.get("sessions") or {}
        active = sum(1 for s in sessions.values() if not s.get("ended"))
        return {
            "status": "mock",
            "detail": f"{len(sessions)} mock session(s), {active} active",
        }
    if cdp_online:
        return {
            "status": "assumed",
            "detail": "CDP connected — verify LinkedIn login in Chrome",
        }
    return {"status": "offline", "detail": "Start Chrome with make browser"}


def _queue_counts(base: Path) -> dict[str, int]:
    pending = _read_json(base / QUEUE_DIR / "pending.json", {"queue": []})
    completed = _read_json(base / QUEUE_DIR / "completed.json", {"completed": []})
    failed = _read_json(base / QUEUE_DIR / "failed.json", {"failed": []})
    p = len(pending.get("queue") or [])
    c = len(completed.get("completed") or [])
    f = len(failed.get("failed") or [])
    total = p + c + f
    load_pct = round(100 * p / total) if total else 0
    return {
        "pending": p,
        "completed": c,
        "failed": f,
        "load_pct": load_pct,
    }


def get_health() -> dict[str, Any]:
    cdp_online, cdp_info = _chrome_running()
    base = outreach_base()
    queue = _queue_counts(base)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "data_root": str(base),
        "mcp_mode": "mock" if mock_mcp_enabled() else "live",
        "claude_cli": _claude_cli_status(),
        "cdp_browser": {
            "status": "online" if cdp_online else "offline",
            "url": CDP_URL,
            "browser": (cdp_info or {}).get("Browser"),
            "detail": (cdp_info or {}).get("Browser")
            or ("Chrome DevTools reachable" if cdp_online else "Not reachable"),
        },
        "linkedin_session": _linkedin_session_status(base, cdp_online),
        "queue": queue,
    }


def _load_connections(base: Path) -> list[dict[str, Any]]:
    data = _read_json(base / "connections.json", {"connections": []})
    return list(data.get("connections") or [])


def _load_prospect(base: Path, prospect_id: str) -> dict[str, Any] | None:
    path = base / "prospects" / f"{prospect_id}.json"
    row = _read_json(path, None)
    return row if isinstance(row, dict) else None


def _load_conversation(base: Path, prospect_id: str) -> dict[str, Any] | None:
    path = base / "conversations" / f"{prospect_id}.json"
    row = _read_json(path, None)
    return row if isinstance(row, dict) else None


def _glob_conversations(base: Path) -> list[dict[str, Any]]:
    conv_dir = base / "conversations"
    if not conv_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(conv_dir.glob("*.json")):
        row = _read_json(path, None)
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _relative_time(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except (ValueError, TypeError):
        return None


def _relative_future(iso: str | None) -> str | None:
    """Render a future timestamp as 'in 2h', 'due now', etc.

    Returns ``None`` if ``iso`` is missing or unparseable. Returns
    ``"due now"`` when the timestamp is in the past or current minute so the
    UI can highlight rows the scheduler is actively considering.
    """
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = ts.astimezone(timezone.utc) - datetime.now(timezone.utc)
        secs = int(delta.total_seconds())
        if secs <= 60:
            return "due now"
        if secs < 3600:
            return f"in {secs // 60}m"
        if secs < 86400:
            return f"in {secs // 3600}h"
        return f"in {secs // 86400}d"
    except (ValueError, TypeError):
        return None


def _last_message_summary(conv: dict[str, Any] | None) -> str | None:
    if not conv:
        return None
    messages = conv.get("messages") or []
    if not messages:
        return conv.get("last_action")
    last = messages[-1]
    sender = last.get("sender", "")
    text = (last.get("text") or "")[:60]
    prefix = "Inbound" if sender == "prospect" else "Outbound"
    return f"{prefix}: {text}" if text else prefix


def _stage_label(stage: str | None, conn_status: str | None) -> str:
    mapping = {
        "cold": "Cold",
        "pending_connection": "Invite Sent",
        "engaged": "Connected",
        "replied": "Replied",
        "converted": "Converted",
        "ended": "Ended",
        "dead": "Dead",
    }
    if stage:
        return mapping.get(stage, stage.replace("_", " ").title())
    conn_labels = {
        "pending": "Invite Sent",
        "connected": "Connected",
        "ended": "Ended",
    }
    if conn_status:
        return conn_labels.get(conn_status, conn_status.replace("_", " ").title())
    return "Unknown"


_ROUTINE_LABELS = {
    "connection_sync": "Connection sync",
    "conversation_plan": "Conversation plan",
}


def _backoff_routine_for(connection_status: str | None) -> str | None:
    """Which per-prospect routine governs this row's next scheduler tick.

    ``pending`` rows are driven by the connection-sync sweep; everything else
    that's still actionable goes through the conversation-plan sweep. ``ended``
    rows have no live routine — we still surface the last ``plan_backoff``
    record for transparency but mark the next-run as N/A.
    """
    if connection_status == "pending":
        return "connection_sync"
    if connection_status == "ended":
        return None
    return "conversation_plan"


def _connection_routine_meta(conn: dict[str, Any]) -> dict[str, Any]:
    """Last/next per-prospect routine timestamps for the connections list.

    Reads from the row's ``sync_backoff`` / ``plan_backoff`` records (written
    by the per-prospect scheduler sweeps in ``web.connection_sync_sweep`` /
    ``web.conversation_plan_sweep``). Returns ``None`` fields when no record
    exists yet so the UI can render a neutral placeholder.
    """
    status = conn.get("connection_status")
    routine = _backoff_routine_for(status)
    sync_bo = conn.get("sync_backoff") if isinstance(conn.get("sync_backoff"), dict) else None
    plan_bo = conn.get("plan_backoff") if isinstance(conn.get("plan_backoff"), dict) else None

    if routine == "connection_sync":
        backoff = sync_bo
    elif routine == "conversation_plan":
        backoff = plan_bo
    else:
        backoff = plan_bo or sync_bo  # fallback for ended rows

    last_at = (backoff or {}).get("last_check_at")
    next_at = (backoff or {}).get("next_check_at") if routine else None
    return {
        "routine": routine,
        "routine_label": _ROUTINE_LABELS.get(routine) if routine else None,
        "last_run_at": last_at,
        "last_run_relative": _relative_time(last_at),
        "next_run_at": next_at,
        "next_run_relative": _relative_future(next_at) if routine else None,
        "current_interval_minutes": (backoff or {}).get("current_interval_minutes"),
        "last_result": (backoff or {}).get("last_result"),
    }


def _connection_display_row(base: Path, conn: dict[str, Any]) -> dict[str, Any]:
    """Build one connections-tab row: identity from ``connections.json``, stage from conversation."""
    pid = (conn.get("prospect_id") or "").strip()
    conv = _load_conversation(base, pid) if pid else None

    prospect = None
    if pid and not (conn.get("name") and conn.get("title") and conn.get("profile_url")):
        prospect = _load_prospect(base, pid)

    name = conn.get("name") or (prospect or {}).get("name") or pid
    title = conn.get("title") or (prospect or {}).get("title") or ""
    profile_url = conn.get("profile_url") or (prospect or {}).get("linkedin_url")
    connection_status = conn.get("connection_status")
    stage = (conv or {}).get("outreach_stage")
    last_ts = (conv or {}).get("last_action_timestamp") or conn.get("connected_at")

    return {
        "prospect_id": pid,
        "name": name,
        "title": title,
        "profile_url": profile_url,
        "connection_status": connection_status,
        "connected_at": conn.get("connected_at"),
        "note_sent": conn.get("note_sent"),
        "outreach_stage": stage,
        "stage_label": _stage_label(stage, connection_status),
        "sequence_step": (conv or {}).get("sequence_step"),
        "last_action": (conv or {}).get("last_action"),
        "last_action_summary": _last_message_summary(conv),
        "last_action_at": last_ts,
        "last_action_relative": _relative_time(last_ts),
        "initials": _initials(str(name)),
        "routine_schedule": _connection_routine_meta(conn),
    }


def get_connections() -> dict[str, Any]:
    base = outreach_base()
    rows = [_connection_display_row(base, conn) for conn in _load_connections(base)]
    rows.sort(key=lambda r: r.get("last_action_at") or "", reverse=True)
    return {"total": len(rows), "connections": rows}


def get_routines() -> dict[str, Any]:
    from web import routines_config

    base = outreach_base()
    payload = routines_config.get_routines_display()
    for r in payload.get("routines") or []:
        r["last_run_relative"] = _relative_time(r.get("last_run_at"))

    planner = _read_json(base / "config" / "conversation_planner.json", {})
    campaign = (planner.get("campaign") or {}).get("goal")
    payload["campaign_goal"] = campaign
    return payload


def _duration_label(started_at: str | None, finished_at: str | None) -> str | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        secs = int((finished - started).total_seconds())
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"
    except (ValueError, TypeError):
        return None


def get_execution_history(*, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    """Routine skill runs from ``logs/routine_runs.jsonl`` only."""
    from web import routines_config

    base = outreach_base()
    entries: list[dict[str, Any]] = []
    names = {
        r["id"]: r.get("name")
        for r in routines_config.load_config().get("routines") or []
        if r.get("id")
    }

    runs_path = base / LOGS_DIR / "routine_runs.jsonl"
    if runs_path.is_file():
        try:
            for line in runs_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                routine_id = row.get("routine_id") or ""
                skill = row.get("skill") or ""
                started_at = row.get("started_at")
                finished_at = row.get("finished_at")
                entries.append(
                    {
                        "id": f"routine-{routine_id}-{finished_at}",
                        "routine_id": routine_id,
                        "routine_name": names.get(routine_id) or skill or routine_id,
                        "skill": skill,
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "duration_label": _duration_label(started_at, finished_at),
                        "status": row.get("status") or "success",
                        "source": "routine_scheduler",
                        "note": row.get("error") or row.get("stdout_tail"),
                    }
                )
        except OSError:
            pass

    entries.sort(key=lambda e: e.get("started_at") or "", reverse=True)
    total = len(entries)
    page = entries[offset : offset + limit]

    completed_n = sum(1 for e in entries if e.get("status") == "success")
    failed_n = sum(1 for e in entries if e.get("status") in ("failed", "error"))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "stats": {
            "success_rate_pct": round(100 * completed_n / total, 1) if total else None,
            "total_events": total,
            "failures": failed_n,
            "pending": 0,
        },
        "entries": page,
    }


def _is_meeting_interest(conv: dict[str, Any], prospect: dict[str, Any] | None) -> bool:
    if conv.get("meeting_link"):
        return True
    if conv.get("ended_reason") in MEETING_END_REASONS:
        return True
    if conv.get("next_action") in MEETING_NEXT_ACTIONS:
        return True
    if (prospect or {}).get("end_goal") == "schedule_meeting" and conv.get("email"):
        return True
    if conv.get("email") and conv.get("ended_reason") in MEETING_END_REASONS:
        return True
    stage = conv.get("outreach_stage")
    if stage == "converted" and (conv.get("email") or conv.get("meeting_link")):
        return True
    return False


def _meeting_channel(link: str | None) -> str | None:
    if not link:
        return None
    lower = link.lower()
    if "zoom" in lower:
        return "Zoom"
    if "meet.google" in lower or "google.com/calendar" in lower:
        return "Google Meet"
    if "teams" in lower:
        return "Microsoft Teams"
    return "Video call"


def get_meetings() -> dict[str, Any]:
    base = outreach_base()
    connections = {c.get("prospect_id"): c for c in _load_connections(base)}
    meetings: list[dict[str, Any]] = []

    for conv in _glob_conversations(base):
        if not _is_meeting_interest(conv, None):
            continue
        pid = conv.get("prospect_id") or ""
        prospect = _load_prospect(base, pid)
        conn = connections.get(pid) or {}
        name = (prospect or {}).get("name") or conn.get("name") or pid
        title = (prospect or {}).get("title") or conn.get("title") or ""
        link = conv.get("meeting_link")
        meetings.append(
            {
                "prospect_id": pid,
                "name": name,
                "title": title,
                "profile_url": conn.get("profile_url") or (prospect or {}).get("linkedin_url"),
                "email": conv.get("email"),
                "meeting_link": link,
                "channel": _meeting_channel(link),
                "outreach_stage": conv.get("outreach_stage"),
                "ended_reason": conv.get("ended_reason"),
                "scheduled_at": conv.get("ended_at") or conv.get("last_action_timestamp"),
                "scheduled_relative": _relative_time(
                    conv.get("ended_at") or conv.get("last_action_timestamp")
                ),
                "interest_summary": conv.get("ended_reason") or conv.get("next_action"),
                "initials": _initials(str(name)),
            }
        )

    meetings.sort(key=lambda m: m.get("scheduled_at") or "", reverse=True)

    with_link = sum(1 for m in meetings if m.get("meeting_link"))
    with_email = sum(1 for m in meetings if m.get("email"))

    return {
        "total": len(meetings),
        "with_meeting_link": with_link,
        "with_email": with_email,
        "meetings": meetings,
    }


def get_summary() -> dict[str, Any]:
    base = outreach_base()
    connections = get_connections()
    meetings = get_meetings()
    routines = get_routines()
    health = get_health()
    pending_conn = sum(
        1
        for c in connections["connections"]
        if c.get("connection_status") == "pending"
    )
    return {
        "connections_total": connections["total"],
        "connections_pending": pending_conn,
        "meetings_total": meetings["total"],
        "active_routines": sum(1 for r in routines["routines"] if r.get("active")),
        "queue_pending": health["queue"]["pending"],
        "mcp_mode": health["mcp_mode"],
    }
