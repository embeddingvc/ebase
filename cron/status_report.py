"""
Cron scheduler status for ``make status`` and the ``get_cron_status`` MCP tool.

Reads ``dashboard_routines.json``, probes the cron HTTP health endpoint, and
tails ``routine_ticks.jsonl`` / ``routine_runs.jsonl`` under the active
outreach data root.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cron import routine_scheduler, routines_config
from outreach.data_paths import outreach_base

_SWEEPS: tuple[tuple[str, str], ...] = (
    (routines_config.ROUTINE_KIND_CONNECTION_SYNC, "Connection sync"),
    (routines_config.ROUTINE_KIND_CONVERSATION_PLAN, "Conversation plan"),
)

_LAUNCHD_LABEL = "com.embeddingvc.ebase.cron"
_SYSTEMD_UNIT = "ebase-cron.service"
_CRON_PID_FILE = "storage/cron.pid"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _relative_ago(value: str | None, *, now: datetime | None = None) -> str:
    dt = _parse_iso(value)
    if dt is None:
        return "never"
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((now - dt).total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _tail_jsonl(path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def _last_event_for(
    routine_id: str,
    *,
    ticks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_at: datetime | None = None
    for row in ticks + runs:
        if row.get("routine_id") != routine_id:
            continue
        at = _parse_iso(row.get("finished_at") or row.get("started_at"))
        if at is None:
            continue
        if best_at is None or at > best_at:
            best = row
            best_at = at
    return best


def _gate_label(row: dict[str, Any]) -> str:
    if not row.get("active"):
        return "inactive"
    if not routines_config.in_active_window(row):
        return "outside window"
    return "ready"


def _window_label(start: str | None, end: str | None) -> str:
    if start and end:
        return f"{start}–{end}"
    return "always on"


def _event_summary(row: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    if not row:
        return {
            "at": None,
            "relative": "never",
            "status": None,
            "reason": None,
            "summary": "never",
        }
    at = row.get("finished_at") or row.get("started_at")
    status = row.get("status") or "unknown"
    reason = row.get("reason")
    relative = _relative_ago(at, now=now)
    detail = status if not reason else f"{status} · {reason}"
    return {
        "at": at,
        "relative": relative,
        "status": status,
        "reason": reason,
        "summary": f"{relative} · {detail}",
    }


def _cron_service_managed() -> tuple[bool, str | None, Path | None]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        path = home / "Library/LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        return path.is_file(), "launchd" if path.is_file() else None, path if path.is_file() else None
    if system == "Linux":
        path = home / ".config/systemd/user" / _SYSTEMD_UNIT
        return path.is_file(), "systemd" if path.is_file() else None, path if path.is_file() else None
    return False, None, None


def _persistence_notes(*, managed: bool, backend: str | None) -> list[str]:
    if managed and backend == "launchd":
        return [
            "Cron auto-start is enabled via launchd (starts at login and after reboot).",
        ]
    if managed and backend == "systemd":
        return [
            "Cron auto-start is enabled via systemd user service (starts at login).",
            "For headless hosts without a login session, run: loginctl enable-linger $USER",
        ]
    return [
        "Cron is not registered with launchd/systemd. "
        "Run ./install.sh or bin/cron-service install for reboot persistence.",
    ]


def _cron_health_url() -> str:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = os.environ.get("WEB_PORT", "3847")
    return f"http://{host}:{port}/health"


def _read_pid_file(base: Path) -> int | None:
    path = base / _CRON_PID_FILE
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool | None:
    if pid is None:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def probe_cron_server(*, base: Path | None = None) -> dict[str, Any]:
    """HTTP health probe plus optional PID file check."""
    base = base or outreach_base()
    url = _cron_health_url()
    pid = _read_pid_file(base)
    pid_alive = _pid_alive(pid)

    reachable = False
    scheduler: str | None = None
    health_error: str | None = None
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if isinstance(body, dict):
            reachable = bool(body.get("ok"))
            scheduler = body.get("scheduler")
    except urllib.error.URLError as exc:
        health_error = str(exc.reason or exc)
    except (json.JSONDecodeError, TimeoutError, OSError) as exc:
        health_error = str(exc)

    running = reachable and scheduler == "running"
    managed, backend, unit_path = _cron_service_managed()
    restart_hint = "bin/cron-service start"
    if not managed:
        restart_hint = "bin/cron-service install  (or ./install.sh)"
    return {
        "url": url,
        "reachable": reachable,
        "running": running,
        "scheduler": scheduler,
        "pid": pid,
        "pid_alive": pid_alive,
        "health_error": health_error,
        "managed": managed,
        "service_backend": backend,
        "service_unit_path": str(unit_path) if unit_path else None,
        "auto_start_on_reboot": managed,
        "restart_hint": restart_hint,
    }


def _sweep_status(
    sweep_id: str,
    label: str,
    row: dict[str, Any],
    *,
    ticks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    last = _last_event_for(sweep_id, ticks=ticks, runs=runs)
    return {
        "id": sweep_id,
        "label": label,
        "active": bool(row.get("active", True)),
        "window": _window_label(
            row.get("active_window_start"),
            row.get("active_window_end"),
        ),
        "gate": _gate_label(row),
        "last_event": _event_summary(last, now=now),
    }


def build_cron_status(*, now: datetime | None = None) -> dict[str, Any]:
    """Structured cron status for MCP tools and APIs."""
    now = now or datetime.now(timezone.utc)
    cfg = routines_config.load_config()
    kind = routines_config.get_scheduler_kind()
    base = outreach_base()
    ticks = _tail_jsonl(base / "logs" / "routine_ticks.jsonl")
    runs = _tail_jsonl(base / "logs" / "routine_runs.jsonl")
    server = probe_cron_server(base=base)

    sweeps: list[dict[str, Any]] = []
    if kind == routines_config.SCHEDULER_KIND_PER_PROSPECT:
        pp = cfg.get("per_prospect") or {}
        for sweep_id, label in _SWEEPS:
            sweeps.append(
                _sweep_status(
                    sweep_id,
                    label,
                    dict(pp.get(sweep_id) or {}),
                    ticks=ticks,
                    runs=runs,
                    now=now,
                )
            )
    else:
        for routine in cfg.get("routines") or []:
            rid = str(routine.get("id") or routine.get("skill") or "?")
            sweeps.append(
                {
                    "id": rid,
                    "label": routine.get("name") or rid,
                    "skill": routine.get("skill"),
                    "active": bool(routine.get("active")),
                    "interval_minutes": routine.get("interval_minutes"),
                    "window": _window_label(
                        routine.get("active_window_start"),
                        routine.get("active_window_end"),
                    ),
                    "gate": _gate_label(routine),
                    "last_run_at": routine.get("last_run_at"),
                    "last_status": routine.get("last_status"),
                    "last_event": _event_summary(
                        _last_event_for(rid, ticks=ticks, runs=runs),
                        now=now,
                    ),
                }
            )

    managed = bool(server.get("managed"))
    backend = server.get("service_backend")
    return {
        "checked_at": now.isoformat(),
        "data_root": str(base),
        "scheduler_kind": kind,
        "tick_seconds": routine_scheduler.TICK_SECONDS,
        "server": server,
        "sweeps": sweeps,
        "notes": _persistence_notes(managed=managed, backend=backend),
    }


def format_sweep_lines(*, now: datetime | None = None) -> list[str]:
    """Return indented status lines for ``make status``."""
    status = build_cron_status(now=now)
    server = status["server"]
    lines = [
        f"  scheduler  {status['scheduler_kind']}  tick={status['tick_seconds']}s",
        f"  data root  {status['data_root']}",
    ]
    if server.get("running"):
        pid = server.get("pid")
        pid_s = f"  pid={pid}" if pid else ""
        backend = server.get("service_backend")
        managed_s = f"  via {backend}" if backend else ""
        lines.append(f"  cron server  running{pid_s}{managed_s}  ({server['url']})")
    else:
        err = server.get("health_error")
        hint = server.get("restart_hint", "bin/cron-service install")
        extra = f" — {err}" if err else ""
        lines.append(f"  cron server  not running{extra}")
        lines.append(f"    restart: {hint}")
    if server.get("managed"):
        lines.append(f"    auto-start  {server.get('service_backend')}  ({server.get('service_unit_path')})")
    elif server.get("auto_start_on_reboot") is False:
        lines.append("    auto-start  not registered (run bin/cron-service install)")

    for sweep in status["sweeps"]:
        active = "yes" if sweep.get("active") else "no"
        lines.append(f"  {sweep['label']}")
        if sweep.get("skill") is not None:
            lines.append(f"    skill      {sweep.get('skill') or '—'}")
        if sweep.get("interval_minutes") is not None:
            lines.append(
                f"    active     {active}  every {sweep['interval_minutes']}m"
                f"  ({sweep['gate']})"
            )
        else:
            lines.append(
                f"    active     {active}  window {sweep['window']}  ({sweep['gate']})"
            )
        if sweep.get("last_run_at"):
            rel = _relative_ago(sweep["last_run_at"], now=now)
            lines.append(
                f"    last run   {rel} · {sweep.get('last_status') or 'unknown'}"
            )
        lines.append(f"    last event {sweep['last_event']['summary']}")

    return lines


def main() -> int:
    for line in format_sweep_lines():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
